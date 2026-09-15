# RoboMaster S1 XT30 Battery Mod - complete installation and reversal from Lab
# Paste this entire generated file into one Lab Python program.
# INSTALL sets guarded XT30 parameters and installs the automatic estimate.
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


def main():
    if MODE not in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
        raise Exception('MODE must be INSTALL, STATUS, DISABLE, or UNINSTALL.')
    os_api = load_module('os')
    process_api = load_module('sub' + 'process')
    tempfile_api = load_module('tempfile')
    hash_api = load_module('hashlib')
    base64_api = load_module('base64')
    json_api = load_module('json')
    packed = base64_api.b64decode(BUNDLE_B64)
    if hash_api.sha256(packed).hexdigest() != BUNDLE_SHA256:
        raise Exception('Embedded bundle checksum failed; copy the complete script again.')
    files = json_api.loads(packed.decode('utf-8'))
    expected = ('boot.py', 'worker.py', 'telemetry.py', 'manage.py', 'lab_manage.py',
                'controller_settings.py',
                's1_battery_autostart.pth')
    if not isinstance(files, dict) or len(files) != len(expected):
        raise Exception('Unexpected embedded file list.')
    # Lab adds checkpoints to loop lines; keep comprehensions out of conditions.
    for name in expected:
        if name not in files:
            raise Exception('Unexpected embedded file list.')
    folder = tempfile_api.mkdtemp(prefix='s1-battery-lab-', dir='/tmp')
    written = []
    try:
        for name in expected:
            path = folder + '/' + name
            fd = os_api.open(path, os_api.O_CREAT | os_api.O_EXCL | os_api.O_WRONLY, 384)
            written.append(path)
            with os_api.fdopen(fd, 'wb') as stream:
                stream.write(files[name].encode('utf-8'))
        print('Battery estimator: ' + MODE)
        job = process_api.Popen(
            ['/data/python_files/bin/python', '-B', '-S', folder + '/lab_manage.py', MODE],
            stdin=process_api.DEVNULL, stdout=process_api.PIPE, stderr=process_api.STDOUT,
            close_fds=True, start_new_session=True)
        try:
            output = job.communicate(timeout=90)[0]
        except process_api.TimeoutExpired:
            job.kill()
            output = job.communicate()[0]
            print(output.decode('utf-8', 'replace'))
            raise Exception('Action timed out. Run STATUS before retrying.')
        print(output.decode('utf-8', 'replace'))
        if job.returncode != 0:
            raise Exception('Action failed; review the message above. No success is assumed.')
    finally:
        # Remove only the known temporary files. Persistent files have a
        # separate manifest and must pass independent restoration checks.
        for path in written:
            os_api.unlink(path)
        os_api.rmdir(folder)


try:
    main()
except Exception as exc:
    print('ERROR: ' + str(exc))
