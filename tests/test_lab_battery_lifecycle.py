"""Offline lifecycle and bundle tests. No robot, native memory, or signals."""
import ast
import base64
import builtins
from contextlib import ExitStack
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import types
import time
import unittest
from unittest.mock import Mock, patch

APP = Path(__file__).resolve().parents[1] / 'xt30-battery'


def preprocess_lab_source(source):
    """Model DSP escape decoding, Lab checkpoints and the framework block.

    Lab locates loop keywords in each physical line, without parsing Python.
    A generator inside an if condition therefore gets a checkpoint indented
    relative to its inline 'for', breaking otherwise valid Python.
    """
    # DSPXMLParser normalizes these escapes before inserting loop checkpoints.
    source = source.replace('\\n', '\n').replace('\\"', '"')
    lines = []
    for line in source.splitlines():
        lines.append(line)
        if re.match(r'^[^\w]*#+', line):
            continue
        inline_for = 'for ' in line and ' in ' in line and ':' in line
        if 'while' in line or inline_for:
            if 'while ' in line:
                offset = line.find('while')
            elif inline_for:
                offset = line.find('for')
            else:
                offset = 0
            lines.append(' ' * (offset + 4) + 'time.sleep(0.005)')
    body = ''.join('    ' + line + '\n' for line in lines)
    return 'try:\n' + body + 'except Exception:\n    raise\n'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def embedded_lab_payload(source):
    outer = {node.targets[0].id: ast.literal_eval(node.value)
             for node in ast.parse(source).body
             if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)}
    payload = base64.b64decode(outer['PAYLOAD_B64']).decode('utf-8')
    values = {node.targets[0].id: ast.literal_eval(node.value)
              for node in ast.parse(payload).body
              if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)}
    return payload, values


manage = load('lifecycle_manager', APP / 'src/manage.py')
settings = Mock()
with patch.dict(sys.modules, {'manage': manage, 'controller_settings': settings}):
    controller = load('lifecycle_controller', APP / 'src/lab_manage.py')
