#!/usr/bin/env python3
"""Experimental robot-only battery estimator; Python 3.6, run with -S.

Dry-run by default. The guarded live test changes two data literals in the
known HDVT process's private RAM to publish a shadow battery record. It never
writes executable files or controller parameters. A separate watchdog restores
the original data source on exit, signal, missing heartbeat, or parent death.
This changes telemetry only; it is not a low-battery motion-stop mechanism.
"""
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import select
import signal
import struct
import sys
import time

sys.dont_write_bytecode = True

_spec = importlib.util.spec_from_file_location(
    's1_process_guard', os.path.join(os.path.dirname(__file__), 'process_guard.py'))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


EXE = '/system/bin/dji_hdvt_uav'
SHA256 = '19d957e93672ce105d09eec509ec2fb873c8eb69a9287e0a505a6438538b2b38'
SYSTEM_EXE = '/system/bin/dji_sys'
SYSTEM_SHA256 = 'fb0df0de6080231c83fc1f87584a5baa4f237040a0ad3f2ce3cf3ef1466a8181'
MEDIAN_SAMPLES = 120  # 30 seconds at the worker's 250 ms sampling cadence
GOT = 0xB0C1C
CACHE = 0xB94A6
GOT_SLOT = 0xB0928
READ_LITERALS = (0x132E8, 0x3B2B8)
RECEIVE_LITERAL = 0x3C5B0
OLD_LITERAL = struct.pack('<i', GOT_SLOT - GOT)
STORAGE = 0xADA00
STORAGE_SIZE = 32
MAGIC = b'S1BATT01'
NEW_LITERAL = struct.pack('<i', STORAGE - GOT)
LOCK = '/tmp/s1-battery-estimator.lock'
CURVE = ((3000, 0), (3450, 5), (3680, 10), (3740, 20),
         (3770, 30), (3790, 40), (3820, 50), (3870, 60),
         (3930, 70), (4000, 80), (4100, 90), (4200, 100))


def emit(event, **fields):
    fields['event'] = event
    fields['monotonic'] = time.monotonic()
    data = (json.dumps(fields, sort_keys=True) + '\n').encode('ascii')
    os.write(1, data)


def emit_cleanup(event, **fields):
    # A full/closed log must not interrupt restoration of another native hook.
    try:
        emit(event, **fields)
    except OSError:
        pass


def percent_from_mv(pack_mv):
    cell = pack_mv // 3
    if cell <= CURVE[0][0]:
        return 0
    for (v0, p0), (v1, p1) in zip(CURVE, CURVE[1:]):
        if cell <= v1:
            return p0 + (p1 - p0) * (cell - v0) // (v1 - v0)
    return 100


class Estimate:
    def __init__(self):
        self.window = None
        self.median_mv = None
        self.filtered = None
        self.displayed = None
        self.down = 0
        self.down_candidate = None
        self.up = 0
        self.next_publish = 0

    def sample(self, voltage, now):
        if not 9300 <= voltage <= 12800:
            raise RuntimeError('voltage outside the configured 3S range: %d mV' % voltage)
        if self.window is None:
            # Seed the startup window with the initial reading. The separate
            # source warmup still checks real input variation before activation.
            self.window = collections.deque([voltage] * MEDIAN_SAMPLES, maxlen=MEDIAN_SAMPLES)
        self.window.append(voltage)
        ordered = sorted(self.window)
        middle = MEDIAN_SAMPLES // 2
        self.median_mv = (ordered[middle - 1] + ordered[middle]) / 2
        self.filtered = self.median_mv if self.filtered is None else self.filtered + (self.median_mv - self.filtered) / 8
        if now >= self.next_publish:
            self.next_publish = now + 1
            candidate = percent_from_mv(int(round(self.filtered)))
            if self.displayed is None:
                self.displayed = candidate
            elif candidate < self.displayed:
                self.up = 0
                self.down = self.down + 1 if candidate == self.down_candidate else 1
                self.down_candidate = candidate
                if self.down >= 3:
                    self.displayed = candidate
                    self.down = 0
            elif candidate > self.displayed:
                self.down = 0
                self.up += 1
                if self.up >= 60:
                    self.displayed += 1
                    self.up = 0
            else:
                self.down = self.up = 0
        return self.displayed


def identity(pid):
    with open('/proc/%d/stat' % pid) as stream:
        data = stream.read()
    return data[data.rfind(')') + 1:].split()[19]


def find_process(path=EXE):
    matches = []
    for entry in os.listdir('/proc'):
        if entry.isdigit():
            try:
                if os.readlink('/proc/%s/exe' % entry) == path:
                    matches.append(int(entry))
            except OSError:
                pass
    if len(matches) != 1:
        raise RuntimeError('expected exactly one process for ' + path)
    return matches[0]


