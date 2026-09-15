"""Protocol/state-transition tests without native processes or hardware."""
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / 'xt30-battery/src/controller_settings.py'
spec = importlib.util.spec_from_file_location('xt30_settings', PATH)
settings = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'worker': Mock()}):
    spec.loader.exec_module(settings)


class ControllerTests(unittest.TestCase):
    def test_known_transition_payloads_touch_only_capacity_and_authentication(self):
        self.assertEqual(settings.make_write_payload(settings.STOCK, settings.XT30), '00000000070000080000')
        self.assertEqual(settings.make_write_payload(settings.LEGACY, settings.XT30), '00000000070000')
        self.assertEqual(settings.make_write_payload(settings.XT30, settings.STOCK), '00000000070001080001')
        for state in (settings.STOCK, settings.XT30, settings.LEGACY):
            self.assertEqual(settings.make_write_payload(state, state), '00000000')
        with self.assertRaisesRegex(RuntimeError, 'unexpected pre-state'):
            settings.make_write_payload({7: 0, 8: 0, 9: 0, 10: 0}, settings.XT30)

    def test_readback_rejects_duplicates_missing_ordinals_and_extra_bytes(self):
        raw = list(b'\0' * 4 + b''.join(struct.pack('<HB', n, value) for n, value in settings.XT30.items()))
        self.assertEqual(settings.decode_values(raw), settings.XT30)
        for bad in (raw[:-1], raw + [0], raw[:7] + raw[4:7] + raw[10:], raw[:4] + [11, 0, 0] + raw[7:]):
            with self.assertRaises(RuntimeError):
                settings.decode_values(bad)

    def test_descriptor_mismatch_prevents_any_state_read_or_write(self):
        session = settings.Session(100, 'start')
        session.transaction = Mock(return_value=[0] * 4 + [7, 0] + [0] * 16 + list(b'wrong\0'))
        with self.assertRaisesRegex(RuntimeError, 'descriptor mismatch'):
            session.change(settings.XT30)
        self.assertEqual([call.args[0] for call in session.transaction.call_args_list], ['e1'])

    def test_idempotent_configuration_does_not_write(self):
        session = settings.Session(100, 'start')
        session.verify_descriptors = Mock()
        session.read = Mock(return_value=settings.XT30)
        session.transaction = Mock()
        session.change(settings.XT30)
        session.verify_descriptors.assert_called_once()
        session.transaction.assert_not_called()

    def test_failed_readback_restores_preexisting_values(self):
        session = settings.Session(100, 'start')
        session.verify_descriptors = Mock()
        session.read = Mock(side_effect=[settings.STOCK, settings.LEGACY, settings.STOCK])
        session.transaction = Mock()
        with self.assertRaisesRegex(RuntimeError, 'previous state restored'):
            session.change(settings.XT30)
        self.assertEqual([call.args for call in session.transaction.call_args_list], [
            ('e3', '00000000070000080000'), ('e3', '00000000070001080001')])

    def test_failed_rollback_is_reported_as_unverified(self):
        session = settings.Session(100, 'start')
        session.verify_descriptors = Mock()
        session.read = Mock(side_effect=[settings.STOCK, settings.LEGACY, settings.LEGACY])
        session.transaction = Mock()
        with self.assertRaisesRegex(RuntimeError, 'rollback unverified'):
            session.change(settings.XT30)

    def test_native_cli_failure_leaves_pause_context_normally(self):
        resumed = []
        @contextmanager
        def pause(pid, started):
            try:
                yield
            finally:
                resumed.append((pid, started))
        with patch.object(settings, 'paused_bridge', pause), \
                patch.object(settings.subprocess, 'run', side_effect=TimeoutError('deadline')):
            with self.assertRaises(TimeoutError):
                settings.Session(100, 'start').transaction('e2', settings.READ_PAYLOAD)
        self.assertEqual(resumed, [(100, 'start')])

    def test_parameter_session_parent_resumes_and_waits_after_exception(self):
        with patch.object(settings.worker, 'identity', return_value='start'), \
                patch.object(settings.os, 'pipe', return_value=(10, 11)), \
                patch.object(settings.os, 'fork', return_value=123, create=True), \
                patch.object(settings.os, 'close') as close, \
                patch.object(settings.os, 'kill') as kill, \
                patch.object(settings.os, 'waitpid', create=True) as wait, \
                patch.object(settings.signal, 'SIGSTOP', 19, create=True), \
                patch.object(settings.signal, 'SIGCONT', 18, create=True):
            with self.assertRaisesRegex(RuntimeError, 'transaction error'):
                with settings.paused_bridge(100, 'start'):
                    raise RuntimeError('transaction error')
        self.assertEqual([call.args for call in kill.call_args_list], [(100, 19), (100, 18)])
        wait.assert_called_once_with(123, 0)
        self.assertEqual([call.args[0] for call in close.call_args_list], [10, 11])


if __name__ == '__main__':
    unittest.main()
