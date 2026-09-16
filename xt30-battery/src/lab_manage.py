"""Complete installation lifecycle invoked by the self-contained Lab script.

Python 3.6 compatible. Runs outside the Lab interpreter using its embedded
bundle. Never starts ADB or restarts robot services.
"""
import argparse
from contextlib import contextmanager, redirect_stdout
import io
import json
import os
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True
import manage
import controller_settings

PYTHON = '/data/python_files/bin/python'
BOOT_LOG = '/tmp/s1-battery-autostart.log'
WORKER_LOG = '/tmp/s1-battery-estimator.log'
CONTROL_LOCK = '/tmp/s1-battery-install.lock'
WORKER_LOCK = '/tmp/s1-battery-estimator.lock'


def quiet_call(callback, *args, **kwargs):
    # Developer helpers keep their detailed CLI output. Lab reports completed
    # steps below; exceptions still propagate and prevent a success message.
    with redirect_stdout(io.StringIO()):
        return callback(*args, **kwargs)


@contextmanager
def control_lock():
    import fcntl
    fd = os.open(CONTROL_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def worker_locked():
    import fcntl
    fd = os.open(WORKER_LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
    finally:
        os.close(fd)


def installation():
    if not os.path.lexists(manage.ROOT) and not os.path.lexists(manage.HOOK):
        return None
    return manage.installed_manifest()


def events():
    try:
        rows = manage.read(WORKER_LOG).decode('utf-8').splitlines()
    except FileNotFoundError:
        return []
    result = []
    for row in rows:
        try:
            record = json.loads(row)
            if isinstance(record, dict):
                result.append(record)
        except ValueError:
            pass
    return result


def manual_worker():
    """Recognize an older temporary launcher by log identity AND command line."""
    active = [row for row in events() if row.get('event') == 'active']
    if not active:
        return None
    record = active[-1]
    pid = record.get('worker_pid')
    if not isinstance(pid, int) or pid <= 1:
        return None
    try:
        with open('/proc/%d/stat' % pid) as stream:
            fields = stream.read().rsplit(')', 1)[1].split()
        if fields[19] != record.get('worker_started') or fields[0] == 'Z':
            return None
        with open('/proc/%d/cmdline' % pid, 'rb') as stream:
            command = stream.read().rstrip(b'\0').split(b'\0')
    except FileNotFoundError:
        return None
    if len(command) < 4 or command[:2] != [PYTHON.encode(), b'-S']:
        return None
    path = command[2]
    if (not path.startswith(b'/tmp/s1-battery-worker-') or not path.endswith(b'.py')
            or b'/' in path[len(b'/tmp/'):]
            or command[3:4] != [b'--execute']):
        return None
    return record


def stop_manual_worker():
    record = manual_worker()
    if record:
        os.kill(record['worker_pid'], signal.SIGTERM)
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline and worker_locked():
            time.sleep(0.1)
        if worker_locked():
            raise RuntimeError('temporary estimator has not restored; retry after checking STATUS')


def show_status():
    manifest = installation()
    if manifest is None:
        print('XT30 mod: Not installed | Auth/capacity checks: not read')
        if worker_locked():
            print('A temporary estimator is still running; use DISABLE or UNINSTALL to stop it.')
        return
    claim = manage.process_claim()
    # Installation and worker state do not prove the current controller flags.
    # Reading them here would pause HDVT; STATUS remains non-invasive.
    print('XT30 mod: installed | Auto-start: %s | Auth/capacity checks: not read' % (
        'on' if os.path.isfile(manage.ROOT + '/enabled') else 'off'))
    rows = events()
    active = [row for row in rows if row.get('event') == 'active']
    if claim and active and active[-1].get('worker_pid') == claim['pid'] and \
            active[-1].get('worker_started') == claim['started']:
        samples = [row for row in rows if row.get('event') in ('active', 'estimate')]
        latest = samples[-1]
        print('Estimate: %s%% | %.3f V | Running' % (
            latest['percent'], latest['voltage_mv'] / 1000.0))
    elif claim:
        print('Estimate: starting in background')
    else:
        print('Estimator: stopped | Run INSTALL to start it and enable auto-start.')
        if rows:
            last = rows[-1]
            detail = last.get('error') or last.get('reason') or last.get('status')
            print('Last event: %s%s' % (last.get('event', 'unknown'),
                                       ' | %s' % detail if detail is not None else ''))
    if 'warning_filter.py' in manifest['files']:
        import importlib.util
        spec = importlib.util.spec_from_file_location('s1_warning_status', manage.ROOT + '/warning_filter.py')
        warning_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(warning_module)
        try:
            probe = warning_module.WarningFilter(readonly=True)
            try:
                state = probe.status()
                print('Battery authentication errors / missing battery information: %s' % (
                    'filtered' if state['filter_active'] else 'unfiltered'))
            finally:
                probe.close()
        except (OSError, RuntimeError) as exc:
            print('Warning filter: not verified | ' + str(exc))
    else:
        print('This older installation has no battery warning filter. UNINSTALL then INSTALL this script to update.')


def start_installed():
    if manage.process_claim():
        return 'already running or starting'
    if worker_locked():
        raise RuntimeError('another estimator is active; run DISABLE before INSTALL')
    quiet_call(manage.verify_native_references)
    if os.path.lexists(manage.CLAIM):
        # Only an explicit INSTALL authorizes another attempt after STOP/fault.
        manage.read(manage.CLAIM)
        if manage.process_claim():
            return 'already running or starting'
        os.unlink(manage.CLAIM)
    with open(BOOT_LOG, 'ab', buffering=0) as log:
        subprocess.Popen([PYTHON, '-S', manage.ROOT + '/boot.py', '--run'],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         close_fds=True, start_new_session=True)
    return 'startup requested'


def perform(mode):
    if mode not in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
        raise RuntimeError('MODE must be INSTALL, STATUS, DISABLE, or UNINSTALL')
    if os.geteuid() != 0:
        raise RuntimeError('root Lab execution is required on the supported robot')
    if mode == 'STATUS':
        show_status()
        return
    manifest = installation()
    if mode == 'INSTALL':
        manage.verify_stock()
        if manifest is not None:
            expected = {name: manage.digest(data) for name, data in manage.source_files().items()}
            if manifest['files'] != expected:
                raise RuntimeError('a different version is installed; run UNINSTALL before INSTALL')
        else:
            quiet_call(manage.main, 'install', True)
        stop_manual_worker()
        quiet_call(manage.main, 'disable', True)
        time.sleep(7)
        quiet_call(controller_settings.set_mode, 'XT30')
        print('Battery checks: authentication OFF | capacity OFF (verified)', flush=True)
        quiet_call(manage.main, 'enable', True)
        startup = start_installed()
        print('INSTALL complete | Auto-start: ON | Background estimate/filter: ' + startup)
        return
    if manifest is not None and mode == 'UNINSTALL':
        quiet_call(manage.main, 'uninstall', False)  # Preflight unknown files before changes.
    stop_manual_worker()
    if manifest is None:
        # Also verify a legacy temporary run when no persistent install exists.
        previous_root = manage.ROOT
        try:
            manage.ROOT = os.path.dirname(os.path.abspath(__file__))
            quiet_call(manage.verify_native_references, recover_warnings=True)
        finally:
            manage.ROOT = previous_root
    else:
        quiet_call(manage.main, 'disable', True)
    time.sleep(7)  # Native presence timeout plus outgoing roster cadence.
    if mode == 'UNINSTALL':
        manage.verify_stock()
        quiet_call(controller_settings.set_mode, 'STOCK')
        print('Battery checks: authentication ON | capacity ON (verified)', flush=True)
        if manifest is not None:
            quiet_call(manage.main, 'uninstall', True)
    if mode == 'DISABLE':
        print('DISABLE complete | Estimate/filter: stopped | Auto-start: OFF')
        print('Battery checks: unchanged (UNINSTALL restores stock checks)')
    else:
        print('UNINSTALL complete | Estimate/filter removed | Stock battery required')
        print('Next: restart once to clear temporary telemetry settings and logs.')


def main(mode):
    with control_lock():
        perform(mode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'))
    args = parser.parse_args()
    main(args.mode)
