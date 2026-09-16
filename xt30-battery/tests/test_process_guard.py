"""Local Linux process tests: disposable Python children, never robot services."""
import importlib.util
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('test_guard', ROOT / 'src/process_guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class BoundedWaitTests(unittest.TestCase):
    def test_unresponsive_child_has_a_deadline(self):
        with patch.object(guard.os, 'waitpid', return_value=(0, 0), create=True), \
                patch.object(guard.os, 'WNOHANG', 1, create=True), \
                patch.object(guard.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, 'deadline'):
                guard.wait_child(123, 1)


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux fork, procfs and signals')
class LinuxRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.target = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        self.started = guard.process_state(self.target.pid)[0]
        self.addCleanup(self.clean_target)

    def clean_target(self):
        self.target.kill()
        self.target.wait(timeout=2)

    def assert_resumed(self, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if guard.process_state(self.target.pid)[1] not in ('T', 't'):
                return
            time.sleep(0.01)
        self.fail('disposable target was left stopped')

    def test_exception_resumes_target_and_reaps_rescue(self):
        with self.assertRaisesRegex(ValueError, 'transaction failed'):
            with guard.paused_process(self.target.pid, self.started, 1):
                self.assertEqual(guard.process_state(self.target.pid)[1], 'T')
                raise ValueError('transaction failed')
        self.assert_resumed()

    def test_preexisting_stop_is_not_taken_over(self):
        os.kill(self.target.pid, signal.SIGSTOP)
        deadline = time.monotonic() + 1
        while guard.process_state(self.target.pid)[1] != 'T' and time.monotonic() < deadline:
            time.sleep(0.01)
        with self.assertRaisesRegex(RuntimeError, 'already stopped'):
            with guard.paused_process(self.target.pid, self.started, 1):
                self.fail('unexpected pause ownership')
        self.assertEqual(guard.process_state(self.target.pid)[1], 'T')
        os.kill(self.target.pid, signal.SIGCONT)

    def test_pid_identity_mismatch_sends_no_signal(self):
        with patch.object(guard.os, 'kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'target changed'):
                with guard.paused_process(self.target.pid, 'wrong', 1):
                    pass
            kill.assert_not_called()

    def exercise_owner_failure(self, fault):
        rd, wr = os.pipe()
        owner = os.fork()
        if owner == 0:
            os.close(rd)
            try:
                with guard.paused_process(self.target.pid, self.started, 0.6):
                    os.write(wr, b'R')
                    time.sleep(60)
            finally:
                os._exit(0)
        os.close(wr)
        try:
            self.assertTrue(select.select([rd], [], [], 2)[0])
            self.assertEqual(os.read(rd, 1), b'R')
            os.kill(owner, fault)
            self.assert_resumed()
        finally:
            os.close(rd)
            os.kill(owner, signal.SIGKILL)
            guard.wait_child(owner, 2)

    def test_killed_owner_does_not_leave_service_stopped(self):
        self.exercise_owner_failure(signal.SIGKILL)

    def test_stalled_owner_does_not_leave_service_stopped(self):
        self.exercise_owner_failure(signal.SIGSTOP)

    def test_late_rescue_never_stops_target_after_timeout_returns(self):
        original = guard.isolate_child
        def delayed(keep):
            original(keep)
            time.sleep(1.2)
        with patch.object(guard, 'isolate_child', delayed), patch.object(guard.os, 'kill', wraps=os.kill):
            with self.assertRaises(RuntimeError):
                with guard.paused_process(self.target.pid, self.started, 0.6):
                    self.fail('late handshake accepted')
        self.assert_resumed()

    def test_rescue_drops_inherited_stdout_and_lock_descriptors(self):
        import fcntl
        import tempfile
        with tempfile.TemporaryFile() as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with guard.paused_process(self.target.pid, self.started, 1):
                children = Path('/proc/self/task/%d/children' % os.getpid()).read_text().split()
                rescues = [int(pid) for pid in children if int(pid) != self.target.pid]
                self.assertEqual(len(rescues), 1)
                paths = []
                for entry in Path('/proc/%d/fd' % rescues[0]).iterdir():
                    paths.append(os.readlink(str(entry)))
                self.assertNotIn(os.readlink('/proc/self/fd/%d' % lock.fileno()), paths)
                self.assertEqual(os.readlink('/proc/%d/fd/1' % rescues[0]), '/dev/null')

    def test_command_descendant_holding_stdout_does_not_block_completion(self):
        # The descendant lives briefly and retains stdout. No pipe EOF is needed.
        code = ('import os,time; child=os.fork(); '
                'time.sleep(1) if child==0 else print("parent finished",flush=True); os._exit(0)')
        begin = time.monotonic()
        result = guard.run_command([sys.executable, '-c', code], timeout=0.5)
        self.assertLess(time.monotonic() - begin, 0.8)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b'parent finished', result.stdout)

    def test_command_timeout_stops_owned_process_group(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            guard.run_command([sys.executable, '-c', 'import time; time.sleep(60)'], timeout=0.05)


if __name__ == '__main__':
    unittest.main()
