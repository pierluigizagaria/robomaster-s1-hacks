"""Execute the actual bundled ARM hook in Unicorn, plus guarded RAM lifecycle tests."""
import contextlib
import importlib.util
from pathlib import Path
import struct
import sys
import types
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_INTR
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3
from unicorn.arm_const import UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7
from unicorn.arm_const import UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11
from unicorn.arm_const import UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('warning_runtime', ROOT / 'src/warning_filter.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
BLOB = runtime.native()


def roster(modules):
    out = bytearray([len(modules)])
    for module, codes in modules:
        out.extend(struct.pack('<HB', module, len(codes)))
        out.extend(struct.pack('<%dH' % len(codes), *codes))
    return bytes(out)


def event(payload, command=0x003F0012, receiver=0x0200):
    return struct.pack('<IHHHHI', command, receiver, 0, 17, 0, len(payload)) + payload


class EmulatedHook:
    CODE, INPUT, STACK, SEND, EXIT = 0x10000, 0x20000, 0x30000, 0x40000, 0x41000
    def __init__(self):
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        for base, size in ((self.CODE, 0x1000), (self.INPUT, 0x2000),
                           (self.STACK, 0x10000), (self.SEND, 0x2000)):
            self.uc.mem_map(base, size)
        self.uc.mem_write(self.CODE, BLOB.BLOB)
        self.uc.hook_add(UC_HOOK_CODE, self.send, begin=self.SEND, end=self.SEND)
        self.uc.hook_add(UC_HOOK_INTR, self.clock)
        self.preserved = [UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                          UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11]

    def clock(self, uc, number, data):
        if uc.reg_read(UC_ARM_REG_R7) != 263 or uc.reg_read(UC_ARM_REG_R0) != 1:
            raise AssertionError('unexpected syscall')
        uc.mem_write(uc.reg_read(UC_ARM_REG_R1), struct.pack('<II', self.now, 0))
        uc.reg_write(UC_ARM_REG_R0, self.clock_result)

    def send(self, uc, address, size, data):
        self.handle = uc.reg_read(UC_ARM_REG_R0)
        pointer = uc.reg_read(UC_ARM_REG_R1)
        length = struct.unpack('<I', uc.mem_read(pointer + 12, 4))[0]
        self.result = bytes(uc.mem_read(pointer, 16 + length))
        for reg in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R12):
            uc.reg_write(reg, 0xDEADBEEF)
        uc.reg_write(UC_ARM_REG_R0, 0x12345678)
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def run(self, data, until=103, now=100, clock_result=0):
        self.now, self.clock_result, self.result = now, clock_result, None
        uc = self.uc
        uc.mem_write(self.CODE, struct.pack('<II', self.SEND | 1, until) + runtime.MAGIC)
        uc.mem_write(self.INPUT, data)
        original = bytes(uc.mem_read(self.INPUT, len(data)))
        uc.reg_write(UC_ARM_REG_R0, 0x777)
        uc.reg_write(UC_ARM_REG_R1, self.INPUT)
        for i, reg in enumerate(self.preserved):
            uc.reg_write(reg, 0xABC000 + i)
        uc.reg_write(UC_ARM_REG_SP, self.STACK + 0xF000)
        uc.reg_write(UC_ARM_REG_LR, self.EXIT | 1)
        uc.emu_start(self.CODE + BLOB.ENTRY, self.EXIT, count=1000000)
        assert uc.reg_read(UC_ARM_REG_PC) == self.EXIT, 'hook failed to return'
        assert uc.reg_read(UC_ARM_REG_SP) == self.STACK + 0xF000, 'stack corrupted'
        assert uc.reg_read(UC_ARM_REG_R0) == 0x12345678, 'native result not propagated'
        assert self.handle == 0x777
        assert bytes(uc.mem_read(self.INPUT, len(data))) == original, 'original event mutated'
        for i, reg in enumerate(self.preserved):
            assert uc.reg_read(reg) == 0xABC000 + i, 'callee-saved register corrupted'
        return self.result


class NativeHookTests(unittest.TestCase):
    def setUp(self):
        self.hook = EmulatedHook()

    def test_exact_pair_removed_and_all_other_diagnostic_words_preserved(self):
        for start in range(0, 65536, 255):
            codes = list(range(start, min(65536, start + 255)))
            expected = [x for x in codes if x not in (0xC205, 0xC209)]
            self.assertEqual(self.hook.run(event(roster([(0x300, codes)]))),
                             event(roster([(0x300, expected)])))

    def test_all_module_ids_retain_both_codes_except_chassis(self):
        for start in range(0, 65536, 140):
            modules = [(i, [0xC205, 0xC209]) for i in range(start, min(65536, start + 140))]
            expected = [(i, [] if i == 0x300 else codes) for i, codes in modules]
            self.assertEqual(self.hook.run(event(roster(modules))), event(roster(expected)))

    def test_expired_missing_invalid_and_failed_clock_lease_pass_through(self):
        raw = event(roster([(0x300, [0xC205, 0xC209])]))
        for until in (0, 99, 100, 104, 0xFFFFFFFF):
            self.assertEqual(self.hook.run(raw, until=until), raw)
        self.assertEqual(self.hook.run(raw, clock_result=0xFFFFFFFF), raw)

    def test_other_destinations_and_commands_pass_through(self):
        payload = roster([(0x300, [0xC205, 0xC209])])
        for dest in (0x905, 0x1C00, 0x201, 0):
            raw = event(payload, receiver=dest)
            self.assertEqual(self.hook.run(raw), raw)
        for command in (0x48_0008, 0x003F0011, 0, 0x403F0012):
            raw = event(payload, command=command)
            self.assertEqual(self.hook.run(raw), raw)

    def test_malformed_and_duplicate_module_payloads_pass_through(self):
        valid = roster([(0x300, [0xC205, 0xC209])])
        cases = [valid[:i] for i in range(len(valid))]
        cases += [valid + b'\x00', roster([(0x300, []), (0x300, [0xC209])]), bytes(1025)]
        # A structurally valid roster beyond the native send limit stays original.
        cases += [roster([(0x300, [0xC205] * 251), (0x400, [0xC209] * 250)])]
        for payload in cases:
            raw = event(payload)
            self.assertEqual(self.hook.run(raw), raw)

    def test_zero_diagnostics_keep_chassis_and_battery_present(self):
        raw = event(roster([(0x300, [0xC205, 0xC209]), (0x30A, [])]))
        self.assertEqual(self.hook.run(raw), event(roster([(0x300, []), (0x30A, [])])))


