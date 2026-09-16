"""Bounded local process cleanup; Python 3.6, no robot commands or native writes."""
from contextlib import contextmanager
import os
import select
import signal
import subprocess
import tempfile
import time


def process_state(pid):
    with open('/proc/%d/stat' % pid) as stream:
        fields = stream.read().rsplit(')', 1)[1].split()
    return fields[19], fields[0]


def resume(pid, started):
    try:
        if process_state(pid)[0] == started:
            os.kill(pid, signal.SIGCONT)
    except ProcessLookupError:
        pass
    except FileNotFoundError:
        pass


def wait_child(pid, timeout):
    """Never turn a recovery timeout into an unbounded waitpid."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            found, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return 0
        if found:
            return status
        if time.monotonic() >= deadline:
            raise RuntimeError('recovery process did not finish before its deadline')
        time.sleep(0.01)


def isolate_child(keep):
    """A rescue must not retain the Lab output pipe, locks, or worker heartbeats."""
    os.setsid()
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, signal.SIG_IGN)
    null = os.open(os.devnull, os.O_RDWR)
    for fd in (0, 1, 2):
        os.dup2(null, fd)
    for name in os.listdir('/proc/self/fd'):
        fd = int(name)
        if fd > 2 and fd not in keep:
            try:
                os.close(fd)
            except OSError:
                pass


def rescue(pid, started, control, ready, timeout):
    owned = False
    status = 1
    try:
        isolate_child((control, ready))
        current, state = process_state(pid)
        if current != started or state in ('T', 't', 'Z'):
            raise RuntimeError('target changed or is already stopped')
        # This child owns BOTH signals. A parent stalled before the handshake
        # can never send SIGSTOP after the rescue deadline has already elapsed.
        if select.select([control], [], [], 0)[0]:
            return
        owned = True
        os.kill(pid, signal.SIGSTOP)
        os.write(ready, b'R')
        os.close(ready)
        select.select([control], [], [], timeout)
        status = 0
    except BaseException:
        pass
    finally:
        try:
            if owned:
                resume(pid, started)
        finally:
            os._exit(status)


@contextmanager
def paused_process(pid, started, timeout):
    current, state = process_state(pid)
    if current != started or state in ('T', 't', 'Z'):
        raise RuntimeError('target changed or was already stopped')
    control_r, control_w = os.pipe()
    ready_r, ready_w = os.pipe()
    try:
        child = os.fork()
    except BaseException:
        for fd in (control_r, control_w, ready_r, ready_w):
            os.close(fd)
        raise
    if child == 0:
        os.close(control_w)
        os.close(ready_r)
        rescue(pid, started, control_r, ready_w, timeout)
    os.close(control_r)
    os.close(ready_w)
    acknowledged = False
    try:
        if not select.select([ready_r], [], [], 1)[0] or os.read(ready_r, 1) != b'R':
            raise RuntimeError('service pause rescue did not become ready')
        acknowledged = True
        deadline = time.monotonic() + min(0.3, timeout / 2)
        while True:
            tasks = os.listdir('/proc/%d/task' % pid)
            states = []
            for tid in tasks:
                try:
                    with open('/proc/%d/task/%s/stat' % (pid, tid)) as stream:
                        states.append(stream.read().rsplit(')', 1)[1].split()[0])
                except FileNotFoundError:
                    states.append('?')
            if (tasks and all(s in ('T', 't') for s in states) and
                    tasks == os.listdir('/proc/%d/task' % pid)):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('could not pause service threads before deadline')
            time.sleep(0.005)
        yield
        if process_state(pid) != (started, 'T'):
            raise RuntimeError('service pause expired or target changed')
    finally:
        # Close first so a late-starting rescue sees cancellation before STOP.
        os.close(control_w)
        os.close(ready_r)
        try:
            if acknowledged:
                resume(pid, started)
        finally:
            # Do not kill the independent rescue or wait indefinitely for it.
            if wait_child(child, timeout + 0.5):
                raise RuntimeError('service pause rescue reported a failure')


def run_command(args, timeout, check=False):
    """Regular-file output cannot be held open as a PIPE by a descendant."""
    with tempfile.TemporaryFile() as output:
        job = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=output,
                               stderr=subprocess.STDOUT, close_fds=True,
                               start_new_session=True)
        try:
            job.wait(timeout=timeout)
        except BaseException:
            try:
                os.killpg(job.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                job.wait(timeout=1)
            except subprocess.TimeoutExpired:
                raise RuntimeError('command did not stop; restoration remains unverified')
            raise
        output.seek(0)
        data = output.read(65536)
        result = subprocess.CompletedProcess(args, job.returncode, data)
        if check:
            result.check_returncode()
        return result
