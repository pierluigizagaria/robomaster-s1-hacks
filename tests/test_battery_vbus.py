import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).resolve().parents[1] / 'xt30-battery/src/telemetry.py'
SPEC = importlib.util.spec_from_file_location('vbus_probe', PATH)
vbus = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(vbus)


class VBusTests(unittest.TestCase):
    def test_live_ack_vector(self):
        raw = bytes.fromhex('550f04a209c9016680480150095059')
        row = vbus.unpack(raw)
        self.assertEqual((row['sender'], row['receiver']), (9, 0xC9))
        self.assertEqual(row['payload'], bytes.fromhex('5009'))
        self.assertEqual(vbus.pack(9, 0xC9, 0x6601, 0x48, 1, row['payload'], flags=0x80), raw)
        for index in (1, 3, 11, 14):
            corrupt = bytearray(raw)
            corrupt[index] ^= 1
            with self.assertRaises(ValueError):
                vbus.unpack(corrupt)

    def test_abstract_socket_peer_can_be_bytes(self):
        client = vbus.Client.__new__(vbus.Client)
        client.sock = Mock()
        client.sock.recvfrom.return_value = (bytes.fromhex('550f04a209c9016680480150095059'),
                                            b'\0/duss/mb/0x900')
        self.assertEqual(client.receive()['payload'], bytes.fromhex('5009'))

    def test_preserves_existing_lab_node(self):
        client = vbus.Client.__new__(vbus.Client)
        client.sock = Mock()
        client.owns_node = client.owns_message = False
        client.request = Mock(side_effect=[b'\x50\x09', b'\x00', b'\x00'])
        with patch('builtins.print'):
            client.subscribe()
            client.close()
        self.assertEqual([call.args[0] for call in client.request.call_args_list], [1, 3, 4])
        self.assertEqual(client.request.call_args_list[-1].args[1], bytes([0, 0xC9, 253]))


if __name__ == '__main__':
    unittest.main()
