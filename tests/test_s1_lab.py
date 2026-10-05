"""Protocol sequencing and source fidelity tests; no robot or vendor DLL needed."""
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import xml.dom.minidom

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lab-cli/scripts'))
import s1_lab as lab

GUID = 'a' * 32
RECEIPT = dict(schema=1, host='192.168.2.1', uploaded=True, guid=GUID, sign='b' * 16)


def row(key, value):
    return dict(operation=4, key=hex(key), payload={'Value': value, 'Error': 0})


def state(number, guid=GUID):
    return row(lab.STATE, dict(state=number, key=guid))


def output(text):
    return row(lab.OUTPUT, dict(infoContent=text))


class FakeClient:
    def __init__(self, batches=()):
        self.history = []
        self.values = {lab.STATE: {'state': 0, 'key': '0' * 32}}
        self.connected = True
        self.batches = list(batches)
        self.sent = []

    def poll(self):
        if self.batches:
            batch = self.batches.pop(0)
            self.history.extend(batch)
            for entry in batch:
                self.values[int(entry['key'], 16)] = lab.value_of(entry)

    def request(self, op, key, value=None):
        self.sent.append((op, key, value))
        if key == lab.STATE:
            return self.values[lab.STATE]
        if key == lab.CONTROL and value['type'] == 5:
            self.batches = [[state(0, '0' * 32)]]
        return ''

    def wait(self, predicate, timeout):
        for _ in range(100):
            if predicate():
                return
            self.poll()
        raise TimeoutError('test response missing')


