"""Synthetic protocol, discovery and lifecycle tests; no device traffic."""
from pathlib import Path
import socket
import struct
import sys
import threading
import unittest
from unittest.mock import Mock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lab-cli/scripts'))
import s1_discovery as discovery
import s1_native as native
import s1_wire as wire

GUID = 'a' * 32
SIGN = 'b' * 16
HOST = '192.168.2.1'
VERSION = b'\x00\x00DJI SCRATCH SYS' + bytes([0, 1, 0, 1]) + b'\x00' * 10


def state_bytes(number=0, guid=GUID):
    return bytes([number]) + guid.encode() + b'\x14' + b'0' * 20 + bytes([0, 0, 100, 0, 0])


def announcement(host=HOST):
    raw = bytearray(24)
    raw[:2] = b'\x5a\x5b'
    raw[6:10] = socket.inet_aton(host)
    key = 7
    for index in range(len(raw)):
        raw[index] ^= key
        key = ((key + 7) ^ 178) & 255
    return bytes(raw)


class WireTests(unittest.TestCase):
    def test_known_host_generated_duml_vector(self):
        raw = bytes.fromhex('550d043302281127400001e827')
        frame = wire.Frame(2, 40, 10001, 0x40, 0, 1, b'')
        self.assertEqual(wire.encode_frame(frame), raw)
        self.assertEqual(wire.decode_frames(raw), [frame])

    def test_corruption_and_trailing_fragments_cannot_be_completions(self):
        raw = wire.encode_frame(wire.Frame(169, 2, 7, 0, 63, 164, b'test'))
        for index in range(len(raw)):
            changed = bytearray(raw)
            changed[index] ^= 1
            with self.subTest(index=index), self.assertRaises(ValueError):
                wire.decode_frames(changed)
        for suffix in (b'\x55', b'bad trailing bytes'):
            with self.assertRaises(ValueError):
                wire.decode_frames(raw + suffix)

    def test_wrong_session_and_checksum_are_rejected(self):
        packet = wire.envelope(3, 0, b'\x01')
        self.assertEqual(wire.decode_envelope(packet, 3), (0, 0, b'\x01'))
        with self.assertRaises(ValueError):
            wire.decode_envelope(packet, 4)
        with self.assertRaises(ValueError):
            wire.decode_envelope(packet[:-1], 3)
        with self.assertRaises(ValueError):
            wire.decode_envelope(packet[:7] + b'\x00' + packet[8:], 3)

    def test_reordering_does_not_acknowledge_missing_data(self):
        window = wire.ReceiveWindow(0x1000)
        self.assertEqual(window.accept(0x1010, 'second'), [])
        self.assertEqual(window.last, 0x1000)
        self.assertEqual(window.accept(0x1008, 'first'), ['first', 'second'])
        self.assertEqual(window.last, 0x1010)
        self.assertEqual(window.accept(0x1008, 'first'), [])
        self.assertEqual(window.accept(0x1010, 'second'), [])

    def test_sequence_wrap_and_bounded_receive_window(self):
        window = wire.ReceiveWindow(65528)
        self.assertEqual(window.accept(8, 'second'), [])
        self.assertEqual(window.accept(0, 'first'), ['first', 'second'])
        with self.assertRaises(ValueError):
            window.accept(9, 'unaligned')
        with self.assertRaises(ValueError):
            window.accept(816, 'outside window')

    def link(self):
        sock = Mock()
        sock.recv.side_effect = BlockingIOError
        clock = Mock(return_value=0.)
        link = wire.WifiLink(HOST, Mock(), sock=sock, clock=clock)
        link.synced = True
        link.last_ack = link.last_heartbeat = 0.
        return link, sock, clock

    def test_retransmission_preserves_sequence_and_stops_on_ack(self):
        link, sock, clock = self.link()
        link.send_frame(169, 63, 163, b'test')
        original = sock.send.call_args.args[0]
        clock.return_value = .21
        link.poll()
        self.assertEqual(sock.send.call_args.args[0], original)
        link._acknowledged(link.tx)
        sock.send.reset_mock()
        clock.return_value = .42
        link.poll()
        self.assertNotIn(original, [call.args[0] for call in sock.send.call_args_list])

    def test_impossible_ack_cannot_drop_pending_command(self):
        link, sock, clock = self.link()
        link.send_frame(169, 63, 163, b'test')
        with self.assertRaises(ValueError):
            link._acknowledged((link.tx + 8) & 65535)
        self.assertEqual(len(link.pending), 1)

    def test_lost_link_and_missing_ack_are_bounded(self):
        link, sock, clock = self.link()
        clock.return_value = 3.1
        with self.assertRaises(ConnectionError):
            link.poll()
        link, sock, clock = self.link()
        link.send_frame(169, 63, 163, b'test')
        clock.return_value = link.last_receive = 3.1
        with self.assertRaises(TimeoutError):
            link.poll()

    def test_repeated_bundle_deduplicates_packets_not_identical_prints(self):
        link, sock, clock = self.link()
        frame = wire.Frame(201, 2, 7, 0, 63, 164, b'hello')
        def packet(frame):
            data = wire.encode_frame(frame)
            return wire.envelope(link.session, 1, struct.pack('<HHI', link.seed, link.seed, 0) * 3
                                 + struct.pack('<H', len(data)) + data)
        link._receive(packet(frame))
        link._receive(packet(frame))
        second = wire.Frame(201, 2, 8, 0, 63, 164, b'hello')
        link._receive(packet(second))
        self.assertEqual([call.args[0] for call in link.on_frame.call_args_list], [frame, second])

    def test_fragmented_data_cannot_be_acknowledged_as_complete(self):
        link, sock, clock = self.link()
        sequence = (link.seed + 8) & 65535
        body = struct.pack('<HHIBBH', link.seed, sequence, 0, 1, 2, 0) + b'fragment'
        with self.assertRaisesRegex(RuntimeError, 'Fragmented'):
            link._receive(wire.envelope(link.session, 3, body, sequence))
        self.assertEqual(link.window.last, link.seed)
        link.on_frame.assert_not_called()

    def test_port_conflict_closes_socket_and_names_other_client(self):
        sock = Mock()
        sock.bind.side_effect = OSError('occupied')
        with patch.object(wire.socket, 'socket', return_value=sock), self.assertRaisesRegex(OSError, '10608.*close RoboMaster'):
            wire.WifiLink(HOST, Mock())
        sock.close.assert_called_once()


