# RoboMaster S1 XT30 Battery Mod - complete installation and reversal from Lab
# Paste this entire generated file into one Lab Python program.
# INSTALL sets guarded XT30 parameters and installs the automatic estimate.
# It also hides missing battery information and battery authentication errors in the app.
# Electrical warnings remain enabled; DISABLE/UNINSTALL restore native reporting.
# Warning filter: offline-tested; real-robot acceptance is still pending.
# Updating an older installation: use this same file with UNINSTALL, then INSTALL.
# STATUS shows installation/runtime state. DISABLE stops it and future startup.
# UNINSTALL restores stock battery checks and removes the installed estimate.
# No ADB, PC-side commands, downloads, or firmware flash are required.
# Supported firmware only. Approximate 3S, 4.2 V/cell voltage estimate.
# An external lithium battery MUST have an independent, correctly rated BMS.
# Use a fuse and physical disconnect. The estimate provides no cell protection
# or automatic low-battery stop. Raise all wheels before running INSTALL/UNINSTALL.

MODE = 'INSTALL'  # INSTALL, STATUS, DISABLE, UNINSTALL

import rm_define


def load_module(name):
    loader = rm_define.__dict__['__builtins__']['__import__']
    return loader(name, globals(), locals(), [], 0)


BUNDLE_B64 = '__BUNDLE_B64__'
BUNDLE_SHA256 = '__BUNDLE_SHA256__'


def print_output(output):
    # Lab renders each print as one console entry, flattening embedded newlines.
    for line in output.decode('utf-8', 'replace').splitlines():
        if line.strip():
            print(line)


def robot_reset():
    # ready() has already run in DJI's framework before this source is inserted.
    # Preserve its exit mode/resume, but omit the automatic recenter task: this
    # maintenance program requests no gimbal position. The framework still runs
    # all stop(), controller exit() and event.stop() cleanup unchanged.
    robot_ctrl.set_mode(rm_define.robot_mode_free)
    gimbal_ctrl.resume()


def stop_job(job, process_api):
    if job.poll() is not None:
        return True
    try:
        job.terminate()
    except Exception:
        if job.poll() is None:
            raise
    try:
        job.wait(timeout=30)  # Allow rollback and temporary-route cleanup.
    except process_api.TimeoutExpired:
        try:
            job.kill()
        except Exception:
            if job.poll() is None:
                raise
        try:
            job.wait(timeout=2)
        except process_api.TimeoutExpired:
            return False
    return True


def read_progress(os_api, log, offset, pending):
    data = os_api.pread(log.fileno(), 65536, offset)
    # DJI's project parser expands escape sequences before compiling user code.
    line_break = b''.fromhex('0a')
    parts = (pending + data).split(line_break)
    print_output(line_break.join(parts[:-1]))
    return offset + len(data), parts[-1]


def remove_temporary_files(os_api, written):
    # No loop: Lab injects stop checkpoints into loops, including cleanup loops.
    # Ten known files keep this recursion shallow even after the Lab Stop button.
    if written:
        os_api.unlink(written.pop())
        remove_temporary_files(os_api, written)


def main():
    if MODE not in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
        raise Exception('MODE must be INSTALL, STATUS, DISABLE, or UNINSTALL.')
    os_api = load_module('os')
    process_api = load_module('sub' + 'process')
    tempfile_api = load_module('tempfile')
    hash_api = load_module('hashlib')
    base64_api = load_module('base64')
    json_api = load_module('json')
    clock_api = load_module('time')
    packed = base64_api.b64decode(BUNDLE_B64)
    if hash_api.sha256(packed).hexdigest() != BUNDLE_SHA256:
        raise Exception('Embedded bundle checksum failed; copy the complete script again.')
    files = json_api.loads(packed.decode('utf-8'))
    expected = ('boot.py', 'worker.py', 'telemetry.py', 'manage.py', 'lab_manage.py',
                'controller_settings.py', 'warning_filter.py', 'warning_hook_blob.py', 'process_guard.py',
                's1_battery_autostart.pth')
    if not isinstance(files, dict) or len(files) != len(expected):
        raise Exception('Unexpected embedded file list.')
    # Lab adds checkpoints to loop lines; keep comprehensions out of conditions.
    for name in expected:
        if name not in files:
            raise Exception('Unexpected embedded file list.')
    folder = tempfile_api.mkdtemp(prefix='s1-battery-lab-', dir='/tmp')
    written = []
    stopped = True
    try:
        for name in expected:
            path = folder + '/' + name
            fd = os_api.open(path, os_api.O_CREAT | os_api.O_EXCL | os_api.O_WRONLY, 384)
            written.append(path)
            with os_api.fdopen(fd, 'wb') as stream:
                stream.write(files[name].encode('utf-8'))
        if MODE == 'INSTALL':
            print('XT30 Battery Mod: INSTALL | Please wait: configuring battery checks and app battery errors...')
        elif MODE == 'UNINSTALL':
            print('XT30 Battery Mod: UNINSTALL | Please wait: restoring original battery checks and app battery errors...')
        elif MODE == 'DISABLE':
            print('XT30 Battery Mod: DISABLE | Please wait: stopping the battery estimate and restoring app battery errors...')
        # A regular file never waits for EOF from inherited background handles.
        with tempfile_api.TemporaryFile() as log:
            job = process_api.Popen(
                ['/data/python_files/bin/python', '-B', '-S', folder + '/lab_manage.py', MODE],
                stdin=process_api.DEVNULL, stdout=log, stderr=process_api.STDOUT,
                close_fds=True, start_new_session=True)
            stopped = False
            offset, pending = 0, b''
            deadline = clock_api.monotonic() + 90
            try:
                while job.poll() is None:
                    offset, pending = read_progress(os_api, log, offset, pending)
                    if clock_api.monotonic() >= deadline:
                        raise Exception('Action timed out. Run STATUS before retrying; completion is not verified.')
                    try:
                        job.wait(timeout=0.2)
                    except process_api.TimeoutExpired:
                        pass
                offset, pending = read_progress(os_api, log, offset, pending)
                print_output(pending)
                pending = b''
                if job.returncode != 0:
                    raise Exception('Action failed; review the message above. No success is assumed.')
            finally:
                stopped = stop_job(job, process_api)
                offset, pending = read_progress(os_api, log, offset, pending)
                print_output(pending)
                if not stopped:
                    print('ERROR: Recovery has not finished; installation files retained. Restart the robot before retrying.')
    finally:
        # Remove only the known temporary files. Persistent files have a
        # separate manifest and must pass independent restoration checks.
        if stopped:
            remove_temporary_files(os_api, written)
            os_api.rmdir(folder)


try:
    main()
except Exception as exc:
    print('ERROR: ' + str(exc))
