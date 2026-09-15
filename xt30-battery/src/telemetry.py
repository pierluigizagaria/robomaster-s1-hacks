#!/usr/bin/env python3
"""Subscribe to battery telemetry through the robot's existing local broker.

Python 3.6 compatible. Run with -S under root ADB. Dry-run by default.
Creates only its own temporary VBUS node/subscription, removed on normal exit.
No UART access, service suspension, firmware writes, or actuator commands.
Receive timestamps show broker delivery, not the age of the controller cache.
"""
import argparse
import json
import signal
import socket
import struct
import time


BROKER = '\0/duss/mb/0x900'
NODE = 0xC9  # vt_air instance 6 has an existing local return route
ADDRESS = '\0/duss/mb/0x906'
MESSAGE = 253  # separate from Lab's normal message 0
BATTERY_UID = 0x000200096862229F


def crc(data, initial, polynomial, mask):
    value = initial
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (polynomial if value & 1 else 0)
    return value & mask


def pack(sender, receiver, sequence, command_set, command, payload, flags=0x40):
    size = 13 + len(payload)
    if size > 1023:
        raise ValueError('frame too long')
    data = bytearray([0x55, size & 255, 4 | (size >> 8), 0,
                      sender, receiver, sequence & 255, sequence >> 8,
                      flags, command_set, command])
    data[3] = crc(data[:3], 0x77, 0x8C, 255)
    data.extend(payload)
    data.extend(struct.pack('<H', crc(data, 0x3692, 0x8408, 65535)))
    return bytes(data)


def unpack(data):
    if len(data) < 13 or data[0] != 0x55:
        raise ValueError('invalid frame header')
    if (data[1] | ((data[2] & 3) << 8)) != len(data):
        raise ValueError('invalid frame length')
    if crc(data[:3], 0x77, 0x8C, 255) != data[3]:
        raise ValueError('invalid header CRC')
    if crc(data[:-2], 0x3692, 0x8408, 65535) != struct.unpack('<H', data[-2:])[0]:
        raise ValueError('invalid frame CRC')
    return {'sender': data[4], 'receiver': data[5],
            'sequence': data[6] | data[7] << 8, 'flags': data[8],
            'set': data[9], 'command': data[10], 'payload': data[11:-2]}


class Client:
    def __init__(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.settimeout(0.5)
        try:
            self.sock.bind(ADDRESS)  # refuses a second instance
        except BaseException:
            self.sock.close()
            raise
        self.sequence = 0x6600
        self.owns_node = False
        self.owns_message = False

    def receive(self):
        raw, peer = self.sock.recvfrom(4096)
        msg = unpack(raw)
        if peer not in ('', b'', BROKER, BROKER.encode('ascii')) or msg['receiver'] != NODE:
            raise RuntimeError('unexpected local message source/destination: peer=%r frame=%s' % (peer, raw.hex()))
        return msg

    def request(self, command, payload):
        self.sequence += 1
        self.sock.sendto(pack(NODE, 9, self.sequence, 0x48, command, payload), BROKER)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                msg = self.receive()
            except socket.timeout:
                continue
            if (msg['flags'] & 0x80 and msg['sender'] == 9 and
                    msg['sequence'] == self.sequence and msg['set'] == 0x48 and
                    msg['command'] == command):
                print('VBUS_ACK ' + json.dumps({'command': command,
                                               'payload': msg['payload'].hex()}), flush=True)
                return msg['payload']
        raise RuntimeError('VBUS request timed out: %02x' % command)

    def subscribe(self):
        result = self.request(1, bytes([NODE]) + struct.pack('<I', 0x03000000))
        if not result or result[0] not in (0, 0x50):
            raise RuntimeError('node registration rejected')
        self.owns_node = result[0] == 0
        payload = bytes([NODE, MESSAGE, 0, 0, 1]) + struct.pack('<QH', BATTERY_UID, 10)
        result = self.request(3, payload)
        if not result or result[0] != 0:
            raise RuntimeError('battery subscription rejected')
        self.owns_message = True

    def close(self):
        errors = []
        try:
            if self.owns_message:
                try:
                    result = self.request(4, bytes([0, NODE, MESSAGE]))
                    if not result or result[0] != 0:
                        errors.append('delete message rejected')
                except Exception as exc:
                    errors.append(str(exc))
            if self.owns_node:
                try:
                    result = self.request(2, bytes([NODE]))
                    if not result or result[0] != 0:
                        errors.append('reset node rejected')
                except Exception as exc:
                    errors.append(str(exc))
        finally:
            self.sock.close()
        print('VBUS_CLEANUP ' + json.dumps({'errors': errors}), flush=True)
        if errors:
            raise RuntimeError('subscription cleanup failed')


def run(args):
    print(json.dumps({'execute': args.execute, 'duration': args.duration,
                      'commands': ['48/01', '48/03', '48/04', '48/02'],
                      'node': hex(NODE), 'uid': hex(BATTERY_UID),
                      'volatile_subscription_only': True}), flush=True)
    if not args.execute:
        return
    client = Client()
    count = 0
    try:
        client.subscribe()
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            try:
                msg = client.receive()
            except socket.timeout:
                continue
            if msg['flags'] & 0x80 or (msg['set'], msg['command']) != (0x48, 8):
                continue
            payload = msg['payload']
            if payload[1:2] != bytes([MESSAGE]):
                continue
            if len(payload) != 12 or msg['sender'] != 9:
                raise RuntimeError('unexpected battery subscription layout')
            voltage, temperature, current, percent, state = struct.unpack('<HhiBB', payload[2:])
            count += 1
            print('BATTERY ' + json.dumps({'received_monotonic': time.monotonic(),
                  'sequence': msg['sequence'], 'voltage_mv': voltage, 'temperature': temperature,
                  'current': current, 'percent': percent, 'state': state,
                  'raw_hex': payload.hex()}), flush=True)
    finally:
        client.close()
    if not count:
        raise RuntimeError('no battery messages received')
    print('VBUS_SAMPLES=%d' % count, flush=True)


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise RuntimeError('interrupted by signal %d' % signum)
    for name in ('SIGTERM', 'SIGHUP'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--duration', type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.duration <= 90:
        parser.error('duration must be between 1 and 90 seconds')
    run(args)
