"""S1 Wi-Fi framing and DUML codec. Python standard library only."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import reduce
import secrets
import socket
import struct
import time

PORT = 10607
LOCAL_PORT = 10608
MTU = 1472


class PortUnavailableError(OSError):
    """Local ownership conflict; discovery must not hide it as a robot timeout."""


def crc(data, initial, polynomial):
    value = initial
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value


@dataclass(frozen=True)
class Frame:
    sender: int
    receiver: int
    sequence: int
    flags: int
    command_set: int
    command: int
    payload: bytes


def encode_frame(frame):
    length = 13 + len(frame.payload)
    if length > 1023:
        raise ValueError('DUML frame exceeds 1023 bytes')
    header = bytearray(struct.pack('<BHBBB HBBB', 0x55, 0x400 | length, 0,
                                  frame.sender, frame.receiver, frame.sequence,
                                  frame.flags, frame.command_set, frame.command))
    header[3] = crc(header[:3], 0x77, 0x8c)
    data = header + frame.payload
    return bytes(data) + struct.pack('<H', crc(data, 0x3692, 0x8408))


def decode_frames(data):
    """Reject truncated/corrupt bundles atomically; never scan into payloads."""
    frames = []
    cursor = 0
    while cursor < len(data):
        if len(data) - cursor < 13:
            raise ValueError('Truncated DUML frame')
        header = data[cursor:cursor+11]
        encoded_length = struct.unpack_from('<H', header, 1)[0]
        length = encoded_length & 1023
        if header[0] != 0x55 or encoded_length >> 10 != 1 or length < 13:
            raise ValueError('Invalid DUML header')
        raw = data[cursor:cursor+length]
        if len(raw) != length or crc(header[:3], 0x77, 0x8c) != header[3]:
            raise ValueError('Invalid DUML length/header checksum')
        if crc(raw[:-2], 0x3692, 0x8408) != int.from_bytes(raw[-2:], 'little'):
            raise ValueError('Invalid DUML checksum')
        if header[8] & 7:
            raise ValueError('Encrypted DUML frame is unsupported')
        frames.append(Frame(header[4], header[5], int.from_bytes(header[6:8], 'little'),
                            header[8], header[9], header[10], raw[11:-2]))
        cursor += length
    return frames


def envelope(session, kind, body=b'', sequence=0):
    length = 8 + len(body)
    if length > MTU:
        raise ValueError('Wi-Fi datagram exceeds MTU')
    header = struct.pack('<HHHB', 0x8000 | length, session, sequence, kind)
    return header + bytes([reduce(int.__xor__, header)]) + body


def decode_envelope(raw, session):
    if not 8 <= len(raw) <= MTU:
        raise ValueError('Invalid Wi-Fi datagram length')
    length, actual_session, sequence, kind = struct.unpack_from('<HHHB', raw)
    if length != 0x8000 | len(raw) or actual_session != session:
        raise ValueError('Wrong Wi-Fi length or session')
    if reduce(int.__xor__, raw[:8]):
        raise ValueError('Invalid Wi-Fi header checksum')
    return kind, sequence, raw[8:]


def handshake(session, seed):
    # Three link channels; receive window, send window, MTU, timing parameters.
    settings = b''.join(struct.pack('<HHHHBH', window, 100, MTU, 20, 0, 100)
                        for window in (100, 100, 20))
    return envelope(session, 0, struct.pack('<H', seed) + settings + bytes([1, 1, 4, 1, 2]))


class ReceiveWindow:
    """Cumulative acknowledgements never cross a missing reliable datagram."""
    def __init__(self, seed):
        self.last = seed
        self.pending = {}

    def accept(self, sequence, payload):
        distance = (sequence - self.last) & 65535
        if distance == 0 or distance >= 32768:
            return []
        if distance % 8 or distance > 100 * 8:
            raise ValueError('Reliable sequence outside receive window')
        previous = self.pending.get(sequence)
        if previous is not None and previous != payload:
            raise ValueError('Conflicting reliable retransmission')
        self.pending[sequence] = payload
        ready = []
        while ((self.last + 8) & 65535) in self.pending:
            self.last = (self.last + 8) & 65535
            ready.append(self.pending.pop(self.last))
        return ready


class WifiLink:
    """Bounded, exclusive S1 session; sends no motion or firmware commands."""
    def __init__(self, host, on_frame, *, clock=time.monotonic, sock=None):
        self.clock = clock
        self.host = host
        self.on_frame = on_frame
        self.socket = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if sock is None:
                if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                    self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                try:
                    self.socket.bind(('0.0.0.0', LOCAL_PORT))
                except OSError as error:
                    raise PortUnavailableError('UDP 10608 unavailable; close RoboMaster or the other Lab client: ' + str(error)) from error
                self.socket.connect((host, PORT))
                self.socket.setblocking(False)
        except BaseException:
            self.socket.close()
            raise
        self.session = secrets.randbelow(65535) + 1
        self.seed = secrets.randbelow(8192) << 3
        self.window = ReceiveWindow(self.seed)
        self.video = self.seed
        self.tx = self.seed
        self.txack = self.seed
        self.message = 0
        self.sequence = secrets.randbelow(65535)
        self.pending = {}
        self.synced = False
        self.closed = False
        self.last_receive = self.clock()
        self.last_ack = self.last_heartbeat = float('-inf')
        self.last_syn = float('-inf')
        self.invalid_count = 0
        self.recent_frames = deque()
        self.recent_set = set()

    def begin(self):
        self.socket.send(handshake(self.session, self.seed))
        self.last_syn = self.clock()

    def next_sequence(self):
        self.sequence = (self.sequence + 1) & 65535
        return self.sequence

    def send_frame(self, receiver, command_set, command, payload=b'', flags=0x40, sequence=None):
        if not self.synced:
            raise RuntimeError('S1 link is not established')
        if len(self.pending) >= 20:
            raise RuntimeError('S1 transmit window is full')
        sequence = self.next_sequence() if sequence is None else sequence
        frame = encode_frame(Frame(2, receiver, sequence, flags, command_set, command, payload))
        self.tx = (self.tx + 8) & 65535
        self.message = (self.message + 1) & 255
        body = struct.pack('<HHIBBH', self.window.last, self.tx, 0, self.message, 1, 0) + frame
        raw = envelope(self.session, 5, body, self.tx)
        self.socket.send(raw)
        now = self.clock()
        self.pending[self.tx] = (raw, now, now)
        return sequence

    def _acknowledged(self, value):
        if ((value - self.txack) & 65535) >= 32768:
            return
        if ((self.tx - value) & 65535) >= 32768 or (value - self.seed) % 8:
            raise ValueError('Peer acknowledges unsent data')
        self.txack = value
        for sequence in list(self.pending):
            if ((value - sequence) & 65535) < 32768:
                del self.pending[sequence]

    def ack(self, extra=b''):
        body = b''.join(struct.pack('<HHI', low, high, 0) for low, high in
                        ((self.video, self.video), (self.window.last, self.window.last), (self.txack, self.tx)))
        self.socket.send(envelope(self.session, 4, body + struct.pack('<H', len(extra)) + extra))
        self.last_ack = self.clock()

    def _receive(self, raw):
        kind, sequence, body = decode_envelope(raw, self.session)
        if kind == 0:
            if body != b'\x01' or sequence != 0:
                raise ValueError('Unexpected handshake reply')
            self.synced = True
            self.last_receive = self.clock()
            return
        if not self.synced:
            return
        frames = []
        if kind == 1:
            if len(body) < 26 or int.from_bytes(body[24:26], 'little') != len(body) - 26:
                raise ValueError('Malformed acknowledgement/data bundle')
            frames = decode_frames(body[26:])
            self._acknowledged(int.from_bytes(body[16:18], 'little'))
        elif kind == 2:
            # Video is not exposed. Acknowledge its delivery without decoding it.
            if len(body) < 12:
                raise ValueError('Malformed video datagram')
            if 0 < ((sequence - self.video) & 65535) < 32768:
                self.video = sequence
        elif kind == 3:
            if len(body) < 12 or int.from_bytes(body[2:4], 'little') != sequence:
                raise ValueError('Malformed reliable datagram')
            if body[9:12] != b'\x01\x00\x00':
                raise RuntimeError('Fragmented S1 control data is unsupported; completion is unconfirmed')
            decoded = decode_frames(body[12:])
            for ready in self.window.accept(sequence, tuple(decoded)):
                frames.extend(ready)
            self.ack()
        else:
            raise ValueError('Unsupported Wi-Fi datagram type')
        self.last_receive = self.clock()
        for frame in frames:
            if frame.receiver == 2 and frame not in self.recent_set:
                # The peer may repeat DUML in acknowledgement/data bundles as
                # well as reliable packets. Keep distinct print sequences intact.
                self.recent_set.add(frame)
                self.recent_frames.append(frame)
                if len(self.recent_frames) > 512:
                    self.recent_set.remove(self.recent_frames.popleft())
                self.on_frame(frame)

    def poll(self):
        if self.closed:
            raise RuntimeError('S1 link is closed')
        for _ in range(256):
            try:
                raw = self.socket.recv(MTU + 1)
            except BlockingIOError:
                break
            except ConnectionResetError:
                break  # UDP ICMP response; the bounded deadline still applies.
            try:
                self._receive(raw)
            except ValueError:
                self.invalid_count += 1
        now = self.clock()
        if not self.synced:
            if now - self.last_syn >= .2:
                self.begin()
            return
        if now - self.last_receive > 3:
            raise ConnectionError('S1 connection lost; program completion is unconfirmed')
        extra = b''
        if now - self.last_heartbeat >= .1:
            # Stock host link heartbeat; fixed channel configuration, no joystick data.
            extra = encode_frame(Frame(2, 9, self.next_sequence(), 0, 1, 4,
                                       bytes([0, 0, 4, 32, 0, 1, 8, 64, 0, 2, 16])))
            self.last_heartbeat = now
        if extra or now - self.last_ack >= .05:
            self.ack(extra)
        for sequence, (raw, sent, first) in list(self.pending.items()):
            if now - first >= 3:
                raise TimeoutError('S1 did not acknowledge a reliable message')
            if now - sent >= .2:
                self.socket.send(raw)
                self.pending[sequence] = (raw, now, first)

    def close(self):
        if not self.closed:
            self.closed = True
            self.pending.clear()
            self.socket.close()