def validate_image(blob):
    if hashlib.sha256(blob).hexdigest() != SHA256:
        raise RuntimeError('unsupported HDVT executable hash')
    if blob[:6] != b'\x7fELF\x01\x01':
        raise RuntimeError('expected ELF32 little endian')
    offset = struct.unpack_from('<I', blob, 28)[0]
    size, count = struct.unpack_from('<HH', blob, 42)
    segments = [struct.unpack_from('<8I', blob, offset + i * size) for i in range(count)]
    if not any(s[:3] == (1, 0, 0) and s[4:7] == (0xAD9F8, 0xAD9F8, 5) for s in segments):
        raise RuntimeError('unexpected first load segment')
    if not 0xAD9F8 <= STORAGE < STORAGE + STORAGE_SIZE <= 0xAE000:
        raise RuntimeError('shadow storage is outside verified page padding')
    if blob[STORAGE:STORAGE + STORAGE_SIZE] != bytes(STORAGE_SIZE):
        raise RuntimeError('file padding is not empty')
    for address in READ_LITERALS + (RECEIVE_LITERAL,):
        if blob[address:address + 4] != OLD_LITERAL:
            raise RuntimeError('unexpected cache reference')


def base_from_maps(maps):
    regions = []
    for line in maps.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        start, end = [int(s, 16) for s in parts[0].split('-')]
        regions.append((start, end, parts[1], int(parts[2], 16), parts[5] if len(parts) > 5 else ''))
    bases = [start for start, end, perms, offset, path in regions
             if path == EXE and offset == 0 and perms == 'r-xp']
    if len(bases) != 1:
        raise RuntimeError('unexpected HDVT executable mapping')
    base = bases[0]
    for rva, size in [(rva, 4) for rva in READ_LITERALS + (RECEIVE_LITERAL,)] + [(STORAGE, STORAGE_SIZE)]:
        if not any(start <= base + rva and base + rva + size <= end and
                   perms == 'r-xp' and path == EXE for start, end, perms, offset, path in regions):
            raise RuntimeError('expected a private executable mapping')
    if not any(start <= base + CACHE and base + CACHE + 10 <= end and perms == 'rw-p'
               for start, end, perms, offset, path in regions):
        raise RuntimeError('battery cache is not in readable/writable memory')
    return base


class Memory:
    def __init__(self, fd, base):
        self.fd, self.base = fd, base

    def read(self, rva, size):
        data = os.pread(self.fd, size, self.base + rva)
        if len(data) != size:
            raise RuntimeError('short process-memory read')
        return data

    def write(self, rva, data):
        if os.pwrite(self.fd, data, self.base + rva) != len(data):
            raise RuntimeError('short process-memory write')
        if self.read(rva, len(data)) != data:
            raise RuntimeError('process-memory write verification failed')

    def validate(self):
        for address in READ_LITERALS + (RECEIVE_LITERAL,):
            if self.read(address, 4) != OLD_LITERAL:
                raise RuntimeError('RAM cache references already modified')
        if self.read(GOT_SLOT, 4) != struct.pack('<I', self.base + CACHE):
            raise RuntimeError('unexpected live cache pointer')
        data = self.read(STORAGE, STORAGE_SIZE)
        retained = (data[:4] == struct.pack('<I', self.base + CACHE) and
                    data[14:24] == bytes(10) and data[24:] == MAGIC)
        if data != bytes(STORAGE_SIZE) and not retained:
            raise RuntimeError('RAM padding is not empty or owned by this estimator')

    def install(self, record, percent):
        shadow = record[:8] + bytes([percent]) + record[9:]
        # Initialize the data and pointer before redirecting either reader.
        block = struct.pack('<I', self.base + STORAGE + 4) + shadow + bytes(10) + MAGIC
        self.write(STORAGE, block)
        for address in READ_LITERALS:
            self.write(address, NEW_LITERAL)

    def update(self, record):
        if len(record) != 10 or record[8] > 100:
            raise RuntimeError('invalid shadow update')
        if any(self.read(r, 4) != NEW_LITERAL for r in READ_LITERALS):
            raise RuntimeError('reader redirection no longer active')
        self.write(STORAGE + 4, record[:8])
        self.write(STORAGE + 12, record[8:9])
        self.write(STORAGE + 13, record[9:])

    def restore(self):
        # Redirect the shadow slot first. A reader already holding its offset
        # can still safely dereference it while the literals are restored.
        block = self.read(STORAGE, STORAGE_SIZE)
        if block[24:] == MAGIC:
            self.write(STORAGE, struct.pack('<I', self.base + CACHE))
        for address in READ_LITERALS:
            current = self.read(address, 4)
            if current == NEW_LITERAL:
                self.write(address, OLD_LITERAL)
            elif current != OLD_LITERAL:
                raise RuntimeError('reader changed by another actor; refusing to overwrite')
        if self.read(RECEIVE_LITERAL, 4) != OLD_LITERAL:
            raise RuntimeError('incoming battery reference changed unexpectedly')
        # Keep the harmless shadow data mapped until process exit, so any
        # reader interrupted before restoration never dereferences a null slot.