class NativeTests(unittest.TestCase):
    def test_output_utf8_lengths_and_state_validation(self):
        text = 'Ciao è'
        self.assertEqual(native.decode_output(bytes([0, 2]) + struct.pack('<H', len(text)) + text.encode())['infoContent'], text)
        state, error = native.decode_state(state_bytes())
        self.assertEqual(state, {'state': 0, 'key': GUID})
        self.assertIsNone(error)
        for raw in (state_bytes()[:-1], state_bytes() + b'x', state_bytes(guid='z' * 32)):
            with self.assertRaises(ValueError):
                native.decode_state(raw)

    def test_service_gate_rejects_unknown_target(self):
        self.assertEqual(native.decode_version(VERSION)['value'], '01.00.01.00')
        with self.assertRaises(RuntimeError):
            native.decode_version(VERSION.replace(b'SCRATCH', b'UNKNOWN'))
        with self.assertRaises(RuntimeError):
            native.decode_version(VERSION[:17] + b'\xff' + VERSION[18:])

    def test_ack_correlation_requires_matching_sender_sequence_command(self):
        client = native.LabClient()
        client.expected.add((169, 7, 63, 163))
        for sender, sequence, command in ((9, 7, 163), (169, 8, 163), (169, 7, 164)):
            client.on_frame(wire.Frame(sender, 2, sequence, 0x80, 63, command, b'\x00'))
        self.assertEqual(client.responses, {})
        client.on_frame(wire.Frame(169, 2, 7, 0x80, 63, 163, b'\x00'))
        self.assertEqual(client.responses, {(169, 7, 63, 163): b'\x00'})

    def test_broken_output_pipe_preserves_link_for_owned_stop(self):
        client = native.LabClient()
        client.connected = True
        client.link = Mock()
        client.link.poll.side_effect = BrokenPipeError()
        with self.assertRaises(BrokenPipeError):
            client.poll()
        self.assertTrue(client.connected)
        client.link.poll.side_effect = ConnectionError()
        with self.assertRaises(ConnectionError):
            client.poll()
        self.assertFalse(client.connected)

    def test_state_query_requires_new_valid_push(self):
        client = native.LabClient()
        client.record(native.STATE, {'state': 0, 'key': GUID})
        def poll():
            client.on_frame(wire.Frame(169, 2, 8, 0, 63, 165, state_bytes(2)))
        client.poll = Mock(side_effect=poll)
        self.assertEqual(client.request(1, native.STATE)['state'], 2)
        client.poll.assert_called_once()

    def test_other_program_stop_and_busy_run_are_refused(self):
        for kind in (2, 5):
            client = native.LabClient()
            def request(op, key, value=None, timeout=10):
                if key == native.STATE:
                    return {'state': 2, 'key': 'c' * 32}
                return native.LabClient.request(client, op, key, value, timeout)
            client.request = request
            client.exchange = Mock()
            with self.assertRaises(RuntimeError):
                client.request(3, native.CONTROL, {'type': kind, 'guid': GUID, 'sign': SIGN})
            client.exchange.assert_not_called()

    def test_upload_requires_creation_ack_and_cannot_redirect_ftp(self):
        for address, finish, succeeds in ((HOST, b'\xd0', True),
                                           (HOST, b'\xd2', False),
                                           ('192.168.2.99', b'\xd0', False)):
            client = native.LabClient()
            client.host = HOST
            client.request = Mock(return_value={'state': 0, 'key': '0' * 32})
            negotiation = b'\x00' + socket.inet_aton(address)[::-1] + b'\x15\x00'
            client.exchange = Mock(side_effect=[negotiation, finish])
            client.transfer = Mock()
            client.poll = Mock(side_effect=lambda: client.record(native.STATE, {'state': 0, 'key': GUID}))
            if succeeds:
                client.upload(b'project')
                client.transfer.assert_called_once_with(b'project')
            else:
                with self.assertRaises(RuntimeError):
                    client.upload(b'project')
                if address != HOST:
                    client.transfer.assert_not_called()

    def test_upload_waits_through_downloading_after_creation_ack(self):
        client = native.LabClient()
        client.host = HOST
        client.record(native.STATE, {'state': 0, 'key': GUID})
        client.request = Mock(return_value=client.values[native.STATE])
        def exchange(command_set, command, *args, **kwargs):
            if command == 0xa1:
                return b'\x00' + socket.inet_aton(HOST)[::-1] + b'\x15\x00'
            # A cached Idle arriving with the ACK must not finish the upload.
            client.record(native.STATE, {'state': 0, 'key': GUID})
            return b'\xd0'
        client.exchange = Mock(side_effect=exchange)
        client.transfer = Mock()
        states = iter([None, 1, 0])
        def poll():
            state = next(states)
            if state is not None:
                client.record(native.STATE, {'state': state, 'key': GUID})
        client.poll = Mock(side_effect=poll)
        client.upload(b'project')
        self.assertEqual(client.poll.call_count, 3)
        self.assertEqual(client.values[native.STATE]['state'], 0)

    def test_ftp_failure_propagates_and_closes_worker_resources(self):
        ftp = Mock()
        ftp.transfercmd.side_effect = OSError('test transfer failure')
        client = native.LabClient()
        client.host = HOST
        client.poll = Mock()
        with patch.object(native.ftplib, 'FTP', return_value=ftp), self.assertRaisesRegex(RuntimeError, 'test transfer failure'):
            client.transfer(b'project')
        ftp.close.assert_called_once()
        self.assertFalse(ftp.trust_server_pasv_ipv4_address)

    def test_interrupt_closes_transfer_before_returning(self):
        started, released = threading.Event(), threading.Event()
        channel = MagicMock()
        channel.__enter__.return_value = channel
        def send(data):
            started.set()
            if not released.wait(2):
                raise AssertionError('Transfer socket was not cancelled')
        channel.sendall.side_effect = send
        channel.shutdown.side_effect = lambda *args: released.set()
        ftp = Mock()
        ftp.transfercmd.return_value = channel
        client = native.LabClient()
        client.host = HOST
        def wait(predicate, timeout):
            self.assertTrue(started.wait(2))
            raise KeyboardInterrupt()
        client.wait = wait
        with patch.object(native.ftplib, 'FTP', return_value=ftp), self.assertRaises(KeyboardInterrupt):
            client.transfer(b'project')
        self.assertTrue(released.is_set())
        ftp.close.assert_called_once()