WAIT_FOR_BOOT_CLAIM = controller.wait_for_boot_claim
bundle = load('lifecycle_bundle', APP / 'src/build_bundle.py')


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # GitHub's Windows runner can provide an 8.3 alias in its temp path.
        # Use canonical fixture paths so the robot's strict symlink guard is
        # exercised with an ordinary directory, not a Windows spelling alias.
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.output = self.stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
        self.source = self.directory / 'bundle'
        bundle.build(self.source)
        self.root = self.directory / 'installed'
        self.hook = self.directory / 'site' / 's1_battery_autostart.pth'
        self.hook.parent.mkdir()
        self.stock = self.directory / 'stock'
        self.stock.write_bytes(b'original stock content')
        self.stack.enter_context(patch.multiple(manage, ROOT=str(self.root), HOOK=str(self.hook),
            CLAIM=str(self.directory / 'claim'), __file__=str(self.source / 'manage.py'),
            STOCK={str(self.stock): manage.digest(self.stock.read_bytes())}))
        self.stack.enter_context(patch.multiple(controller,
            __file__=str(self.source / 'lab_manage.py'),
            BOOT_LOG=str(self.directory / 'boot.log'), WORKER_LOG=str(self.directory / 'worker.log')))
        self.stack.enter_context(patch.object(manage.os, 'geteuid', return_value=0, create=True))
        self.claim = self.stack.enter_context(patch.object(manage, 'process_claim', return_value=None))
        self.native = self.stack.enter_context(patch.object(manage, 'verify_native_references'))
        self.launch = self.stack.enter_context(patch.object(controller.subprocess, 'Popen'))
        self.ready = self.stack.enter_context(patch.object(controller, 'wait_for_boot_claim',
                                                         return_value={'pid': 42, 'started': 'start'}))
        self.settings = self.stack.enter_context(patch.object(controller, 'controller_settings'))
        self.stack.enter_context(patch.object(controller, 'worker_locked', return_value=False))
        self.stack.enter_context(patch.object(controller.time, 'sleep'))

    def test_install_status_disable_reenable_uninstall_and_repeat(self):
        controller.perform('INSTALL')
        self.assertTrue((self.root / 'enabled').is_file())
        self.assertTrue(self.hook.is_file())
        initial = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertEqual(self.launch.call_args.args[0][:2], [controller.PYTHON, '-S'])
        self.assertIn('--startup-delay', self.launch.call_args.args[0])
        self.assertIn('--ready-window', self.launch.call_args.args[0])
        self.assertEqual(self.launch.call_args.args[0][-2:], ['--ready-timeout', '300'])
        self.assertTrue(self.launch.call_args.kwargs['start_new_session'])
        controller.perform('INSTALL')
        self.assertEqual(self.launch.call_count, 2)
        self.assertEqual(initial, {p.name: p.read_bytes() for p in self.root.iterdir()})
        controller.perform('STATUS')
        self.claim.return_value = None
        controller.perform('DISABLE')
        self.assertFalse((self.root / 'enabled').exists())
        self.assertTrue(self.hook.is_file())
        controller.perform('INSTALL')
        self.assertTrue((self.root / 'enabled').exists())
        controller.perform('UNINSTALL')
        self.assertFalse(self.root.exists())
        self.assertFalse(self.hook.exists())
        self.assertEqual(self.stock.read_bytes(), b'original stock content')
        controller.perform('STATUS')
        controller.perform('UNINSTALL')
        self.assertIn('Battery checks: not verified', self.output.getvalue())
        self.assertIn('Battery warnings: visible', self.output.getvalue())
        self.assertIn('Battery percentage estimate: inactive', self.output.getvalue())
        self.assertGreaterEqual(self.native.call_count, 5)
        self.settings.set_mode.assert_any_call('XT30')
        self.settings.set_mode.assert_any_call('STOCK')

    def test_first_install_skips_old_worker_settling_delay(self):
        controller.perform('INSTALL')
        self.assertNotIn(7, [call.args[0] for call in controller.time.sleep.call_args_list])
        controller.time.sleep.reset_mock()
        controller.perform('INSTALL')
        self.assertIn(7, [call.args[0] for call in controller.time.sleep.call_args_list])

    def test_failed_controller_setup_keeps_disabled_recovery_installation(self):
        self.settings.set_mode.side_effect = RuntimeError('parameter mismatch')
        with self.assertRaisesRegex(RuntimeError, 'parameter mismatch'):
            controller.perform('INSTALL')
        self.assertTrue(self.hook.exists())
        self.assertTrue((self.root / 'worker.py').exists())
        self.assertFalse((self.root / 'enabled').exists())
        self.launch.assert_not_called()

    def test_stock_restore_failure_prevents_file_removal(self):
        controller.perform('INSTALL')
        self.settings.set_mode.side_effect = RuntimeError('stock readback failed')
        with self.assertRaisesRegex(RuntimeError, 'stock readback failed'):
            controller.perform('UNINSTALL')
        self.assertTrue(self.hook.exists())
        self.assertFalse((self.root / 'enabled').exists())

    def test_uninstall_requires_verified_restoration_before_removing_files(self):
        controller.perform('INSTALL')
        self.native.side_effect = RuntimeError('native references not restored')
        with self.assertRaisesRegex(RuntimeError, 'not restored'):
            controller.perform('UNINSTALL')
        self.assertTrue(self.hook.exists())
        self.assertTrue((self.root / 'worker.py').exists())
        self.assertFalse((self.root / 'enabled').exists())

    def test_unknown_files_refused_before_persistent_uninstall_changes(self):
        controller.perform('INSTALL')
        extra = self.root / 'unrelated.txt'
        extra.write_text('keep me')
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        controller.perform('STATUS')
        self.assertIn('Uninstall blocked by extra files: ["unrelated.txt"]', self.output.getvalue())
        with self.assertRaisesRegex(RuntimeError, 'unexpected installation files: .*unrelated.txt'):
            controller.perform('UNINSTALL')
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})
        self.assertTrue(self.hook.exists())

    def test_uninstall_removes_only_managed_python_bytecode_cache(self):
        controller.perform('INSTALL')
        cache = self.root / '__pycache__'
        cache.mkdir()
        (cache / 'worker.cpython-36.pyc').write_bytes(b'cached worker')
        (cache / 'warning_filter.cpython-36.opt-1.pyc').write_bytes(b'cached filter')
        controller.perform('UNINSTALL')
        self.assertFalse(self.root.exists())
        self.assertFalse(self.hook.exists())

    def test_uninstall_refuses_unknown_python_cache_entry(self):
        controller.perform('INSTALL')
        cache = self.root / '__pycache__'
        cache.mkdir()
        foreign = cache / 'other.cpython-36.pyc'
        foreign.write_bytes(b'keep me')
        controller.perform('STATUS')
        self.assertIn('__pycache__/other.cpython-36.pyc', self.output.getvalue())
        with self.assertRaisesRegex(RuntimeError, '__pycache__/other.cpython-36.pyc'):
            controller.perform('UNINSTALL')
        self.assertEqual(foreign.read_bytes(), b'keep me')
        self.assertTrue(self.hook.exists())

    def test_changed_install_is_neither_overwritten_nor_deleted(self):
        controller.perform('INSTALL')
        path = self.root / 'worker.py'
        path.write_text('changed by somebody else')
        for mode in ('INSTALL', 'UNINSTALL'):
            with self.assertRaisesRegex(RuntimeError, 'installed file changed'):
                controller.perform(mode)
        self.assertEqual(path.read_text(), 'changed by somebody else')

    def test_known_different_version_can_be_removed_but_is_not_silently_updated(self):
        controller.perform('INSTALL')
        old = manage.source_files()
        old['boot.py'] += b'\n# another release\n'
        with patch.object(manage, 'source_files', return_value=old):
            with self.assertRaisesRegex(RuntimeError, 'different version'):
                controller.perform('INSTALL')
            controller.perform('UNINSTALL')
        self.assertFalse(self.root.exists())

    def test_install_waits_for_matching_boot_claim(self):
        job = Mock(pid=42)
        job.poll.return_value = None
        claim = {'pid': 42, 'started': 'start'}
        with patch.object(manage, 'process_claim', side_effect=[None, claim]), \
                patch.object(controller.time, 'monotonic', side_effect=[0, 0, 0.25]):
            self.assertEqual(WAIT_FOR_BOOT_CLAIM(job, timeout=2), claim)

    def test_install_refuses_launcher_that_exits_before_claim(self):
        job = Mock(pid=42)
        job.poll.return_value = 1
        with patch.object(controller.time, 'monotonic', side_effect=[0, 0]):
            with self.assertRaisesRegex(RuntimeError, 'exited before claiming startup'):
                WAIT_FOR_BOOT_CLAIM(job, timeout=1)

    def test_install_does_not_claim_startup_without_boot_claim(self):
        job = Mock(pid=42)
        job.poll.return_value = None
        with patch.object(controller.time, 'monotonic', side_effect=[0, 0, 1]):
            with self.assertRaisesRegex(RuntimeError, 'did not claim startup'):
                WAIT_FOR_BOOT_CLAIM(job, timeout=1)

    def test_failed_write_rolls_back_fresh_install(self):
        with patch.object(manage.os, 'fsync', side_effect=[None, OSError('disk full')]):
            with self.assertRaisesRegex(OSError, 'disk full'):
                controller.perform('INSTALL')
        self.assertFalse(self.root.exists())
        self.assertFalse(self.hook.exists())
        self.launch.assert_not_called()

    def test_failed_hook_publish_rolls_back_fresh_install(self):
        with patch.object(manage.os, 'rename', side_effect=OSError('cannot publish')):
            with self.assertRaisesRegex(OSError, 'cannot publish'):
                controller.perform('INSTALL')
        self.assertFalse(self.root.exists())
        self.assertFalse(self.hook.exists())
        self.assertFalse(Path(str(self.hook) + '.staging').exists())

    def test_partial_install_refused_without_further_writes(self):
        self.root.mkdir()
        (self.root / 'worker.py').write_bytes(b'incomplete')
        with self.assertRaises(FileNotFoundError):
            controller.perform('INSTALL')
        self.assertEqual(list(self.root.iterdir()), [self.root / 'worker.py'])
        self.launch.assert_not_called()

    def test_status_does_not_enable_or_start_anything(self):
        controller.perform('STATUS')
        self.assertFalse(self.root.exists())
        self.launch.assert_not_called()
        self.native.assert_not_called()
        self.settings.set_mode.assert_not_called()

    def test_explicit_install_can_replace_only_a_stale_boot_claim(self):
        Path(manage.CLAIM).write_text('{"pid":123,"started":"77"}')
        controller.perform('INSTALL')
        self.assertFalse(Path(manage.CLAIM).exists())
        self.launch.assert_called_once()

    def test_manual_worker_rejects_pid_reuse_and_unrelated_commands(self):
        record = {'event': 'active', 'worker_pid': 123, 'worker_started': '77'}
        with patch.object(controller, 'events', return_value=[record]):
            for started, command, matched in (
                    ('88', b'/data/python_files/bin/python\0-S\0/tmp/s1-battery-worker-a.py\0--execute\0', False),
                    ('77', b'/data/python_files/bin/python\0-S\0/tmp/unrelated.py\0--execute\0', False),
                    ('77', b'/data/python_files/bin/python\0-S\0/tmp/s1-battery-worker-a.py\0--execute\0', True)):
                stat = '123 (python) S ' + ' '.join(['0'] * 18 + [started])
                with patch('builtins.open', side_effect=[io.StringIO(stat), io.BytesIO(command)]):
                    self.assertEqual(controller.manual_worker() is not None, matched)