def presence_frame(sequence):
    """The tested local common 00/F1 report: source 0300, system 0801."""
    def crc(data, initial, polynomial):
        result = initial
        for value in data:
            result ^= value
            for _ in range(8):
                result = (result >> 1) ^ (polynomial if result & 1 else 0)
        return result
    frame = bytearray([0x55, 16, 4, 0, 3, 0x28, sequence & 255,
                       (sequence >> 8) & 255, 0, 0, 0xf1, 1, 0xff, 0x0a])
    frame[3] = crc(frame[:3], 0x77, 0x8c)
    frame.extend(struct.pack('<H', crc(frame, 0x3692, 0x8408)))
    return bytes(frame)


class BatteryPresence:
    """Guarded native presence reports; never writes system-service memory.

    The native handler also refreshes chassis presence. Require continuing
    variation of the original voltage cache, independently from the smoothed
    display value. Never erase an existing battery-specific diagnostic list.
    """
    def __init__(self):
        self.fd = self.sock = None
        try:
            self.pid = find_process(SYSTEM_EXE)
            self.started = identity(self.pid)
            with open('/proc/%d/exe' % self.pid, 'rb') as stream:
                if hashlib.sha256(stream.read()).hexdigest() != SYSTEM_SHA256:
                    raise RuntimeError('unsupported system executable hash')
            with open('/proc/%d/maps' % self.pid) as stream:
                lines = [line.split() for line in stream if line.strip()]
            bases = [int(p[0].split('-')[0], 16) for p in lines
                     if len(p) >= 6 and p[5] == SYSTEM_EXE and
                     int(p[2], 16) == 0 and p[1] == 'r-xp']
            if len(bases) != 1:
                raise RuntimeError('unexpected system executable mapping')
            self.regions = [(int(p[0].split('-')[0], 16), int(p[0].split('-')[1], 16))
                            for p in lines if p[1].startswith('rw')]
            self.fd = os.open('/proc/%d/mem' % self.pid, os.O_RDONLY)
            self.instance_slot = bases[0] + 0x6464C
            self.instance = struct.unpack('<I', self.read(self.instance_slot, 4))[0]
            if self.instance % 4:
                raise RuntimeError('unaligned module-state object')
            self.validate(initial=True)
            import socket
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            self.sock.bind('\0/s1/battery/watchdog/%d' % os.getpid())
            self.sock.settimeout(0.25)
            self.sequence = 0x7A00
            self.next_send = 0
            self.last_voltage = None
            self.last_change = time.monotonic()
            self.sent = 0
        except BaseException:
            self.close()
            raise

    def read(self, address, size):
        if not any(start <= address and address + size <= end for start, end in self.regions):
            raise RuntimeError('module-state pointer outside writable mappings')
        data = os.pread(self.fd, size, address)
        if len(data) != size:
            raise RuntimeError('short module-state read')
        return data

    def validate(self, initial=False):
        if identity(self.pid) != self.started:
            raise RuntimeError('system service restarted')
        if struct.unpack('<I', self.read(self.instance_slot, 4))[0] != self.instance:
            raise RuntimeError('module-state object changed')
        if self.read(self.instance + 0x4C, 1) != b'\x01':
            raise RuntimeError('chassis is not present')
        if initial and self.read(self.instance + 0x64, 1) != b'\x00':
            raise RuntimeError('battery already present; wait for expiry or inspect native battery')
        head = self.instance + 0x74
        if self.read(head, 8) != struct.pack('<II', head, head):
            raise RuntimeError('battery diagnostics present; refusing to clear them')

    def update(self, native_record, now):
        if len(native_record) != 10:
            raise RuntimeError('invalid native source size for battery presence')
        voltage = struct.unpack('<H', native_record[:2])[0]
        if native_record[2:9] != bytes(7) or not 9300 <= voltage <= 12800:
            raise RuntimeError('invalid native source for battery presence')
        if voltage != self.last_voltage:
            self.last_voltage, self.last_change = voltage, now
        if now - self.last_change > 1:
            raise RuntimeError('original voltage unchanged for one second; stop battery presence')
        if now >= self.next_send:
            self.validate()
            self.sock.sendto(presence_frame(self.sequence), '\0/duss/mb/0x900')
            self.sequence = (self.sequence + 1) & 65535
            self.next_send = now + 1
            self.sent += 1
            if self.sent == 1:
                emit('presence_started', system_pid=self.pid, native_command='00/F1')

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def watchdog(memory, pipe_read, ready_write, pid, started, record, percent,
             battery_presence=False, battery_warnings=False):
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.SIG_IGN)
    status = 0
    reason = 'parent_closed_pipe'
    presence = None
    warnings = None
    try:
        # The watchdog is the only writer. A stalled parent cannot reinstall
        # a redirection after the watchdog has restored it and exited.
        if battery_presence:
            presence = BatteryPresence()
        if battery_warnings:
            from warning_filter import WarningFilter
            warnings = WarningFilter()
            warnings.install()
            emit('warnings_active', suppressed=['0300C205', '0300C209'],
                 electrical_alarms_preserved=True, native_lease_seconds=3)
        memory.install(record, percent)
        os.write(ready_write, b'R')
        os.close(ready_write)
        buffer = b''
        while True:
            readable, _, _ = select.select([pipe_read], [], [], 2)
            if not readable:
                reason = 'heartbeat_timeout'
                break
            data = os.read(pipe_read, 4096)
            if not data:
                break
            buffer += data
            stop = False
            while buffer:
                if buffer[:1] == b'Q':
                    reason = 'normal_stop'
                    stop = True
                    break
                if buffer[:1] != b'U':
                    raise RuntimeError('invalid estimator pipe message')
                if len(buffer) < 11:
                    break
                if identity(pid) != started:
                    raise RuntimeError('HDVT identity changed')
                memory.update(buffer[1:11])
                buffer = buffer[11:]
            if stop:
                break
            if presence is not None:
                # Read the incoming cache directly, not an old queued parent
                # message or the filtered shadow value, before any status pulse.
                presence.update(memory.read(CACHE, 10), time.monotonic())
            if warnings is not None:
                warnings.update()
    except BaseException as exc:
        reason = 'watchdog_error'
        emit('watchdog_error', error=str(exc))
        status = 1
    finally:
        if presence is not None:
            try:
                presence.close()
                emit_cleanup('presence_stopped', reports_sent=presence.sent)
            except BaseException as exc:
                emit_cleanup('presence_close_error', error=str(exc))
                status = 1
        if warnings is not None:
            try:
                warnings.restore()
                warnings.verify_restored()
                emit_cleanup('warnings_restored', system_pid=warnings.pid)
            except BaseException as exc:
                emit_cleanup('warnings_restore_error', error=str(exc))
                status = 1
            finally:
                try:
                    warnings.close()
                except BaseException as exc:
                    emit_cleanup('warnings_close_error', error=str(exc))
                    status = 1
        try:
            if identity(pid) == started:
                memory.restore()
                emit_cleanup('restored', reason=reason, hdvt_pid=pid)
            else:
                emit_cleanup('process_changed', hdvt_pid=pid)
        except FileNotFoundError:
            emit_cleanup('process_exited', hdvt_pid=pid)
        except BaseException as exc:
            emit_cleanup('restore_error', error=str(exc))
            status = 1
        os._exit(status)