class FakeMemory(runtime.WarningFilter):
    def __init__(self):
        self.image = BLOB
        self.base = 0x10000
        self.hook = self.base + runtime.PAD + BLOB.ENTRY
        self.original = 0x777001
        self.pid, self.started = 123, 'start'
        self.memory = bytearray(0x60000)
        self.memory[runtime.GOT:runtime.GOT+4] = struct.pack('<I', self.original)
        self.retained, self.owned, self.fd = False, False, None
        self.dead = False
    def check_identity(self):
        if self.dead:
            raise RuntimeError('restarted')
    def read(self, rva, size):
        return bytes(self.memory[rva:rva+size])
    def write(self, rva, data):
        self.check_identity()
        self.memory[rva:rva+len(data)] = data


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.pause = patch.object(runtime, 'paused', lambda *args: contextlib.nullcontext())
        self.pause.start()
        self.addCleanup(self.pause.stop)
        self.clock = patch.object(runtime.time, 'monotonic', return_value=100)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_install_restore_retains_immutable_code(self):
        ram = FakeMemory()
        ram.install()
        self.assertEqual(ram.pointer(), ram.hook)
        self.assertTrue(ram.status()['filter_active'])
        code = ram.read(runtime.PAD + 16, len(BLOB.BLOB)-16)
        ram.restore()
        ram.verify_restored()
        self.assertEqual(ram.read(runtime.PAD + 16, len(code)), code)
        self.assertEqual(ram.pointer(), ram.original)
        self.assertEqual(ram.read(runtime.PAD + 4, 4), bytes(4))

    def test_orphan_recovery_refuses_live_lease_then_restores_expired(self):
        ram = FakeMemory()
        ram.install()
        ram.owned, ram.retained = False, True
        with self.assertRaisesRegex(RuntimeError, 'live lease'):
            ram.recover_expired()
        with patch.object(runtime.time, 'monotonic', return_value=103):
            ram.recover_expired()
        ram.verify_restored()

    def test_competing_pointer_is_never_overwritten(self):
        ram = FakeMemory()
        ram.install()
        ram.memory[runtime.GOT:runtime.GOT+4] = struct.pack('<I', 0x999001)
        with self.assertRaisesRegex(RuntimeError, 'refusing overwrite'):
            ram.restore()
        self.assertEqual(ram.pointer(), 0x999001)
        self.assertEqual(ram.read(runtime.PAD + 4, 4), bytes(4))

    def test_process_restart_refuses_writes(self):
        ram = FakeMemory()
        ram.install()
        ram.dead = True
        snapshot = bytes(ram.memory)
        with self.assertRaisesRegex(RuntimeError, 'restarted'):
            ram.restore()
        self.assertEqual(bytes(ram.memory), snapshot)

    def test_changed_immutable_code_stops_lease_refresh(self):
        ram = FakeMemory()
        ram.install()
        ram.memory[runtime.PAD + 32] ^= 1
        with self.assertRaisesRegex(RuntimeError, 'code or config'):
            ram.update()
        ram.restore()
        self.assertEqual(ram.pointer(), ram.original)

    def test_partial_install_failure_keeps_rollback_responsibility(self):
        ram = FakeMemory()
        with patch.object(ram, 'update', side_effect=OSError('write denied')):
            with self.assertRaises(OSError):
                ram.install()
        self.assertTrue(ram.owned)
        ram.restore()
        ram.verify_restored()


class WatchdogCleanupTests(unittest.TestCase):
    def test_warning_close_failure_does_not_block_battery_reader_restore(self):
        spec = importlib.util.spec_from_file_location('warning_test_worker', ROOT / 'src/worker.py')
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        memory, warning = Mock(), Mock(pid=123)
        warning.install.side_effect = RuntimeError('installation failed')
        warning.close.side_effect = OSError('close failed')
        module = types.SimpleNamespace(WarningFilter=lambda: warning)
        # A sentinel replaces os._exit; no real process, memory, or signal touched.
        class Exited(Exception):
            pass
        with patch.dict(sys.modules, {'warning_filter': module}), \
                patch.object(worker.signal, 'SIGHUP', 1, create=True), \
                patch.object(worker.signal, 'signal'), patch.object(worker, 'identity', return_value='same'), \
                patch.object(worker, 'emit'), patch.object(worker.os, '_exit', side_effect=Exited):
            with self.assertRaises(Exited):
                worker.watchdog(memory, 1, 2, 3, 'same', bytes(10), 50, battery_warnings=True)
        warning.restore.assert_called_once()
        memory.restore.assert_called_once()


if __name__ == '__main__':
    unittest.main()