class DiscoveryTests(unittest.TestCase):
    def test_only_matching_private_announcements_expose_an_endpoint(self):
        data = announcement()
        self.assertEqual(discovery.decode_announcement(data, HOST), HOST)
        for peer in ('8.8.8.8', '127.0.0.1', '192.168.2.2', 'bad'):
            self.assertIsNone(discovery.decode_announcement(data, peer))
        self.assertIsNone(discovery.decode_announcement(data[:23], HOST))
        self.assertIsNone(discovery.decode_announcement(b'bad' * 8, HOST))

    def connect(self, announcements, ready_hosts=(), host=None, fail_direct=False, unavailable=False,
                no_direct_route=False):
        links = []
        tick = [0.]
        listener = Mock()
        batches = list(announcements)
        listener.poll.side_effect = lambda: batches.pop(0) if batches else set()
        class Link:
            def __init__(self, address, callback):
                if links:
                    assert links[-1].closed, 'Old socket must close before replacement'
                self.host, self.callback = address, callback
                self.synced = False
                self.closed = False
                self.sent = False
                links.append(self)
            def begin(self):
                if no_direct_route and self.host == HOST:
                    raise OSError('No route to direct-mode network')
            def poll(self):
                if fail_direct and self.host == HOST:
                    raise ConnectionError('Direct mode unavailable')
                if self.host in ready_hosts:
                    self.synced = True
                    self.callback(wire.Frame(169, 2, 10, 0, 63, 165, state_bytes()))
                    if self.sent:
                        self.callback(wire.Frame(169, 2, 42, 0x80, 0, 1, VERSION))
            def send_frame(self, *args):
                self.sent = True
                return 42
            def close(self):
                self.closed = True
        client = native.LabClient()
        def sleep(value):
            tick[0] += .1
        with patch.object(native, 'WifiLink', Link), patch.object(native, 'Discovery', return_value=listener,
                side_effect=OSError('occupied') if unavailable else None) as factory, \
                patch.object(native.time, 'monotonic', side_effect=lambda: tick[0]), \
                patch.object(native.time, 'sleep', side_effect=sleep):
            try:
                client.connect(host, timeout=1)
            except (RuntimeError, TimeoutError) as error:
                return client, links, listener, factory, error
        return client, links, listener, factory, None

    def test_late_router_announcement_replaces_unconfirmed_direct(self):
        router = '192.168.1.42'
        for fail, no_route in ((False, False), (True, False), (False, True)):
            client, links, listener, factory, error = self.connect([set(), {router}], [router],
                                                                  fail_direct=fail, no_direct_route=no_route)
            self.assertIsNone(error)
            self.assertEqual(client.host, router)
            self.assertTrue(links[0].closed)
            self.assertTrue(client.connected)
            listener.close.assert_called_once()

    def test_ready_direct_wins_and_explicit_host_disables_discovery(self):
        client, links, listener, factory, error = self.connect([set(), {'192.168.1.42'}], [HOST])
        self.assertIsNone(error)
        self.assertEqual(client.host, HOST)
        self.assertEqual(len(links), 1)
        client, links, listener, factory, error = self.connect([], ['192.168.1.42'], host='192.168.1.42')
        factory.assert_not_called()
        self.assertIsNone(error)

    def test_multiple_announcements_are_not_arbitrarily_selected(self):
        client, links, listener, factory, error = self.connect([{'192.168.1.42', '192.168.1.43'}])
        self.assertRegex(str(error), 'Multiple S1')
        self.assertFalse(client.connected)
        self.assertTrue(all(link.closed for link in links))
        listener.close.assert_called_once()

    def test_unavailable_discovery_keeps_direct_and_timeout_closes_link(self):
        client, links, listener, factory, error = self.connect([], [HOST], unavailable=True)
        self.assertIsNone(error)
        client, links, listener, factory, error = self.connect([], unavailable=True)
        self.assertRegex(str(error), '--host')
        self.assertFalse(client.connected)
        self.assertTrue(links[0].closed)


if __name__ == '__main__':
    unittest.main()
