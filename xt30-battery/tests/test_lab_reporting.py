"""Verified user-facing states and bounded launcher cleanup, without hardware."""
import ast
import builtins
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reporting_fixture', ROOT.parent / 'tests/test_lab_battery_lifecycle.py')
fixture_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)


def launcher_functions():
    tree = ast.parse((ROOT / 'src/lab_launcher.template.py').read_text())
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {}
    exec(compile(tree, 'launcher-functions', 'exec'), namespace)
    return namespace


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.LifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.controller = fixture_module.controller

    def test_status_off_requires_completed_readback_and_records_history(self):
        self.controller.perform('INSTALL')
        manifest = json.loads((self.fixture.root / 'manifest.json').read_text())
        self.assertEqual(manifest['battery_checks'], {'authentication': 0, 'capacity': 0})
        self.fixture.output.seek(0)
        self.fixture.output.truncate()
        self.fixture.settings.reset_mock()
        self.controller.perform('STATUS')
        self.assertIn('Battery checks (auth/capacity): OFF (last verified)', self.fixture.output.getvalue())
        self.assertNotIn('not read', self.fixture.output.getvalue())
        self.fixture.settings.set_mode.assert_not_called()

    def test_failed_readback_clears_previous_off_confirmation(self):
        self.controller.perform('INSTALL')
        self.fixture.settings.set_mode.side_effect = RuntimeError('readback failed')
        self.fixture.output.seek(0)
        self.fixture.output.truncate()
        with self.assertRaises(RuntimeError):
            self.controller.perform('UNINSTALL')
        self.assertNotIn('battery_checks', json.loads((self.fixture.root / 'manifest.json').read_text()))
        self.assertNotIn('UNINSTALL complete', self.fixture.output.getvalue())
        self.assertTrue(self.fixture.hook.exists())

    def test_old_installation_never_invents_verified_off(self):
        self.controller.perform('INSTALL')
        manifest = self.controller.installation()
        self.controller.record_checks(manifest)
        self.fixture.output.seek(0)
        self.fixture.output.truncate()
        self.controller.perform('STATUS')
        text = self.fixture.output.getvalue()
        self.assertNotIn('OFF (last verified)', text)
        self.assertIn('run INSTALL to verify', text)

    def test_failed_startup_does_not_print_install_complete(self):
        with patch.object(self.controller, 'start_installed', side_effect=RuntimeError('startup failed')):
            with self.assertRaises(RuntimeError):
                self.controller.perform('INSTALL')
        self.assertIn('authentication OFF | capacity OFF (verified)', self.fixture.output.getvalue())
        self.assertNotIn('INSTALL complete', self.fixture.output.getvalue())

    def test_late_background_process_prevents_uninstall_success(self):
        self.controller.perform('INSTALL')
        self.fixture.output.seek(0)
        self.fixture.output.truncate()
        with patch.object(self.controller, 'worker_locked', return_value=True):
            with self.assertRaisesRegex(RuntimeError, 'still stopping'):
                self.controller.perform('UNINSTALL')
        self.assertTrue(self.fixture.hook.exists())
        self.assertNotIn('UNINSTALL complete', self.fixture.output.getvalue())