def run(args):
    battery_presence = getattr(args, 'battery_presence', False)
    battery_warnings = getattr(args, 'battery_warnings', False)
    emit('plan', execute=args.execute, duration_seconds=args.duration,
         firmware_writes=False, controller_parameter_writes=False, motion_commands=False,
         ram_data_literal_changes=[hex(r) for r in READ_LITERALS],
         shadow_storage=hex(STORAGE), ui_estimate_only=True,
         battery_presence=battery_presence, battery_warnings=battery_warnings,
         median_window_seconds=30)
    if not args.execute:
        return
    import fcntl
    if os.geteuid() != 0:
        raise RuntimeError('root required')
    lock_fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fd = None
    child = None
    heartbeat = None
    disk_before = None
    voltage = None
    try:
        with open(EXE, 'rb') as stream:
            disk_before = hashlib.sha256(stream.read()).hexdigest()
        pid = find_process()
        started = identity(pid)
        with open('/proc/%d/exe' % pid, 'rb') as stream:
            validate_image(stream.read())
        with open('/proc/%d/maps' % pid) as stream:
            base = base_from_maps(stream.read())
        fd = os.open('/proc/%d/mem' % pid, os.O_RDWR)
        memory = Memory(fd, base)
        memory.validate()
        estimate = Estimate()
        distinct = set()
        warmup_voltages = []
        # Confirm a varying, plausible XT30-only source before any RAM write.
        for _ in range(8):
            record = memory.read(CACHE, 10)
            voltage = struct.unpack('<H', record[:2])[0]
            if record[2:9] != bytes(7):
                raise RuntimeError('native battery data is present; refusing override')
            estimate.sample(voltage, time.monotonic())
            distinct.add(voltage)
            warmup_voltages.append(voltage)
            time.sleep(0.25)
        if len(distinct) < 2 or identity(pid) != started:
            raise RuntimeError('source freshness or process identity not confirmed')
        # Seed the long display window from all eight real startup readings,
        # so one noisy first sample cannot set the estimate for thirty seconds.
        ordered = sorted(warmup_voltages)
        estimate = Estimate()
        estimate.sample((ordered[3] + ordered[4]) // 2, time.monotonic())
        read_end, heartbeat = os.pipe()
        # A stalled watchdog must not block this process on a full heartbeat pipe.
        os.set_blocking(heartbeat, False)
        ready_read, ready_write = os.pipe()
        child = os.fork()
        if child == 0:
            os.close(heartbeat)
            os.close(ready_read)
            watchdog(memory, read_end, ready_write, pid, started, record, estimate.displayed,
                     battery_presence, battery_warnings)
        os.close(read_end)
        os.close(ready_write)
        try:
            if not select.select([ready_read], [], [], 2)[0] or os.read(ready_read, 1) != b'R':
                raise RuntimeError('restore watchdog failed to start')
        finally:
            os.close(ready_read)
        emit('active', hdvt_pid=pid, worker_pid=os.getpid(), watchdog_pid=child,
             worker_started=identity(os.getpid()), percent=estimate.displayed, voltage_mv=voltage,
             battery_presence=battery_presence)
        deadline = time.monotonic() + args.duration
        last_change = last_log = time.monotonic()
        last_voltage = voltage
        while time.monotonic() < deadline:
            now = time.monotonic()
            if identity(pid) != started:
                raise RuntimeError('HDVT restarted')
            record = memory.read(CACHE, 10)
            voltage = struct.unpack('<H', record[:2])[0]
            if record[2:9] != bytes(7):
                raise RuntimeError('native battery data returned; stopping override')
            if voltage != last_voltage:
                last_voltage, last_change = voltage, now
            if now - last_change > 10:
                raise RuntimeError('voltage cache unchanged for ten seconds')
            percentage = estimate.sample(voltage, now)
            os.write(heartbeat, b'U' + record[:8] + bytes([percentage]) + record[9:])
            if now - last_log >= 5:
                emit('estimate', voltage_mv=voltage, median_mv=round(estimate.median_mv),
                     filtered_mv=round(estimate.filtered), percent=percentage)
                last_log = now
            time.sleep(0.25)
    except BaseException as exc:
        emit('worker_error', error=str(exc), voltage_mv=voltage)
        raise
    finally:
        cleanup_failed = False
        if heartbeat is not None:
            try:
                os.write(heartbeat, b'Q')
            except OSError:
                pass
            os.close(heartbeat)
        if child:
            try:
                status = guard.wait_child(child, 5)
                if status:
                    emit('watchdog_failed', status=status)
                    cleanup_failed = True
            except RuntimeError as exc:
                # Keep the independent restorer alive. Its inherited lock keeps
                # uninstall from deleting files before recovery really finishes.
                emit('watchdog_wait_failed', error=str(exc))
                cleanup_failed = True
        if fd is not None:
            os.close(fd)
        os.close(lock_fd)
        if disk_before is not None:
            with open(EXE, 'rb') as stream:
                unchanged = hashlib.sha256(stream.read()).hexdigest() == disk_before
            emit('disk_check', executable_unchanged=unchanged)
            if not unchanged:
                raise RuntimeError('executable hash changed')
        if cleanup_failed:
            raise RuntimeError('watchdog reported a failure; inspect restoration log')


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise RuntimeError('interrupted by signal %d' % signum)
    for name in ('SIGTERM', 'SIGHUP'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--battery-presence', action='store_true',
                        help='Announce the software battery using the guarded native status path')
    parser.add_argument('--battery-warnings', action='store_true',
                        help='Suppress only app warnings C205/C209 while the estimate is active')
    parser.add_argument('--duration', type=float, default=15)
    args = parser.parse_args()
    if not 1 <= args.duration <= 86400:
        parser.error('duration must be between 1 second and 24 hours')
    run(args)