class LabTests(unittest.TestCase):
    def setUp(self):
        source_directory = tempfile.TemporaryDirectory()
        self.addCleanup(source_directory.cleanup)
        self.source = Path(source_directory.name) / 'example.py'
        self.source.write_text('def start():\n    print("test")\n', encoding='utf-8')
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.errors = contextlib.redirect_stderr(io.StringIO())
        self.errors.__enter__()
        self.pipe = patch.object(lab, 'STDOUT_BROKEN', False)
        self.pipe.start()
        self.sleep = patch.object(lab.time, 'sleep', return_value=None)
        self.sleep.start()

    def tearDown(self):
        self.sleep.stop()
        self.pipe.stop()
        self.errors.__exit__(None, None, None)
        self.capture.__exit__(None, None, None)

    def test_packaging_preserves_xml_and_python(self):
        source = 'def start():\n    print("a < b & c > d")'
        packed = lab.project(lab.script_source(source, GUID), '<test & title>', GUID)
        doc = xml.dom.minidom.parseString(packed['xml'])
        actual = doc.getElementsByTagName('python_code')[0].firstChild.wholeText
        self.assertEqual(actual, lab.script_source(source, GUID).strip())
        self.assertEqual(doc.getElementsByTagName('title')[0].firstChild.data, '<test & title>')
        self.assertEqual(len(packed['sign']), 16)

    def test_original_firmware_parser_when_available(self):
        parser = ROOT / 'build/s1-lab-audit/firmware/dji_scratch/lib/dji_scratch_project_parser.py'
        if not parser.exists():
            self.skipTest('Optional private firmware reference not installed')
        logger = types.SimpleNamespace(error=lambda *args: None)
        modules = {'rm_log': types.SimpleNamespace(dji_scratch_logger_get=lambda: logger), 'rm_define': types.ModuleType('rm_define')}
        with patch.dict(sys.modules, modules):
            firmware_parser = runpy.run_path(str(parser))['DSPXMLParser']()
        source = lab.script_source((ROOT / 'root-adb/scripts/enable_root_adb.py').read_text(), GUID)
        packed = lab.project(source, 'ADB', GUID)
        self.assertEqual(firmware_parser.parseDSPString(packed['xml']), 0)
        self.assertEqual(firmware_parser.dsp_dict['python_code'], source.strip())

    def test_rejects_silent_source_corruption(self):
        for source in ('print("a\\nb")', 'print("a\\\"b")'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                lab.project(source, 'bad')
        for source in ('while True: pass', 'print("meanwhile")', '_s1_lab_original_start = 1'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                lab.script_source(source, GUID)

    def test_wrapper_reports_failure_and_allows_framework_cleanup(self):
        messages = []
        namespace = dict(print=messages.append)
        exec(lab.script_source('def start():\n    raise Exception("expected")', GUID), namespace)
        namespace['start']()
        self.assertTrue(any('FAILED_' + GUID in text for text in messages))
        self.assertFalse(any('DONE_' + GUID in text for text in messages))

    def test_busy_program_prevents_upload(self):
        client = lab.LabClient()
        client.request = unittest.mock.Mock(return_value={'state': 2, 'key': 'c' * 32})
        client.transfer = unittest.mock.Mock()
        client.exchange = unittest.mock.Mock()
        with self.assertRaisesRegex(RuntimeError, 'busy'):
            lab.upload(client, *lab.prepare_upload(self.source, 'hello'))
        client.transfer.assert_not_called()
        client.exchange.assert_not_called()

    def test_memory_upload_preserves_transfer_bytes_and_confirms_receipt(self):
        self.source.write_text('def start():\n    print("café < & >")\n', encoding='utf-8')
        data, draft = lab.prepare_upload(self.source, 'hello')
        # Compare the old UTF-8 file route with the new memory route, including
        # host newline conversion and XML escaping.
        packed = lab.project(lab.script_source(self.source.read_text(encoding='utf-8'), draft['guid']), 'hello', draft['guid'])
        legacy = self.source.with_suffix('.dsp')
        legacy.write_text(packed['xml'], encoding='utf-8')
        self.assertEqual(data, legacy.read_bytes())
        client = lab.LabClient()
        client.host = RECEIPT['host']
        client.request = unittest.mock.Mock(return_value={'state': 0, 'key': '0' * 32})
        client.exchange = unittest.mock.Mock(side_effect=[bytes([0, 1, 2, 168, 192, 21, 0]), b'\xd0'])
        client.transfer = unittest.mock.Mock()
        client.poll = unittest.mock.Mock(side_effect=lambda: client.record(lab.STATE, {'state': 0, 'key': '0' * 32}))
        with patch.object(Path, 'write_text', side_effect=AssertionError('Unexpected transfer file')):
            receipt = lab.upload(client, data, draft)
        client.transfer.assert_called_once_with(data)
        self.assertEqual(client.exchange.call_args.args, (63, 162, b'\x01\x00' + lab.hashlib.md5(data).digest()))
        self.assertEqual(receipt['host'], client.host)
        self.assertTrue(receipt['uploaded'])
        self.assertFalse(draft['uploaded'])

    def test_upload_failure_never_returns_receipt_as_successful(self):
        data, draft = lab.prepare_upload(self.source, 'hello')
        client = unittest.mock.Mock()
        client.upload.side_effect = RuntimeError('upload failed')
        with self.assertRaisesRegex(RuntimeError, 'upload failed'):
            lab.upload(client, data, draft)
        self.assertFalse(draft['uploaded'])

    def test_run_requires_own_done_and_fresh_idle(self):
        client = FakeClient([[state(0)], [output('S1LAB_DONE_' + 'c' * 32)],
                             [state(2)], [output('S1LAB_DONE_' + GUID)], [state(0)]])
        lab.run(client, RECEIPT, 1)
        self.assertEqual(client.batches, [])
        self.assertEqual([v['type'] for op, key, v in client.sent if key == lab.CONTROL], [2])

    def test_error_waits_for_cleanup_without_racing_exit(self):
        client = FakeClient([[state(2)], [output('S1LAB_FAILED_' + GUID + ' expected')], [state(0)]])
        with self.assertRaisesRegex(RuntimeError, 'expected'):
            lab.run(client, RECEIPT, 1)
        self.assertEqual([v['type'] for op, key, v in client.sent if key == lab.CONTROL], [2])

    def test_framework_error_after_done_is_not_success(self):
        client = FakeClient([[state(2)], [output('S1LAB_DONE_' + GUID)],
                             [row(lab.ERROR, dict(key=GUID, errorMsg='cleanup failed'))], [state(0)]])
        with self.assertRaisesRegex(RuntimeError, 'cleanup failed'):
            lab.run(client, RECEIPT, 1)

    def test_stop_refuses_other_program(self):
        client = FakeClient()
        client.values[lab.STATE] = {'state': 2, 'key': 'c' * 32}
        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            lab.stop(client, RECEIPT)
        self.assertFalse(any(key == lab.CONTROL for op, key, value in client.sent))

    def test_stop_matches_original_exit_action(self):
        client = FakeClient()
        client.values[lab.STATE] = {'state': 2, 'key': GUID}
        lab.stop(client, RECEIPT)
        self.assertEqual(client.sent[-1], (3, lab.CONTROL, dict(type=5, guid=GUID, sign=RECEIPT['sign'])))

    def test_receipt_cannot_target_another_robot_or_failed_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            path.write_text(json.dumps(RECEIPT))
            with self.assertRaises(ValueError):
                lab.read_receipt(path, '192.168.2.2')
            path.write_text(json.dumps(dict(RECEIPT, uploaded=False)))
            with self.assertRaises(ValueError):
                lab.read_receipt(path, RECEIPT['host'])

    def test_private_network_only(self):
        for host in ('192.168.2.1', '10.0.0.1', '172.16.0.2'):
            self.assertEqual(lab.private_host(host), host)
        for host in ('127.0.0.1', '0.0.0.0', '224.0.0.1', '8.8.8.8', '169.254.1.1'):
            with self.subTest(host=host), self.assertRaises(ValueError):
                lab.private_host(host)

    def test_human_output_hides_markers_and_json_remains_available(self):
        with patch.object(lab, 'JSON_OUTPUT', False), contextlib.redirect_stdout(io.StringIO()) as text, contextlib.redirect_stderr(io.StringIO()) as errors:
            lab.emit('output', value={'infoContent': '[time]: S1LAB_DONE_' + GUID})
            lab.emit('output', value={'infoContent': '[time]: Hello'})
            lab.emit('output', value={'infoContent': '[time]:   indented\n\n'})
            lab.emit('connected')
            lab.emit('error', message='expected error')
        self.assertEqual(text.getvalue(), 'Hello\n  indented\n\n')
        self.assertIn('Connected', errors.getvalue())
        self.assertIn('expected error', errors.getvalue())
        with patch.object(lab, 'JSON_OUTPUT', True), contextlib.redirect_stdout(io.StringIO()) as text:
            lab.emit('completed', guid=GUID)
        self.assertEqual(json.loads(text.getvalue())['guid'], GUID)

    def test_upload_receipt_redirect_roundtrip_with_shell_encodings(self):
        with patch.object(lab, 'JSON_OUTPUT', False), contextlib.redirect_stdout(io.StringIO()) as text:
            lab.emit('receipt', receipt=RECEIPT)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            for encoding in ('utf-8', 'utf-8-sig', 'utf-16'):
                with self.subTest(encoding=encoding):
                    path.write_bytes(text.getvalue().encode(encoding))
                    self.assertEqual(lab.read_receipt(path, RECEIPT['host']), RECEIPT)

    def test_bad_source_fails_before_opening_a_robot_connection(self):
        args = types.SimpleNamespace(command='run', host=None, file=self.source, title=None, connect_timeout=15, timeout=60)
        for source in (None, 'def start(:', 'def start():\n    print("a\\nb")'):
            with self.subTest(source=source), patch.object(lab, 'LabClient') as factory:
                if source is None:
                    self.source.unlink()
                else:
                    self.source.write_text(source)
                with self.assertRaises((FileNotFoundError, SyntaxError, ValueError)):
                    lab.perform(args)
                factory.assert_not_called()

    def test_closed_pipe_still_stops_the_owned_program(self):
        client = FakeClient([[state(2)], [output('hello')]])
        normal_poll = client.poll
        def polling():
            normal_poll()
            if client.values.get(lab.OUTPUT):
                lab.emit('output', value=client.values[lab.OUTPUT])
        client.poll = polling
        sink = unittest.mock.Mock()
        sink.write.side_effect = BrokenPipeError()
        with patch.object(lab, 'JSON_OUTPUT', False), patch.object(lab.sys, 'stdout', sink):
            with self.assertRaises(BrokenPipeError):
                lab.run(client, RECEIPT, 1)
        self.assertEqual([v['type'] for op, key, v in client.sent if key == lab.CONTROL], [2, 5])
        self.assertEqual(client.values[lab.STATE]['state'], 0)

    def test_status_needs_no_workspace_and_closes_connection(self):
        client = unittest.mock.Mock()
        client.request.side_effect = [{'value': 'test'}, {'state': 0}]
        args = types.SimpleNamespace(command='status', host=RECEIPT['host'], connect_timeout=15)
        with patch.object(lab, 'LabClient', return_value=client), contextlib.redirect_stdout(io.StringIO()) as text:
            lab.perform(args)
        self.assertEqual(text.getvalue(), 'Lab: Ready\nVersion: test\n')
        client.close.assert_called_once()

    def test_main_closes_connection_on_interrupt(self):
        client = unittest.mock.Mock()
        client.connect.side_effect = KeyboardInterrupt()
        with patch.object(lab, 'LabClient', return_value=client), patch.object(sys, 'argv', ['s1-lab', 'status']):
            with self.assertRaises(KeyboardInterrupt):
                lab.main()
        client.close.assert_called_once()

    def test_saved_receipt_selects_its_host_without_discovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'receipt.json'
            receipt = dict(RECEIPT, host='192.168.1.42')
            path.write_text(json.dumps(receipt))
            args = types.SimpleNamespace(command='stop', receipt=path, host=None, connect_timeout=15)
            client = unittest.mock.Mock()
            with patch.object(lab, 'LabClient', return_value=client), patch.object(lab, 'stop') as stop:
                lab.perform(args)
                client.connect.assert_called_once_with('192.168.1.42', timeout=15)
                stop.assert_called_once_with(client, receipt)
                client.close.assert_called_once()
            args.host = '192.168.1.43'
            with patch.object(lab, 'LabClient') as factory, self.assertRaises(ValueError):
                lab.perform(args)
            factory.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher')
    def test_portable_folder_help_and_status_without_vendor_loader(self):
        with tempfile.TemporaryDirectory(prefix='portable lab ') as directory:
            root = Path(directory)
            portable = root / 'S1 Lab'
            shutil.copytree(ROOT / 'lab-cli', portable,
                            ignore=shutil.ignore_patterns('bridge', '__pycache__'))
            launcher = portable / 's1-lab.cmd'
            env = dict(os.environ, S1_LAB_BRIDGE=str(root / 'missing.dll'), PYTHONIOENCODING='utf-8')
            result = subprocess.run([str(launcher), '--help'], cwd=root, env=env,
                                    capture_output=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('run-project', result.stdout)
            self.assertNotIn('enable-adb', result.stdout)
            self.assertNotIn('--bridge', result.stdout)
            # A separate interpreter imports only the copied folder. Fail any
            # attempt to load a DLL; emulate the robot, never contact hardware.
            harness = """
import sys
from unittest.mock import Mock, patch
def audit(event, args):
    if event == 'ctypes.dlopen':
        raise AssertionError('Vendor loader called')
sys.addaudithook(audit)
sys.path.insert(0, sys.argv[1])
import s1_lab
client = Mock()
client.request.side_effect = [{'value': 'test'}, {'state': 0}]
with patch.object(s1_lab, 'LabClient', return_value=client):
    sys.argv = ['s1-lab', 'status']
    s1_lab.main()
client.connect.assert_called_once_with(None, timeout=15)
client.close.assert_called_once()
"""
            result = subprocess.run([sys.executable, '-S', '-c', harness, str(portable / 'scripts')],
                                    cwd=root, env=env, capture_output=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'Lab: Ready\nVersion: test\n')


if __name__ == '__main__':
    unittest.main()
