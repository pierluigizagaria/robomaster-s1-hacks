"""ADB readiness under asynchronous init; no device or native DLL."""
import contextlib
import io
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = ROOT / 'root-adb/scripts/enable_root_adb.py'

class AdbProgramTests(unittest.TestCase):
    def run_program(self, statuses, failures=None, interfaces='', port='5555', calls=None):
        if calls is None:
            calls = []
        pending = list(statuses)
        def popen(argv, **kwargs):
            cmd = argv[-1]
            calls.append(cmd)
            output = ''
            if cmd.startswith('getprop'): output = port
            elif 'pidof' in cmd: output = '123'
            elif '/proc/123/status' in cmd:
                rows = pending.pop(0) if len(pending) > 1 else pending[0]
                output = chr(10).join(rows)
            elif 'ifconfig' in cmd: output = interfaces
            code = (failures or {}).get(cmd, 0)
            return types.SimpleNamespace(returncode=code, communicate=lambda: (output.encode(), None))
        fake = types.SimpleNamespace(Popen=popen, PIPE=-1, STDOUT=-2)
        define = types.ModuleType('rm_define')
        define.__builtins__ = {'__import__': lambda *args: fake}
        stream = io.StringIO()
        with patch.dict(sys.modules, {'rm_define': define}), contextlib.redirect_stdout(stream):
            namespace = runpy.run_path(str(PROGRAM))
            namespace['start']()
        return calls, stream.getvalue()

    def test_waits_for_restart_then_confirms_all_root_uids(self):
        calls, output = self.run_program([[], ['Name: adbd', 'Uid: 2000 2000 2000 2000'],
                                         ['Name: adbd', 'Uid: 0 0 0 0']])
        self.assertEqual(calls.count('/system/xbin/busybox sleep 1'), 2)
        self.assertIn('S1_ADB_READY', output)

    def test_program_passes_lab_checkpoint_validation(self):
        sys.path.insert(0, str(ROOT / 'lab-cli/scripts'))
        import s1_lab
        s1_lab.script_source(PROGRAM.read_text(), 'a' * 32)

    def test_already_root_needs_no_fixed_sleep(self):
        calls, output = self.run_program([['Name: adbd', 'Uid: 0 0 0 0']])
        self.assertEqual(calls[:5], [
            'test -f /system/bin/adb_en.sh',
            '/system/bin/sh /system/bin/adb_en.sh',
            'setprop service.adb.tcp.port 5555',
            'setprop ctl.restart adbd',
            'getprop service.adb.tcp.port'])
        self.assertFalse(any('sleep' in c for c in calls))
        self.assertIn('root=true', output)

    def test_nonroot_partial_uid_and_wrong_name_fail(self):
        for rows in [['Name: adbd', 'Uid: 0 2000 0 0'], ['Name: sh', 'Uid: 0 0 0 0'],
                     ['Name: adbd', 'Uid: 0 0 0'], []]:
            calls = []
            with self.subTest(rows=rows), self.assertRaisesRegex(Exception, 'within 10 checks'):
                self.run_program([rows], calls=calls)
            self.assertEqual(calls.count('/system/xbin/busybox pidof adbd || true'), 10)
            self.assertEqual(calls.count('/system/xbin/busybox sleep 1'), 9)

    def test_printed_commands_select_robot_and_exclude_loopback(self):
        statuses = [[], ['Name: adbd', 'Uid: 0 0 0 0']]
        interfaces = chr(10).join(['lo inet addr:127.0.0.1', 'wlan0 inet addr:  \t192.168.2.1  Mask:255.255.255.0',
                                  'alias inet addr:192.168.2.1', 'empty inet addr:0.0.0.0'])
        calls, output = self.run_program(statuses, interfaces=interfaces)
        self.assertIn('adb -s 192.168.2.1:5555 shell id', output)
        self.assertIn('adb -s 192.168.2.1:5555 shell getprop ro.product.model', output)
        self.assertNotIn('adb shell id', output)
        self.assertNotIn('adb connect 127.', output)
        self.assertNotIn('adb connect 0.0.0.0', output)
        self.assertEqual(output.count('adb connect 192.168.2.1:5555'), 1)

    def test_setup_errors_propagate(self):
        for command in ('test -f /system/bin/adb_en.sh', '/system/bin/sh /system/bin/adb_en.sh',
                        'setprop service.adb.tcp.port 5555', 'setprop ctl.restart adbd',
                        'getprop service.adb.tcp.port'):
            with self.subTest(command=command), self.assertRaisesRegex(Exception, 'failed'):
                self.run_program([], failures={command: 1})
        for port in ('', '0', '5038'):
            with self.subTest(port=port), self.assertRaisesRegex(Exception, 'Unexpected ADB TCP port'):
                self.run_program([], port=port)

    def test_missing_addresses_do_not_invalidate_confirmed_root_or_guess_endpoint(self):
        calls, output = self.run_program([['Name: adbd', 'Uid: 0 0 0 0']],
                                        failures={'/system/xbin/busybox ifconfig': 1})
        self.assertIn('S1_ADB_READY', output)
        self.assertIn('No address was read', output)
        self.assertNotIn('adb connect ', output)

if __name__ == '__main__': unittest.main()
