"""Direct S1 Lab client: Wi-Fi protocol, anonymous FTP, no vendor runtime."""
from __future__ import annotations

import ftplib
import hashlib
import re
import socket
import struct
import threading
import time

from s1_discovery import DIRECT_HOST, Discovery, private_host
from s1_wire import PortUnavailableError, WifiLink

SCRATCH_VERSION = 0x05000004
CONTROL = 0x05000020
STATE = 0x05000021
ERROR = 0x0500003F
OUTPUT = 0x05000040
SCRATCH = 0xa9
SUPPORTED_VERSION = bytes([0, 1, 0, 1])


def decode_version(payload):
    if len(payload) < 21 or payload[0] != 0 or payload[2:17] != b'DJI SCRATCH SYS':
        raise RuntimeError('Endpoint did not identify the S1 Scratch service')
    if payload[17:21] != SUPPORTED_VERSION:
        raise RuntimeError('Unsupported Scratch service version; no program uploaded')
    return {'value': '.'.join('%02d' % n for n in reversed(payload[17:21])),
            'service': 'DJI SCRATCH SYS'}


def decode_state(payload):
    if len(payload) < 34 or payload[0] > 5:
        raise ValueError('Malformed Lab state')
    guid = payload[1:33].decode('ascii')
    if not re.fullmatch('[0-9a-f]{32}', guid):
        raise ValueError('Malformed Lab project identity')
    state = {'state': payload[0], 'key': guid}
    if payload[0] == 5:
        if len(payload) < 64 or payload[34] != 20:
            raise ValueError('Malformed Lab error')
        length = int.from_bytes(payload[62:64], 'little')
        if length != len(payload) - 64:
            raise ValueError('Malformed Lab error text')
        error = {'key': guid, 'errorMsg': payload[64:].decode('utf-8', 'replace'),
                 'line': int.from_bytes(payload[58:62], 'little')}
        return state, error
    block_length = payload[33]
    end = 34 + block_length
    if len(payload) < end + 5:
        raise ValueError('Truncated Lab block state')
    count = int.from_bytes(payload[end+3:end+5], 'little')
    if len(payload) != end + 5 + count * 6:
        raise ValueError('Malformed Lab variable data')
    return state, None


def decode_output(payload):
    if len(payload) < 4:
        raise ValueError('Truncated Lab output')
    text = payload[4:].decode('utf-8', 'strict')
    length = int.from_bytes(payload[2:4], 'little')
    # Stock Python counts characters; other producers may report UTF-8 bytes.
    if length not in (len(text), len(payload) - 4):
        raise ValueError('Malformed Lab output length')
    return {'infoContent': text, 'infoType': payload[0], 'level': payload[1]}


