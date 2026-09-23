"""Generic Lab bridge: pass a Base64 payload to a child and relay its output.

The decoded Lab payload supplies ARCHIVE_JSON, PAYLOAD_SHA256 and RUNNER_B64
before executing this bridge in the Lab script's globals.
"""
RUNNER_CODE = "import base64;exec(base64.b64decode('" + RUNNER_B64 + "'))"
ACTION_COMPLETE = False
FRAMEWORK_STOPPED = False
_stock_stop = stop
_stock_robot_exit = robot_exit


def robot_reset():
    robot_ctrl.set_mode(rm_define.robot_mode_free)
    gimbal_ctrl.resume()


def stop():
    global FRAMEWORK_STOPPED
    _stock_stop()
    FRAMEWORK_STOPPED = True


def robot_exit():
    _stock_robot_exit()
    if ACTION_COMPLETE and FRAMEWORK_STOPPED and MODE != 'STATUS':
        print(MODE + ' OK')


def module(name):
    return rm_define.__dict__['__builtins__']['__import__'](name, globals(), locals(), [], 0)


def show(data):
    for line in data.decode('utf-8', 'replace').splitlines():
        if line.strip() and line != 'XT30_ACTION_DONE:' + MODE and not line.startswith('ERROR'):
            print(line)


def progress(os_api, log, offset, pending):
    data = os_api.pread(log.fileno(), 65536, offset)
    parts = (pending + data).split(b''.fromhex('0a'))
    show(b''.fromhex('0a').join(parts[:-1]))
    return offset + len(data), parts[-1]


def stop_job(job, process_api):
    if job.poll() is not None:
        return True
    try:
        job.terminate()
    except OSError:
        if job.poll() is not None:
            return True
        raise
    try:
        job.wait(timeout=30)
    except process_api.TimeoutExpired:
        try:
            job.kill()
        except OSError:
            if job.poll() is not None:
                return True
            raise
        try:
            job.wait(timeout=2)
        except process_api.TimeoutExpired:
            return False
    return True


def main():
    if MODE not in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
        raise Exception('Invalid MODE')
    os_api = module('os')
    process_api = module('sub' + 'process')
    tempfile_api = module('tempfile')
    clock_api = module('time')
    path = None
    stopped = True
    try:
        with tempfile_api.NamedTemporaryFile(prefix='s1-battery-', dir='/tmp', delete=False) as source:
            path = source.name
            source.write(ARCHIVE_JSON.encode('utf-8'))
        print('XT30 Battery Mod status' if MODE == 'STATUS' else
              'XT30 Battery Mod ' + MODE.lower() + ', please wait...')
        with tempfile_api.TemporaryFile() as log:
            job = process_api.Popen(
                ['/data/python_files/bin/python', '-B', '-S', '-c', RUNNER_CODE,
                 MODE, path, PAYLOAD_SHA256],
                stdin=process_api.DEVNULL, stdout=log, stderr=process_api.STDOUT,
                close_fds=True, start_new_session=True)
            stopped = False
            offset, pending = 0, b''
            deadline = clock_api.monotonic() + 90
            try:
                while job.poll() is None:
                    offset, pending = progress(os_api, log, offset, pending)
                    if clock_api.monotonic() >= deadline:
                        raise Exception('Action timed out; run STATUS before retrying')
                    try:
                        job.wait(timeout=0.2)
                    except process_api.TimeoutExpired:
                        pass
                offset, pending = progress(os_api, log, offset, pending)
                show(pending)
                pending = b''
                if job.returncode != 0:
                    output = os_api.pread(log.fileno(), os_api.fstat(log.fileno()).st_size, 0)
                    errors = [line for line in output.decode('utf-8', 'replace').splitlines()
                              if line.startswith('ERROR')]
                    raise Exception(errors[-1] if errors else 'Action failed (exit ' + str(job.returncode) + ')')
                marker = ('XT30_ACTION_DONE:' + MODE).encode('ascii') + b''.fromhex('0a')
                size = os_api.fstat(log.fileno()).st_size
                if size < len(marker) or os_api.pread(log.fileno(), len(marker), size - len(marker)) != marker:
                    raise Exception('Installer completion was not confirmed; run STATUS before retrying')
            finally:
                stopped = stop_job(job, process_api)
                offset, pending = progress(os_api, log, offset, pending)
                show(pending)
                if not stopped:
                    print('ERROR: Recovery has not finished; restart the robot before retrying')
    finally:
        if stopped and path is not None:
            os_api.unlink(path)


main()
ACTION_COMPLETE = True
