"""Extract and execute the XT30 Lab payload outside the DJI Lab interpreter."""
import hashlib
import json
import os
import sys
import tempfile


EXPECTED = ('boot.py', 'worker.py', 'telemetry.py', 'manage.py', 'lab_manage.py',
            'controller_settings.py', 'warning_filter.py', 'warning_hook_blob.py',
            'process_guard.py', 's1_battery_autostart.pth')


def main():
    if len(sys.argv) != 4 or sys.argv[1] not in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
        raise RuntimeError('invalid XT30 payload request')
    mode, archive_path, expected_hash = sys.argv[1:]
    with open(archive_path, 'rb') as stream:
        packed = stream.read()
    if hashlib.sha256(packed).hexdigest() != expected_hash:
        raise RuntimeError('embedded payload checksum failed; copy the complete Lab script again')
    files = json.loads(packed.decode('utf-8'))
    if not isinstance(files, dict) or set(files) != set(EXPECTED):
        raise RuntimeError('unexpected embedded file list')

    folder = tempfile.mkdtemp(prefix='s1-battery-payload-')
    written = []
    previous_argv = sys.argv
    try:
        for name in EXPECTED:
            path = folder + '/' + name
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            written.append(path)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(files[name].encode('utf-8'))
        sys.dont_write_bytecode = True
        sys.path.insert(0, folder)
        path = folder + '/lab_manage.py'
        sys.argv = [path, mode]
        with open(path, 'rb') as stream:
            source = stream.read()
        exec(compile(source, path, 'exec'), {'__name__': '__main__', '__file__': path})
    finally:
        sys.argv = previous_argv
        if folder in sys.path:
            sys.path.remove(folder)
        for path in reversed(written):
            os.unlink(path)
        os.rmdir(folder)


if __name__ == '__main__':
    main()