class EmbeddedLauncherTests(unittest.TestCase):
    def setUp(self):
        self.source = (APP / 'scripts/xt30_battery.py').read_text(encoding='utf-8')

    def test_lab_checkpoint_model_reproduces_inline_generator_failure(self):
        source = ('def check(files, expected):\n'
                  '    if not all(name in files for name in expected):\n'
                  '        raise Exception("missing file")\n'
                  '    return files\n')
        compile(source, 'plain-python', 'exec')
        with self.assertRaises(IndentationError):
            compile(preprocess_lab_source(source), 'lab-python', 'exec')

    def test_all_payloads_are_python_36_compatible_and_match_sources(self):
        payload, values = embedded_lab_payload(self.source)
        packed = values['ARCHIVE_JSON'].encode('utf-8')
        self.assertEqual(hashlib.sha256(packed).hexdigest(), values['PAYLOAD_SHA256'])
        files = json.loads(packed.decode('utf-8'))
        self.assertEqual(files, bundle.payload_files())
        ast.parse(payload, feature_version=(3, 6))
        ast.parse(base64.b64decode(values['RUNNER_B64']), feature_version=(3, 6))
        ast.parse(self.source, feature_version=(3, 6))
        ast.parse(preprocess_lab_source(self.source), feature_version=(3, 6))
        for name, data in files.items():
            if name.endswith('.py'):
                ast.parse(data, filename=name, feature_version=(3, 6))

    def run_launcher(self, directory, source=None, failure=None, mode='INSTALL',
                     child_output=None, returncode=0, expected_error=None):
        def robot_import(name, *args, **kwargs):
            if name in ('zlib', 'bz2', 'lzma'):
                raise ModuleNotFoundError("No module named '%s'" % name)
            return builtins.__import__(name, *args, **kwargs)

        module = types.ModuleType('rm_define')
        module.__dict__['__builtins__'] = dict(builtins.__dict__, __import__=robot_import)
        captures = []
        job = Mock(returncode=returncode)
        job.poll.return_value = returncode
        if failure:
            job.poll.side_effect = [None, None]
            job.wait.side_effect = [subprocess.TimeoutExpired('controller', 30), 0]
        clock = Mock(side_effect=[0, 91])

        def pread(fd, size, offset):
            # Windows fixture for Linux os.pread; preserve the writer's offset.
            previous = os.lseek(fd, 0, os.SEEK_CUR)
            try:
                os.lseek(fd, offset, os.SEEK_SET)
                return os.read(fd, size)
            finally:
                os.lseek(fd, previous, os.SEEK_SET)

        def launch(command, **kwargs):
            captures.append(json.loads(Path(command[-2]).read_bytes()))
            self.assertEqual(command[1:4], ['-B', '-S', '-c'])
            self.assertEqual(command[-3], mode)
            data = child_output if child_output is not None else (
                'Controller finished.\nXT30_ACTION_DONE:' + mode + '\n').encode('ascii')
            os.write(kwargs['stdout'].fileno(), data)
            return job

        original_named = tempfile.NamedTemporaryFile
        def make_archive(**kwargs):
            kwargs['dir'] = directory
            return original_named(**kwargs)

        # Match the Lab builtins needed by the entry point. In particular,
        # sorted/open/compile/set are unavailable in the user-code namespace.
        allowed = ('Exception', 'all', 'dict', 'isinstance', 'len', 'str', 'globals', 'locals', 'print')
        restricted = {name: getattr(builtins, name) for name in allowed}
        restricted['__import__'] = builtins.__import__
        with patch.dict(sys.modules, {'rm_define': module}), \
                patch.object(tempfile, 'NamedTemporaryFile', side_effect=make_archive), \
                patch.object(subprocess, 'Popen', side_effect=launch) as launch_mock, \
                patch.object(os, 'pread', side_effect=pread, create=True), \
                patch.object(time, 'monotonic', clock), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            selected = (source or self.source).replace("MODE = 'INSTALL'", "MODE = '%s'" % mode, 1)
            processed = preprocess_lab_source(selected)
            namespace = {'__builtins__': restricted, 'time': types.SimpleNamespace(sleep=Mock()),
                         'stop': Mock(), 'robot_exit': Mock()}
            if expected_error is None:
                exec(compile(processed, 'test-lab-program', 'exec'), namespace)
                namespace['stop']()
            else:
                with self.assertRaisesRegex(Exception, expected_error):
                    exec(compile(processed, 'test-lab-program', 'exec'), namespace)
            namespace['robot_exit']()
        return captures, output.getvalue(), launch_mock, job

    def test_actual_generated_launcher_extracts_and_removes_its_whole_bundle(self):
        with tempfile.TemporaryDirectory() as directory:
            captures, output, launch, job = self.run_launcher(directory)
            self.assertNotIn('ERROR:', output)
            self.assertEqual(captures, [bundle.payload_files()])
            self.assertEqual(list(Path(directory).iterdir()), [])
            launch.assert_called_once()

    def test_every_mode_launches_without_optional_compression_modules(self):
        for mode in ('INSTALL', 'STATUS', 'DISABLE', 'UNINSTALL'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                captures, output, launch, job = self.run_launcher(directory, mode=mode)
                self.assertNotIn('ERROR:', output)
                if mode == 'STATUS':
                    self.assertTrue(output.startswith('XT30 Battery Mod status\n'))
                    self.assertNotIn('STATUS OK', output)
                else:
                    self.assertTrue(output.endswith(mode + ' OK\n'))
                self.assertEqual(captures, [bundle.payload_files()])
                self.assertEqual(list(Path(directory).iterdir()), [])
                launch.assert_called_once()

    def test_payload_runner_rejects_a_bad_checksum(self):
        runner = (APP / 'src/lab_payload_runner.py').read_text()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'payload.txt'
            archive.write_bytes(b'{}')
            result = subprocess.run([sys.executable, '-c', runner, 'STATUS', str(archive),
                                     'incorrect'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('checksum failed', result.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [archive])

    def test_payload_runner_executes_and_cleans_a_valid_payload(self):
        runner = (APP / 'src/lab_payload_runner.py').read_text()
        files = {name: '' for name in bundle.payload_files()}
        files['lab_manage.py'] = "import sys\nprint('XT30_ACTION_DONE:' + sys.argv[1])\n"
        packed = json.dumps(files).encode('utf-8')
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'payload.txt'
            archive.write_bytes(packed)
            result = subprocess.run([sys.executable, '-B', '-S', '-c', runner, 'STATUS',
                                     str(archive), hashlib.sha256(packed).hexdigest()],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'XT30_ACTION_DONE:STATUS\n')

    def test_timeout_is_not_reported_as_success_and_temporary_files_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            captures, output, launch, job = self.run_launcher(directory, failure=True, expected_error='Action timed out')
            self.assertNotIn('ERROR:', output)
            self.assertNotIn('INSTALL OK', output)
            self.assertEqual(list(Path(directory).iterdir()), [])
            job.terminate.assert_called_once()
            job.kill.assert_called_once()
            self.assertEqual([c.kwargs['timeout'] for c in job.wait.call_args_list], [30, 2])
            job.communicate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
