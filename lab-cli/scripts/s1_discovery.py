"""Passive S1 LAN announcements, matching the Quest client's discovery rules."""
from __future__ import annotations

import ipaddress
import socket
import time

DISCOVERY_PORT = 45678
DIRECT_HOST = '192.168.2.1'
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(value) for value in
                         ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))


def private_host(value):
    address = ipaddress.IPv4Address(value)
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise ValueError('An explicit private robot IPv4 address is required')
    return str(address)


def decode_announcement(packet, sender):
    """Return only the endpoint; device and pairing identifiers stay private."""
    if not 24 <= len(packet) <= 4096:
        return None
    try:
        host = private_host(sender)
    except (ValueError, TypeError):
        return None
    key = 7
    decoded = bytearray()
    for byte in packet:
        decoded.append(byte ^ key)
        key = ((key + 7) ^ 178) & 255
    if decoded[:2] != b'\x5a\x5b':
        return None
    if decoded[6:10] != ipaddress.IPv4Address(host).packed:
        return None
    return host


class Discovery:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(('0.0.0.0', DISCOVERY_PORT))
            self.socket.setblocking(False)
        except BaseException:
            self.socket.close()
            raise

    def poll(self):
        hosts = set()
        for _ in range(64):
            try:
                packet, peer = self.socket.recvfrom(4097)
            except BlockingIOError:
                break
            host = decode_announcement(packet, peer[0])
            if host:
                hosts.add(host)
        return hosts

    def close(self):
        self.socket.close()


def discover(timeout=5):
    listener = Discovery()
    hosts = set()
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            hosts.update(listener.poll())
            time.sleep(.05)
        return sorted(hosts, key=ipaddress.IPv4Address)
    finally:
        listener.close()
