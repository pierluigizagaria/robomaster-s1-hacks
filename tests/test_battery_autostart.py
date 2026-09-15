import importlib.util
import io
import json
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, mock_open, patch

ROOT = Path(__file__).resolve().parents[1] / 'xt30-battery/src'


def load(name):
    spec = importlib.util.spec_from_file_location('autostart_' + name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


boot = load('boot')
manage = load('manage')


class AutostartTests(unittest.TestCase):
    def test_source_priming_releases_subscription_before_returning(self):
        import struct
        client = Mock()
        client.receive.side_effect = [
            {'sender': 9, 'flags': 0, 'set': 0x48, 'command': 8,
             'payload': bytes([0, 253]) + struct.pack('<HhiBB', v, 0, 0, 0, 0)}
            for v in (12250, 12251, 12249)]
        telemetry = Mock(MESSAGE=253)
        telemetry.Client.return_value = client
        clock = Mock()
        clock.monotonic.return_value = 0
        boot.prime_voltage(telemetry, clock)
        client.subscribe.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_source_priming_cleans_up_after_subscription_failure(self):
        client = Mock()
        client.subscribe.side_effect = RuntimeError('subscription refused')
        telemetry = Mock()
        telemetry.Client.return_value = client
        with self.assertRaisesRegex(RuntimeError, 'refused'):
            boot.prime_voltage(telemetry, Mock())
        client.close.assert_called_once_with()

    def test_claim_handles_process_exit_between_stat_and_cmdline_reads(self):
        process_stat = '123 (python) R ' + ' '.join(['0'] * 18 + ['77'])
        with patch.object(manage.os.path, 'exists', return_value=True), \
                patch.object(manage, 'read', return_value=b'{"pid":123,"started":"77"}'), \
                patch('builtins.open', side_effect=[io.StringIO(process_stat), io.BytesIO(b'')]):
            self.assertIsNone(manage.process_claim())

    def test_readiness_rejects_startup_burst_then_frozen_cache(self):
        readiness = boot.SourceReadiness()
        results = [readiness.update(1, 'a', 12250 + tick if tick < 4 else 12254, tick / 4)
                   for tick in range(100)]
        self.assertFalse(any(results))
        for tick in range(100, 140):
            self.assertFalse(readiness.update(1, 'a', 12250 + tick % 2, tick / 4))
        self.assertTrue(readiness.update(1, 'a', 12250, 35))

    def test_readiness_requires_ten_seconds_and_resets_on_process_change(self):
        readiness = boot.SourceReadiness()
        for tick in range(40):
            self.assertFalse(readiness.update(1, 'a', 12250 + tick % 2, tick / 4))
        self.assertTrue(readiness.update(1, 'a', 12250, 10))
        self.assertFalse(readiness.update(1, 'b', 12251, 10.25))

    def test_pth_does_not_require_argv_during_python_36_site_startup(self):
        source = (ROOT / 's1_battery_autostart.pth').read_text()
        seen = []
        script = b"import sys; sys._s1_hook_test.append(__name__)"
        original = sys.argv
        try:
            del sys.argv
            with patch.object(sys, '_s1_hook_test', seen, create=True), \
                    patch('builtins.open', mock_open(read_data=script)):
                exec(compile(source, 'startup.pth', 'exec'), {})
            self.assertEqual(seen, ['s1_battery_boot_hook'])
        finally:
            sys.argv = original

    def test_only_stock_init_service_matches(self):
        command = [boot.PYTHON.encode(), boot.SCRATCH.encode()]
        self.assertTrue(boot.matches_service(command, 1, 0))
        for other, parent, uid in [(command, 200, 0), (command, 1, 1000),
                                   (command + [b'--test'], 1, 0),
                                   ([command[0], b'-c', command[1]], 1, 0),
                                   ([command[0], b'/tmp/user_lab.py'], 1, 0)]:
            self.assertFalse(boot.matches_service(other, parent, uid))

    def test_other_python_invocations_do_not_start_estimator(self):
        with patch('builtins.open', mock_open(read_data=b'python\0-c\0pass\0')), \
                patch.object(boot.os, 'getppid', return_value=1), \
                patch.object(boot.os, 'geteuid', return_value=0, create=True), \
                patch.object(boot, 'enabled') as enabled:
            boot.launch_from_site()
            enabled.assert_not_called()

    def test_disabled_hook_never_launches(self):
        data = boot.PYTHON.encode() + b'\0' + boot.SCRATCH.encode() + b'\0'
        with patch('builtins.open', mock_open(read_data=data)), \
                patch.object(boot.os, 'getppid', return_value=1), \
                patch.object(boot.os, 'geteuid', return_value=0, create=True), \
                patch.object(boot, 'enabled', return_value=False), \
                patch('subprocess.Popen') as launch:
            boot.launch_from_site()
            launch.assert_not_called()

    def test_hook_errors_do_not_break_stock_startup(self):
        with patch('builtins.open', side_effect=OSError('unavailable')):
            boot.launch_from_site()

    def test_changed_payload_or_stock_file_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {'boot.py': b'boot', 'worker.py': b'worker', 'telemetry.py': b'telemetry'}
            for name, data in files.items():
                (root / name).write_bytes(data)
            stock = root / 'stock'
            stock.write_bytes(b'original')
            manifest = {'schema': 's1-battery-autostart/v1',
                        'files': {name: manage.digest(data) for name, data in files.items()},
                        'stock_files': {str(stock): manage.digest(b'original')}}
            (root / 'manifest.json').write_text(json.dumps(manifest))
            with patch.object(boot, 'ROOT', folder):
                boot.verify_installation()
                stock.write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError, 'hash changed'):
                    boot.verify_installation()
                stock.write_bytes(b'original')
                (root / 'worker.py').write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError, 'hash changed'):
                    boot.verify_installation()

    def test_existing_installation_is_not_overwritten(self):
        with patch.object(manage.os, 'geteuid', return_value=0, create=True), \
                patch.object(manage, 'verify_stock'), patch.object(manage, 'source_files'), \
                patch.object(manage.os.path, 'lexists', return_value=True), \
                patch.object(manage.os, 'mkdir') as mkdir:
            with self.assertRaisesRegex(RuntimeError, 'already exists'):
                manage.main('install', True)
            mkdir.assert_not_called()


if __name__ == '__main__':
    unittest.main()
