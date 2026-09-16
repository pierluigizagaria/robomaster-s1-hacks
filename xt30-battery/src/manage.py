"""Install/remove the optional data-only S1 boot hook. Dry-run unless --execute."""
import argparse
import hashlib
import json
import os
import signal
import stat
import time

ROOT = '/data/s1-battery-estimator'
HOOK = '/data/python_files/lib/python3.6/site-packages/s1_battery_autostart.pth'
CLAIM = '/tmp/s1-battery-boot.claim'
STOCK = {
    '/init.rc': '09c3608090cb37c628d44a4404270feb3303170b0d056702e0a6c732ee336dea',
    '/system/bin/start_dji_system.sh': 'dcec211753bdca7a3e95a72629e9fdda9f1a7ebc053e4169440541517450e4a2',
    '/data/dji_scratch/bin/dji_scratch.py': '4d3dc175f1b50bfb3f3a64ce0e053cd67f702c97c96c1f2f1f8c220335ee16bb',
    '/data/python_files/lib/python3.6/site.py': 'dac39deafc69b01e37d1fdc18291eb120fdfe65175f2d6193272fa8a39769da3',
    '/system/bin/dji_hdvt_uav': '19d957e93672ce105d09eec509ec2fb873c8eb69a9287e0a505a6438538b2b38',
    '/system/bin/dji_sys': 'fb0df0de6080231c83fc1f87584a5baa4f237040a0ad3f2ce3cf3ef1466a8181',
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise RuntimeError('expected a regular file: ' + path)
    with open(path, 'rb') as stream:
        return stream.read()


def verify_stock():
    for path, expected in STOCK.items():
        if digest(read(path)) != expected:
            raise RuntimeError('unsupported or changed stock file: ' + path)


def source_files():
    folder = os.path.dirname(os.path.abspath(__file__))
    result = {name: read(folder + '/' + name)
              for name in ('boot.py', 'worker.py', 'telemetry.py', 'warning_filter.py',
                           'warning_hook_blob.py', 's1_battery_autostart.pth')}
    for name in ('boot.py', 'worker.py', 'telemetry.py', 'warning_filter.py', 'warning_hook_blob.py'):
        compile(result[name], name, 'exec')
    expected_hook = ("import builtins; exec(compile(builtins.open('/data/s1-battery-estimator/boot.py', "
                     "'rb').read(), 's1_battery_boot_hook', 'exec'), {'__name__': 's1_battery_boot_hook'})")
    if result['s1_battery_autostart.pth'].decode('ascii').strip() != expected_hook:
        raise RuntimeError('unexpected Python startup hook')
    return result


def installed_manifest():
    if os.path.islink(ROOT) or not os.path.isdir(ROOT):
        raise RuntimeError('installation directory is missing or a symlink')
    manifest = json.loads(read(ROOT + '/manifest.json').decode('utf-8'))
    if manifest.get('schema') != 's1-battery-autostart/v1' or manifest.get('stock_files') != STOCK:
        raise RuntimeError('unknown installation manifest')
    if set(manifest.get('files', {})) not in (
            {'boot.py', 'worker.py', 's1_battery_autostart.pth'},
            {'boot.py', 'worker.py', 'telemetry.py', 's1_battery_autostart.pth'},
            {'boot.py', 'worker.py', 'telemetry.py', 'warning_filter.py',
             'warning_hook_blob.py', 's1_battery_autostart.pth'}):
        raise RuntimeError('unexpected managed file list')
    for name, expected in manifest['files'].items():
        path = HOOK if name.endswith('.pth') else ROOT + '/' + name
        if digest(read(path)) != expected:
            raise RuntimeError('installed file changed; refusing to overwrite: ' + path)
    return manifest


def write_new(path, data, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        os.unlink(path)  # O_EXCL succeeded: this invocation created the file.
        raise


def process_claim():
    if not os.path.exists(CLAIM):
        return None
    claim = json.loads(read(CLAIM).decode('utf-8'))
    pid = claim.get('pid')
    if not isinstance(pid, int) or pid <= 1:
        raise RuntimeError('invalid boot process claim')
    try:
        with open('/proc/%d/stat' % pid) as stream:
            fields = stream.read().rsplit(')', 1)[1].split()
        if fields[19] != claim.get('started') or fields[0] == 'Z':
            return None
        with open('/proc/%d/cmdline' % pid, 'rb') as stream:
            command = stream.read().rstrip(b'\0').split(b'\0')
        if command == [b'']:
            # Exit can occur between stat and cmdline reads. A dying process
            # may expose an empty command before stat reports its zombie state.
            return None
        if command[:2] != [b'/data/python_files/bin/python', b'-S'] or command[2:3] not in (
                [ROOT.encode() + b'/boot.py'], [ROOT.encode() + b'/worker.py']):
            raise RuntimeError('claimed process is not the installed estimator')
        return claim
    except FileNotFoundError:
        return None


def disable():
    path = ROOT + '/enabled'
    if os.path.lexists(path):
        read(path)  # refuse symlinks
        os.unlink(path)
    claim = process_claim()
    if claim:
        os.kill(claim['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 7
        while time.monotonic() < deadline and process_claim():
            time.sleep(0.1)
        if process_claim():
            raise RuntimeError('estimator did not stop; installation retained')
    verify_native_references(recover_warnings=True)


def restore_warning_filter():
    """After stopping our worker, recover even a hook left by a killed watchdog."""
    path = ROOT + '/warning_filter.py'
    if not os.path.isfile(path):
        return  # Legacy installation predates the warning hook.
    import importlib.util
    spec = importlib.util.spec_from_file_location('s1_warning_recovery', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    deadline = time.monotonic() + 7
    while True:
        check = module.WarningFilter()
        try:
            if not check.status()['filter_active']:
                check.recover_expired()
                return
        finally:
            check.close()
        if time.monotonic() >= deadline:
            raise RuntimeError('warning filter still active; retaining recovery files')
        time.sleep(0.1)


def verify_native_references(recover_warnings=False):
    """Do not remove recovery files before an independent read-only check."""
    import importlib.util
    import sys
    sys.dont_write_bytecode = True
    if recover_warnings:
        restore_warning_filter()
    spec = importlib.util.spec_from_file_location('s1_installed_worker', ROOT + '/worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    deadline = time.monotonic() + 7
    while True:
        try:
            pid = worker.find_process()
            started = worker.identity(pid)
            with open('/proc/%d/exe' % pid, 'rb') as stream:
                worker.validate_image(stream.read())
            with open('/proc/%d/maps' % pid) as stream:
                base = worker.base_from_maps(stream.read())
            memory_fd = os.open('/proc/%d/mem' % pid, os.O_RDONLY)
            try:
                worker.Memory(memory_fd, base).validate()
                if worker.identity(pid) != started:
                    raise RuntimeError('HDVT restarted during restoration check')
            finally:
                os.close(memory_fd)
            warning_path = ROOT + '/warning_filter.py'
            if os.path.isfile(warning_path):
                warning_spec = importlib.util.spec_from_file_location('s1_installed_warning', warning_path)
                warning = importlib.util.module_from_spec(warning_spec)
                warning_spec.loader.exec_module(warning)
                check = warning.WarningFilter(readonly=True)
                try:
                    check.verify_restored()
                finally:
                    check.close()
            print('Native battery readers and installed warning filter independently verified restored.')
            return
        except (OSError, RuntimeError):
            if time.monotonic() >= deadline:
                raise RuntimeError('cannot verify native references; installation retained')
            time.sleep(0.1)


def main(action, execute=False):
    print(json.dumps({'action': action, 'execute': execute, 'root': ROOT, 'hook': HOOK,
                      'stock_file_writes': False, 'firmware_flash': False}, sort_keys=True))
    if os.geteuid() != 0:
        raise RuntimeError('root required')
    if action == 'status':
        manifest = installed_manifest()
        print(json.dumps({'installed': True, 'enabled': os.path.isfile(ROOT + '/enabled'),
                          'process': process_claim(), 'files': manifest['files']}, sort_keys=True))
        return
    if action == 'install':
        verify_stock()
        files = source_files()
        if os.path.lexists(ROOT) or os.path.lexists(HOOK):
            raise RuntimeError('target already exists; inspect or uninstall first')
        if os.path.realpath(os.path.dirname(HOOK)) != os.path.dirname(HOOK):
            raise RuntimeError('unexpected site-packages symlink')
        staging = HOOK + '.staging'
        if os.path.lexists(staging):
            raise RuntimeError('startup hook staging file already exists')
        if not execute:
            return
        os.mkdir(ROOT, 0o700)
        manifest = {'schema': 's1-battery-autostart/v1', 'stock_files': STOCK,
                    'files': {name: digest(data) for name, data in files.items()}}
        created = []
        try:
            for name in ('boot.py', 'worker.py', 'telemetry.py', 'warning_filter.py',
                         'warning_hook_blob.py', 'manifest.json'):
                data = (json.dumps(manifest, sort_keys=True).encode('ascii')
                        if name == 'manifest.json' else files[name])
                write_new(ROOT + '/' + name, data)
                created.append(ROOT + '/' + name)
            # Publish the hook only after every target exists; disabled initially.
            write_new(staging, files['s1_battery_autostart.pth'])
            created.append(staging)
            os.rename(staging, HOOK)
            created[-1] = HOOK
            installed_manifest()
        except BaseException:
            for path in reversed(created):
                os.unlink(path)
            os.rmdir(ROOT)  # Never remove unexpected files recursively.
            raise
        print('Installed, disabled. No stock file was modified.')
        return
    manifest = installed_manifest()
    if action == 'uninstall':
        expected = {name for name in manifest['files'] if name.endswith('.py')}
        expected.update(('manifest.json', 'enabled'))
        if set(os.listdir(ROOT)) - expected:
            raise RuntimeError('unexpected installation files; nothing removed')
    if action == 'enable':
        verify_stock()
    if not execute:
        return
    if action == 'enable':
        if not os.path.exists(ROOT + '/enabled'):
            write_new(ROOT + '/enabled', b'Enabled for the next stock Lab service boot.\n')
        print('Enabled for the next boot. This does not restart any robot service.')
    elif action in ('disable', 'uninstall'):
        disable()
        if action == 'uninstall':
            os.unlink(HOOK)
            managed = [name for name in manifest['files'] if name.endswith('.py')]
            for name in managed + ['manifest.json']:
                os.unlink(ROOT + '/' + name)
            os.rmdir(ROOT)  # refuses unexpected files; never recursive
            if os.path.exists(CLAIM):
                os.unlink(CLAIM)
        print(action.capitalize() + ' complete.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('install', 'status', 'enable', 'disable', 'uninstall'))
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    main(args.action, args.execute)