class LabClient:
    def __init__(self, *, emit=None):
        self.emit = emit or (lambda *args, **kwargs: None)
        self.history = []
        self.values = {}
        self.connected = False
        self.host = None
        self.link = None
        self.responses = {}
        self.expected = set()
        self.state_revision = 0
        self.version = None

    def record(self, key, value):
        self.history.append(dict(monotonic=time.monotonic(), operation=4, key=hex(key),
                                 payload={'value': value}))
        self.values[key] = value
        if key == STATE:
            self.state_revision += 1
        elif key in (OUTPUT, ERROR):
            self.emit('output' if key == OUTPUT else 'script_error', value=value)

    def on_frame(self, frame):
        if frame.receiver != 2:
            return
        identity = (frame.sender, frame.sequence, frame.command_set, frame.command)
        if frame.flags & 0x80:
            if identity in self.expected:
                self.responses[identity] = frame.payload
            return
        if frame.sender not in (SCRATCH, 0xc9) or frame.command_set != 0x3f:
            return
        try:
            if frame.command == 0xa5 and frame.sender == SCRATCH:
                state, error = decode_state(frame.payload)
                self.record(STATE, state)
                if error:
                    self.record(ERROR, error)
            elif frame.command == 0xa4:
                self.record(OUTPUT, decode_output(frame.payload))
        except (ValueError, UnicodeError):
            # Never turn malformed input into an Idle or completion indication.
            return

    def _candidate(self, host):
        self.connected = False
        if self.link:
            self.link.close()
        self.host = private_host(host)
        self.values.clear()
        self.responses.clear()
        self.expected.clear()
        self.history.clear()
        self.state_revision = 0
        self.version = None
        self.link = WifiLink(self.host, self.on_frame)
        self.link.begin()

    def connect(self, host=None, timeout=15):
        listener = None
        if host is None:
            try:
                listener = Discovery()
            except OSError:
                self.emit('discovery_unavailable', message='UDP 45678 unavailable; trying direct S1 Wi-Fi. Use --host for a router address.')
        end = time.monotonic() + timeout
        discovered = set()
        attempted = set()
        version_identity = None

        def begin_candidate(address):
            try:
                self._candidate(address)
            except PortUnavailableError:
                raise
            except OSError:
                if host is not None or listener is None:
                    raise
                # Some adapters report no route on the first direct send.
                # Keep listening: a reachable router endpoint can still arrive.
                self.close()
                self.link = None

        try:
            begin_candidate(host or DIRECT_HOST)
            attempted.add(self.host)
            while time.monotonic() < end:
                if self.link:
                    try:
                        self.link.poll()
                    except (OSError, TimeoutError):
                        if host is not None or listener is None:
                            raise
                        self.link.close()
                        self.link = None
                if self.link and self.link.synced and version_identity is None:
                    sequence = self.link.send_frame(SCRATCH, 0, 1)
                    version_identity = (SCRATCH, sequence, 0, 1)
                    self.expected.add(version_identity)
                if version_identity in self.responses:
                    self.version = decode_version(self.responses.pop(version_identity))
                    self.expected.discard(version_identity)
                if self.link and self.version and self.state_revision:
                    self.connected = True
                    self.emit('connected', host=self.host)
                    return
                if listener:
                    discovered.update(listener.poll())
                    if len(discovered) > 1:
                        raise RuntimeError('Multiple S1 announcements; select one explicitly with --host')
                    candidates = discovered - attempted
                    if candidates:
                        begin_candidate(next(iter(candidates)))
                        attempted.add(self.host)
                        version_identity = None
                time.sleep(.01)
            raise TimeoutError('No confirmed S1 Lab connection. Check robot power and Wi-Fi; '
                               'use --host ADDRESS if router announcements are blocked.')
        except BaseException:
            self.close()
            raise
        finally:
            if listener:
                listener.close()

    def poll(self):
        try:
            self.link.poll()
        except BrokenPipeError:
            # An output consumer closing stdout does not sever the robot link;
            # leave it available for the caller's receipt-scoped stop.
            raise
        except (OSError, TimeoutError, RuntimeError):
            self.connected = False
            raise

    def wait(self, predicate, timeout=10):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.poll()
            if predicate():
                return
            time.sleep(.01)
        raise TimeoutError('Timed out waiting for the S1 Lab response')

    def exchange(self, command_set, command, payload=b'', timeout=10):
        sequence = self.link.send_frame(SCRATCH, command_set, command, payload)
        identity = (SCRATCH, sequence, command_set, command)
        self.expected.add(identity)
        try:
            self.wait(lambda: identity in self.responses, timeout)
            return self.responses.pop(identity)
        finally:
            self.expected.discard(identity)
            self.responses.pop(identity, None)

    def request(self, operation, key, value=None, timeout=10):
        if operation == 1 and key == SCRATCH_VERSION:
            return self.version
        if operation == 1 and key == STATE:
            revision = self.state_revision
            self.wait(lambda: self.state_revision > revision, timeout)
            return self.values[STATE]
        if operation == 3 and key == CONTROL:
            kind = value.get('type')
            guid, signature = value.get('guid', ''), value.get('sign', '')
            if kind not in (2, 5) or not re.fullmatch('[0-9a-f]{32}', guid) or not re.fullmatch('[0-9a-f]{16}', signature):
                raise ValueError('Only receipt-scoped Lab run/stop is supported')
            state = self.request(1, STATE)
            if kind == 2 and state['state'] != 0:
                raise RuntimeError('Lab busy; existing program left untouched')
            if kind == 5:
                if state['state'] == 0:
                    return None
                if state['key'] != guid:
                    raise RuntimeError('Active program does not match this receipt; no stop sent')
            result = self.exchange(0x3f, 0xa3, bytes([kind]) + guid.encode() + signature.encode(), timeout)
            if result != b'\x00':
                raise RuntimeError('S1 rejected Lab control (code %s)' % result[:1].hex())
            return None
        raise ValueError('Unsupported Lab operation')

    def upload(self, data):
        """Upload an ordinary DSP project; finish only after a fresh Idle push."""
        if not 1 <= len(data) <= 4 * 1024 * 1024:
            raise ValueError('Lab projects must be between 1 byte and 4 MiB')
        if self.request(1, STATE)['state'] != 0:
            raise RuntimeError('Lab busy; no upload sent')
        result = self.exchange(0x3f, 0xa1, struct.pack('<BBHI', 1, 0, 4, len(data)))
        if len(result) != 7 or result[0] != 0:
            raise RuntimeError('S1 rejected FTP negotiation')
        advertised = socket.inet_ntoa(result[1:5][::-1])
        port = int.from_bytes(result[5:7], 'little')
        if advertised != self.host or port != 21:
            raise RuntimeError('FTP negotiation redirected away from the selected S1; refused')
        self.transfer(data)
        result = self.exchange(0x3f, 0xa2, b'\x01\x00' + hashlib.md5(data).digest(), timeout=15)
        if result != b'\xd0':
            raise RuntimeError('S1 did not confirm project creation (code %s)' % result[:1].hex())
        # The creation ACK can arrive before Downloading -> Idle completes.
        # Require Idle received after the ACK, not cached while finalizing.
        revision = self.state_revision
        self.wait(lambda: self.state_revision > revision and self.values[STATE]['state'] == 0, 10)

    def transfer(self, data):
        """Keep Wi-Fi acknowledgements running while bounded FTP I/O blocks."""
        ftp = ftplib.FTP(timeout=5)
        ftp.trust_server_pasv_ipv4_address = False
        cancelled = threading.Event()
        finished = threading.Event()
        failures = []
        sockets = []

        def check():
            if cancelled.is_set():
                raise InterruptedError('FTP upload interrupted')

        def worker():
            stage = 'connecting'
            try:
                check()
                ftp.connect(self.host, 21, timeout=5)
                sockets.append(ftp.sock)
                check()
                stage = 'anonymous login'
                ftp.login()  # Standard anonymous FTP; no embedded credentials.
                check()
                stage = 'binary transfer setup'
                ftp.voidcmd('TYPE I')
                check()
                stage = 'opening data channel'
                channel = ftp.transfercmd('STOR /python/python_raw.dsp')
                sockets.append(channel)
                stage = 'sending project'
                with channel:
                    for offset in range(0, len(data), 16384):
                        check()
                        channel.sendall(data[offset:offset+16384])
                check()
                stage = 'confirming transfer'
                ftp.voidresp()
            except BaseException as error:
                failures.append(RuntimeError(stage + ': ' + str(error)))
            finally:
                ftp.close()
                finished.set()

        thread = threading.Thread(target=worker, name='s1-lab-ftp', daemon=True)
        thread.start()
        try:
            self.wait(finished.is_set, 30)
            if failures:
                raise RuntimeError('S1 FTP upload failed: ' + str(failures[0])) from failures[0]
        finally:
            cancelled.set()
            for channel in sockets:
                try:
                    channel.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                channel.close()
            thread.join(timeout=6)
            if thread.is_alive():
                raise RuntimeError('FTP worker did not finish within its socket timeout')

    def close(self):
        self.connected = False
        if self.link:
            self.link.close()
