"""Optional data-only boot hook for the tested S1; compatible with Python 3.6."""
import os
import sys

ROOT = '/data/s1-battery-estimator'
PYTHON = '/data/python_files/bin/python'
SCRATCH = '/data/dji_scratch/bin/dji_scratch.py'
CLAIM = '/tmp/s1-battery-boot.claim'
BOOT_LOG = '/tmp/s1-battery-autostart.log'
WORKER_LOG = '/tmp/s1-battery-estimator.log'


def matches_service(command, parent, uid):
    return (uid == 0 and parent == 1 and
            command == [PYTHON.encode('ascii'), SCRATCH.encode('ascii')])


def enabled():
    return os.path.isfile(ROOT + '/enabled')


def launch_from_site():
    # Do not depend on sys.argv being initialized during Python site startup.
    try:
        with open('/proc/self/cmdline', 'rb') as stream:
            command = stream.read().rstrip(b'\0').split(b'\0')
        if not matches_service(command, os.getppid(), os.geteuid()) or not enabled():
            return
        import subprocess
        with open(BOOT_LOG, 'ab', buffering=0) as log:
            subprocess.Popen([PYTHON, '-S', ROOT + '/boot.py', '--run'],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                             close_fds=True, start_new_session=True)
    except Exception:
        # An optional estimator must never prevent the stock Lab service boot.
        pass


def verify_installation():
    import hashlib
    import json
    with open(ROOT + '/manifest.json') as stream:
        manifest = json.load(stream)
    if manifest.get('schema') != 's1-battery-autostart/v1':
        raise RuntimeError('unknown installation manifest')
    expected = {ROOT + '/' + name: manifest['files'][name]
                for name in ('boot.py', 'worker.py', 'telemetry.py')}
    warning_names = ('warning_filter.py', 'warning_hook_blob.py')
    if any(name in manifest['files'] for name in warning_names):
        expected.update({ROOT + '/' + name: manifest['files'][name] for name in warning_names})
    if 'process_guard.py' in manifest['files']:
        expected[ROOT + '/process_guard.py'] = manifest['files']['process_guard.py']
    expected.update(manifest['stock_files'])
    for path, digest in expected.items():
        if os.path.islink(path):
            raise RuntimeError('unexpected symlink: ' + path)
        with open(path, 'rb') as stream:
            if hashlib.sha256(stream.read()).hexdigest() != digest:
                raise RuntimeError('file hash changed: ' + path)


def process_identity(pid):
    with open('/proc/%d/stat' % pid) as stream:
        fields = stream.read().rsplit(')', 1)[1].split()
    return fields[19]


class SourceReadiness:
    """Require a continuous live window, not two transient startup readings."""
    def __init__(self):
        self.source = None
        self.voltage = None
        self.since = self.changed = None

    def update(self, pid, started, voltage, now):
        source = (pid, started)
        if self.source != source:
            self.source, self.voltage = source, voltage
            self.since = self.changed = now
            return False
        if now - self.changed > 1:
            self.since = now
        if voltage != self.voltage:
            self.voltage, self.changed = voltage, now
        return now - self.changed <= 1 and now - self.since >= 10


def prime_voltage(telemetry, clock):
    """Briefly request battery data, then release the Lab route completely.

    On the tested HDVT, ADD_MSG promotes the upstream topic's frequency;
    deleting our downstream message does not lower that native topic setting.
    The subsequent readiness window independently verifies continuing input.
    """
    import struct
    client = telemetry.Client()  # Refuse an occupied Lab socket; never replace it.
    readings = set()
    count = 0
    try:
        client.subscribe()
        deadline = clock.monotonic() + 5
        while clock.monotonic() < deadline:
            try:
                msg = client.receive()
            except telemetry.socket.timeout:
                continue
            payload = msg['payload']
            if (msg['flags'] & 0x80 or msg['sender'] != 9 or
                    (msg['set'], msg['command']) != (0x48, 8) or
                    payload[1:2] != bytes([telemetry.MESSAGE])):
                continue
            if len(payload) != 12 or payload[4:11] != bytes(7):
                raise RuntimeError('unexpected native battery data during startup')
            voltage = struct.unpack('<H', payload[2:4])[0]
            if not 9300 <= voltage <= 12800:
                raise RuntimeError('invalid startup battery voltage: %d mV' % voltage)
            readings.add(voltage)
            count += 1
            if len(readings) >= 2 and count >= 3:
                break
        else:
            raise RuntimeError('no varying battery data during startup subscription')
    finally:
        client.close()
    print('Battery source primed at 10 Hz; temporary subscription and Lab socket released.', flush=True)