class LauncherCleanupTests(unittest.TestCase):
    def setUp(self):
        self.namespace = launcher_functions()
        self.namespace['MODE'] = 'INSTALL'

    def test_dji_escape_decoding_reproduces_reported_string_syntax_error(self):
        source = "def broken():\n    return b'\\n'\n"
        compile(source, 'valid-desktop-python', 'exec')
        with self.assertRaises(SyntaxError):
            compile(fixture_module.preprocess_lab_source(source), 'dji-decoded-python', 'exec')

    def test_launcher_survives_dji_escape_decoding_unchanged(self):
        source = (ROOT / 'scripts/xt30_battery.py').read_text()
        decoded = source.replace('\\n', '\n').replace('\\"', '"')
        self.assertEqual(decoded, source)
        ast.parse(fixture_module.preprocess_lab_source(source), feature_version=(3, 6))

    def test_builder_refuses_launcher_with_dji_rewritten_string_literals(self):
        spec = importlib.util.spec_from_file_location('lab_builder', ROOT / 'build_lab_script.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        for source in ("value = b'\\n'", r'value = "an escaped \"quote\""'):
            compile(source, 'valid-before-dji-decoding', 'exec')
            with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, 'DJI project parser'):
                builder.validate_launcher(source)

    def test_unresponsive_process_gets_two_bounded_waits(self):
        job = Mock()
        job.poll.return_value = None
        job.wait.side_effect = subprocess.TimeoutExpired('job', 1)
        self.assertFalse(self.namespace['stop_job'](job, subprocess))
        self.assertEqual([call.kwargs['timeout'] for call in job.wait.call_args_list], [30, 2])
        job.terminate.assert_called_once()
        job.kill.assert_called_once()
        job.communicate.assert_not_called()

    def test_graceful_recovery_finishes_without_kill(self):
        job = Mock()
        job.poll.return_value = None
        self.assertTrue(self.namespace['stop_job'](job, subprocess))
        job.wait.assert_called_once_with(timeout=30)
        job.kill.assert_not_called()

    def test_progress_preserves_partial_lines_without_duplicates(self):
        os_api = Mock()
        os_api.pread.side_effect = [b'Battery checks: aut', b'hentication OFF\nApp errors:', b' restored\n']
        log = Mock()
        offset, pending = 0, b''
        with patch('sys.stdout', new_callable=io.StringIO) as output:
            for _ in range(3):
                offset, pending = self.namespace['read_progress'](os_api, log, offset, pending)
        self.assertEqual(output.getvalue(), 'Battery checks: authentication OFF\nApp errors: restored\n')
        self.assertEqual(pending, b'')
        self.assertEqual(offset, len(output.getvalue()))

    def test_maintenance_exit_preserves_mode_and_resume_without_recenter(self):
        robot, gimbal = Mock(), Mock()
        self.namespace.update(robot_ctrl=robot, gimbal_ctrl=gimbal,
                              rm_define=types.SimpleNamespace(robot_mode_free=123))
        self.namespace['robot_reset']()
        robot.set_mode.assert_called_once_with(123)
        gimbal.resume.assert_called_once()
        gimbal.recenter.assert_not_called()

    def test_failed_shutdown_retains_temporary_recovery_bundle(self):
        generated = ast.parse((ROOT / 'scripts/xt30_battery.py').read_text())
        for node in generated.body:
            if isinstance(node, ast.Assign):
                self.namespace[node.targets[0].id] = ast.literal_eval(node.value)
        rm_define = types.ModuleType('rm_define')
        rm_define.__dict__['__builtins__'] = builtins.__dict__
        self.namespace['rm_define'] = rm_define
        job = Mock()
        job.poll.return_value = None
        job.wait.side_effect = subprocess.TimeoutExpired('job', 1)
        original = tempfile.mkdtemp
        with tempfile.TemporaryDirectory() as directory:
            def make_folder(**kwargs):
                return original(prefix=kwargs['prefix'], dir=directory)
            with patch.object(tempfile, 'mkdtemp', side_effect=make_folder), \
                    patch.object(subprocess, 'Popen', return_value=job), \
                    patch.object(os, 'pread', return_value=b'', create=True), \
                    patch.object(time, 'monotonic', side_effect=[0, 91]), \
                    patch('sys.stdout', new_callable=io.StringIO) as output:
                with self.assertRaisesRegex(Exception, 'Action timed out'):
                    self.namespace['main']()
            self.assertIn('Recovery has not finished', output.getvalue())
            remaining = list(Path(directory).iterdir())
            self.assertEqual(len(remaining), 1)
            self.assertTrue((remaining[0] / 'lab_manage.py').is_file())

    def test_cleanup_survives_lab_stop_checkpoints(self):
        tree = ast.parse(fixture_module.preprocess_lab_source(
            (ROOT / 'src/lab_launcher.template.py').read_text()))
        functions = [node for node in tree.body[0].body if isinstance(node, ast.FunctionDef)]
        self.namespace['time'] = types.SimpleNamespace(sleep=Mock(side_effect=RuntimeError('Lab Stop')))
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'checkpoint-functions', 'exec'), self.namespace)
        os_api = Mock()
        written = ['one', 'two', 'three']
        self.namespace['remove_temporary_files'](os_api, written)
        self.assertEqual([call.args[0] for call in os_api.unlink.call_args_list], ['three', 'two', 'one'])
        self.assertEqual(written, [])


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.EmbeddedLauncherTests()
        self.fixture.setUp()

    def test_zero_exit_without_confirmation_is_a_lab_failure(self):
        for data in (b'', b'Battery checks: OFF\n', b'XT30_ACTION_DONE:UNINSTALL\n',
                     b'XT30_ACTION_DONE:INSTALL', b'XT30_ACTION_DONE:INSTALL\nERROR\n'):
            with self.subTest(output=data), tempfile.TemporaryDirectory() as directory:
                _, output, _, _ = self.fixture.run_launcher(
                    directory, child_output=data, expected_error='completion was not confirmed')
                self.assertIn('ERROR: Installer completion was not confirmed', output)
                self.assertEqual(list(Path(directory).iterdir()), [])

    def test_nonzero_exit_still_fails_with_a_completion_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            _, output, _, _ = self.fixture.run_launcher(
                directory, returncode=1, expected_error='exit 1')
        self.assertIn('ERROR: Action failed (exit 1)', output)

    def test_success_marker_is_private_and_adds_no_console_row(self):
        with tempfile.TemporaryDirectory() as directory:
            _, output, _, _ = self.fixture.run_launcher(directory)
        self.assertIn('Controller finished.', output)
        self.assertNotIn('XT30_ACTION_DONE', output)
        self.assertEqual(len(output.splitlines()), 2)

    def test_controller_confirms_only_after_main_returns(self):
        tree = ast.parse((ROOT / 'src/lab_manage.py').read_text())
        entry = tree.body[-1]
        for fault in (None, RuntimeError('incomplete restoration')):
            output = io.StringIO()
            def action(mode):
                self.assertEqual(mode, 'INSTALL')
                self.assertNotIn('XT30_ACTION_DONE', output.getvalue())
                if fault:
                    raise fault
            namespace = {'__name__': '__main__', '__doc__': '', 'STEP': 'restoring',
                         'main': action, 'signal': Mock(), 'sys': sys,
                         'argparse': __import__('argparse')}
            with self.subTest(fault=fault), patch.object(sys, 'argv', ['lab_manage.py', 'INSTALL']), \
                    patch('sys.stdout', output):
                if fault:
                    with self.assertRaises(SystemExit) as error:
                        exec(compile(ast.Module(body=[entry], type_ignores=[]), 'controller-entry', 'exec'), namespace)
                    self.assertEqual(error.exception.code, 1)
                    self.assertNotIn('XT30_ACTION_DONE', output.getvalue())
                else:
                    exec(compile(ast.Module(body=[entry], type_ignores=[]), 'controller-entry', 'exec'), namespace)
                    self.assertEqual(output.getvalue(), 'XT30_ACTION_DONE:INSTALL\n')


if __name__ == '__main__':
    unittest.main()
