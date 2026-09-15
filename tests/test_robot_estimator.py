import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import Mock, patch


PATH = Path(__file__).resolve().parents[1] / 'xt30-battery/src/worker.py'
SPEC = importlib.util.spec_from_file_location('robot_estimator', PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class FakeMemory(worker.Memory):
    def __init__(self):
        self.base = 0xB6E6B000
        self.data = bytearray(0xBA000)
        self.writes = []
        for address in worker.READ_LITERALS + (worker.RECEIVE_LITERAL,):
            self.data[address:address + 4] = worker.OLD_LITERAL
        self.data[worker.GOT_SLOT:worker.GOT_SLOT + 4] = struct.pack('<I', self.base + worker.CACHE)

    def read(self, rva, size):
        return bytes(self.data[rva:rva + size])

    def write(self, rva, data):
        self.writes.append((rva, data))
        self.data[rva:rva + len(data)] = data


class RobotEstimatorTests(unittest.TestCase):
    def test_watchdog_restores_on_heartbeat_timeout_offline(self):
        memory = FakeMemory()
        record = struct.pack('<HhiBB', 12250, 0, 0, 0, 0)
        with patch.object(worker.signal, 'signal'), patch.object(worker.os, 'write'), \
                patch.object(worker.os, 'close'), patch.object(worker, 'identity', return_value='same'), \
                patch.object(worker, 'emit') as emit, \
                patch.object(worker.select, 'select', return_value=([], [], [])), \
                patch.object(worker.os, '_exit', side_effect=SystemExit(0)):
            with self.assertRaises(SystemExit):
                # SIGHUP is absent on Windows; provide the constant for this
                # simulation. No process, signal, or robot access occurs.
                with patch.object(worker.signal, 'SIGHUP', 1, create=True):
                    worker.watchdog(memory, 10, 11, 123, 'same', record, 88)
        memory.validate()
        emit.assert_any_call('restored', reason='heartbeat_timeout', hdvt_pid=123)

    def test_watchdog_restores_when_parent_pipe_closes_offline(self):
        memory = FakeMemory()
        record = struct.pack('<HhiBB', 12250, 0, 0, 0, 0)
        with patch.object(worker.signal, 'signal'), patch.object(worker.os, 'write'), \
                patch.object(worker.os, 'close'), patch.object(worker, 'identity', return_value='same'), \
                patch.object(worker, 'emit') as emit, patch.object(worker.os, 'read', return_value=b''), \
                patch.object(worker.select, 'select', return_value=([10], [], [])), \
                patch.object(worker.os, '_exit', side_effect=SystemExit(0)), \
                patch.object(worker.signal, 'SIGHUP', 1, create=True):
            with self.assertRaises(SystemExit):
                worker.watchdog(memory, 10, 11, 123, 'same', record, 88)
        memory.validate()
        emit.assert_any_call('restored', reason='parent_closed_pipe', hdvt_pid=123)

    def test_curve_and_voltage_limits(self):
        self.assertEqual(worker.percent_from_mv(12600), 100)
        self.assertEqual(worker.percent_from_mv(12250), 88)
        self.assertEqual(worker.percent_from_mv(9000), 0)
        values = [worker.percent_from_mv(v) for v in range(9000, 12801)]
        self.assertEqual(values, sorted(values))
        for voltage in (9299, 12801):
            with self.assertRaises(RuntimeError):
                worker.Estimate().sample(voltage, 0)

    def test_no_fast_upward_recovery(self):
        estimate = worker.Estimate()
        self.assertEqual(estimate.sample(12000, 0), 80)
        for index in range(1, 50):
            estimate.sample(12300, index)
        self.assertEqual(estimate.displayed, 80)

    def test_short_load_sags_do_not_change_the_display(self):
        for duration in (0.5, 2, 5, 10):
            with self.subTest(duration=duration):
                estimate = worker.Estimate()
                percentages = []
                for tick in range(480):
                    now = tick / 4
                    voltage = 11500 if 40 <= now < 40 + duration else 12250
                    percentages.append(estimate.sample(voltage, now))
                self.assertEqual(set(percentages), {88})

    def test_sustained_lower_voltage_is_not_hidden_by_the_median(self):
        estimate = worker.Estimate()
        for tick in range(480):
            now = tick / 4
            result = estimate.sample(12250 if now < 40 else 11500, now)
        self.assertLessEqual(result, 54)

    def test_invalid_raw_voltage_is_rejected_before_display_filtering(self):
        estimate = worker.Estimate()
        for tick in range(120):
            estimate.sample(12250, tick / 4)
        with self.assertRaisesRegex(RuntimeError, '9000 mV'):
            estimate.sample(9000, 30)

    def test_presence_frame_uses_only_the_reviewed_native_status_command(self):
        spec = importlib.util.spec_from_file_location('wire_for_presence', PATH.with_name('telemetry.py'))
        wire = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wire)
        msg = wire.unpack(worker.presence_frame(0x1234))
        self.assertEqual((msg['sender'], msg['receiver'], msg['set'], msg['command'], msg['flags']),
                         (3, 0x28, 0, 0xf1, 0))
        self.assertEqual(msg['payload'], bytes.fromhex('01ff0a'))
        self.assertEqual(msg['sequence'], 0x1234)

    def test_presence_refuses_stale_voltage_and_native_battery_data(self):
        presence = worker.BatteryPresence.__new__(worker.BatteryPresence)
        presence.sock = Mock()
        presence.validate = Mock()
        presence.last_voltage = 12250
        presence.last_change = 0
        presence.next_send = 0
        record = struct.pack('<HhiBB', 12250, 0, 0, 0, 0)
        with self.assertRaisesRegex(RuntimeError, 'unchanged'):
            presence.update(record, 1.01)
        with self.assertRaisesRegex(RuntimeError, 'invalid native'):
            presence.update(struct.pack('<HhiBB', 12255, 230, 0, 0, 0), 0.1)
        presence.sock.sendto.assert_not_called()

    def test_presence_guard_refuses_a_nonempty_battery_diagnostic_list(self):
        presence = worker.BatteryPresence.__new__(worker.BatteryPresence)
        presence.pid, presence.started = 1, 'same'
        presence.instance_slot, presence.instance = 0x1000, 0x2000
        memory = {0x1000: struct.pack('<I', 0x2000), 0x204c: b'\x01',
                  0x2064: b'\x00', 0x2074: struct.pack('<II', 0x3000, 0x3000)}
        presence.read = lambda address, size: memory[address]
        with patch.object(worker, 'identity', return_value='same'):
            with self.assertRaisesRegex(RuntimeError, 'diagnostics present'):
                presence.validate(initial=True)

    def test_watchdog_closes_presence_on_parent_timeout(self):
        memory = FakeMemory()
        record = struct.pack('<HhiBB', 12250, 0, 0, 0, 0)
        with patch.object(worker, 'BatteryPresence') as factory, \
                patch.object(worker.signal, 'signal'), patch.object(worker.os, 'write'), \
                patch.object(worker.os, 'close'), patch.object(worker, 'identity', return_value='same'), \
                patch.object(worker, 'emit'), \
                patch.object(worker.select, 'select', return_value=([], [], [])), \
                patch.object(worker.os, '_exit', side_effect=SystemExit(0)), \
                patch.object(worker.signal, 'SIGHUP', 1, create=True):
            with self.assertRaises(SystemExit):
                worker.watchdog(memory, 10, 11, 123, 'same', record, 88, True)
        factory.return_value.close.assert_called_once()
        factory.return_value.update.assert_not_called()
        memory.validate()

    def test_restore_keeps_inflight_reader_pointer_valid(self):
        memory = FakeMemory()
        memory.validate()
        original = struct.pack('<HhiBB', 12250, 0, 0, 0, 0)
        memory.install(original, 88)
        self.assertEqual(memory.read(worker.STORAGE + 12, 1), b'X')
        self.assertEqual(memory.read(worker.RECEIVE_LITERAL, 4), worker.OLD_LITERAL)
        memory.writes.clear()
        memory.restore()
        self.assertEqual(memory.writes[0], (worker.STORAGE, struct.pack('<I', memory.base + worker.CACHE)))
        for address in worker.READ_LITERALS:
            self.assertEqual(memory.read(address, 4), worker.OLD_LITERAL)
        memory.validate()  # retained storage can be reused without rebooting

    def test_refuses_unknown_live_modification(self):
        memory = FakeMemory()
        memory.data[worker.READ_LITERALS[0]] ^= 1
        with self.assertRaises(RuntimeError):
            memory.validate()
        self.assertEqual(memory.writes, [])

    def test_refuses_occupied_padding_and_unknown_firmware(self):
        memory = FakeMemory()
        memory.data[worker.STORAGE] = 1
        with self.assertRaises(RuntimeError):
            memory.validate()
        with self.assertRaises(RuntimeError):
            worker.validate_image(bytes(1024))

    def test_dry_run_has_no_process_access(self):
        class Args:
            execute = False
            duration = 15
        with patch.object(worker, 'emit'), patch.object(worker, 'find_process', side_effect=AssertionError):
            worker.run(Args())


if __name__ == '__main__':
    unittest.main()