def run(duration=86400, startup_delay=3, ready_timeout=300):
    import json
    import time
    if os.geteuid() != 0 or not enabled():
        return
    verify_installation()
    # A service restart must not silently re-enable an estimator stopped by
    # its operator or watchdog. /tmp is a verified tmpfs, fresh on each boot.
    try:
        fd = os.open(CLAIM, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('Autostart already attempted during this boot.', flush=True)
        return
    with os.fdopen(fd, 'w') as stream:
        json.dump({'pid': os.getpid(), 'started': process_identity(os.getpid())}, stream)
    print('Waiting for ten continuous seconds of live voltage (up to %s seconds).' % ready_timeout, flush=True)
    time.sleep(startup_delay)
    if not enabled():
        return
    # Imported only by the detached process, never by the stock Lab service.
    sys.dont_write_bytecode = True
    import worker
    import telemetry
    import struct
    deadline = time.monotonic() + ready_timeout
    readiness = SourceReadiness()
    primed = False
    while enabled() and time.monotonic() < deadline:
        try:
            pid = worker.find_process()
            started = worker.identity(pid)
            with open('/proc/%d/exe' % pid, 'rb') as stream:
                worker.validate_image(stream.read())
            with open('/proc/%d/maps' % pid) as stream:
                base = worker.base_from_maps(stream.read())
            memory_fd = os.open('/proc/%d/mem' % pid, os.O_RDONLY)
            try:
                memory = worker.Memory(memory_fd, base)
                memory.validate()
                record = memory.read(worker.CACHE, 10)
            finally:
                os.close(memory_fd)
            voltage = struct.unpack('<H', record[:2])[0]
            if record[2:9] != bytes(7):
                raise RuntimeError('native battery data is present')
            if not 9300 <= voltage <= 12800:
                raise RuntimeError('voltage outside configured 3S range')
            if worker.identity(pid) != started:
                raise RuntimeError('HDVT restarted during readiness check')
            if not primed:
                prime_voltage(telemetry, time)
                primed = True
                readiness = SourceReadiness()
                continue
            if readiness.update(pid, started, voltage, time.monotonic()):
                if not enabled():
                    return
                verify_installation()
                # Share the manual launcher's lock to avoid truncating an
                # active manual session's log. Keep it across exec/watchdog.
                import fcntl
                launch_fd = os.open('/tmp/s1-battery-estimator-launch.lock', os.O_CREAT | os.O_RDWR, 0o600)
                try:
                    fcntl.flock(launch_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    os.close(launch_fd)
                    raise RuntimeError('another launcher is active')
                try:
                    os.set_inheritable(launch_fd, True)
                    print('Starting the guarded estimator once for this boot.', flush=True)
                    log_fd = os.open(WORKER_LOG, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
                    try:
                        os.dup2(log_fd, 1)
                        os.dup2(log_fd, 2)
                    finally:
                        os.close(log_fd)
                    os.execv(PYTHON, [PYTHON, '-S', ROOT + '/worker.py',
                                     '--execute', '--battery-presence', '--battery-warnings',
                                     '--duration', str(duration)])
                finally:
                    # Reached only on exec failure; successful exec replaces us.
                    os.close(launch_fd)
        except (OSError, RuntimeError) as exc:
            readiness = SourceReadiness()
            print('Not ready: ' + str(exc), flush=True)
        time.sleep(0.25)
    print('Autostart ended without activating the estimator.', flush=True)


if __name__ == 's1_battery_boot_hook':
    launch_from_site()
elif __name__ == '__main__':
    import signal
    def interrupted(signum, frame):
        raise SystemExit('startup cancelled')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--duration', type=int, default=86400)
    parser.add_argument('--startup-delay', type=float, default=3)
    parser.add_argument('--ready-timeout', type=float, default=300)
    args = parser.parse_args()
    if not 1 <= args.duration <= 86400 or not 0 <= args.startup_delay <= 60 or not 1 <= args.ready_timeout <= 600:
        parser.error('invalid bounded duration or startup timeout')
    if args.run:
        run(args.duration, args.startup_delay, args.ready_timeout)
