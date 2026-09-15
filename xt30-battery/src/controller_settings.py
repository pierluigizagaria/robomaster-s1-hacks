"""Guarded XT30/stock parameter transition; Python 3.6, no motion or flash.

Uses the previously verified E1/E2/E3 interface. Only ordinals 7 and 8 may be
written. A separate pipe watchdog resumes HDVT if the caller exits or stalls.
The estimator must be stopped before using this maintenance interface.
"""
import json
import os
import select
import signal
import subprocess
import tempfile
from contextlib import contextmanager

import worker

MB = '/system/bin/dji_mb_ctrl'
STOCK_JSON = '/system/etc/dji.json'
NAMES = {7: 'sa_bat_capcity_check_enable', 8: 'sa_bat_auth_check_enable',
         9: 'sa_roll_over_check_enable', 10: 'sa_bat_auth_check_faile_test'}
XT30 = {7: 0, 8: 0, 9: 1, 10: 0}
STOCK = {7: 1, 8: 1, 9: 1, 10: 0}
LEGACY = {7: 1, 8: 0, 9: 1, 10: 0}
READ_PAYLOAD = '000000000700080009000a00'
ROUTE = {'mb_route_table': {'u_pc5': {'host': 'pc', 'index': 5,
    '1': {'status': 1, 'target': 'flight', 'index': 6, 'channel': 'uart',
          'distance': 0, 'protocol': 'v1', 'uart': {'interface': '/dev/ttyS3',
          'baudrate': 921600, 'parity': 0, 'stopbit': 0, 'wordlen': 8}}}}}


def parse_response(output):
    text = output.decode('latin1')
    if 'Resp message' not in text:
        raise RuntimeError('no DUSS parameter response')
    values = []
    for line in text.rsplit('Resp message', 1)[1].splitlines():
        parts = line.strip().split()
        if parts and all(len(part) == 2 for part in parts):
            try:
                values.extend(int(part, 16) for part in parts)
            except ValueError:
                raise RuntimeError('malformed DUSS parameter response')
    if not values:
        raise RuntimeError('empty DUSS parameter response')
    return values


def decode_values(raw):
    if len(raw) != 16 or raw[:4] != [0, 0, 0, 0]:
        raise RuntimeError('invalid E2 response')
    values = {}
    for offset in range(4, 16, 3):
        ordinal = raw[offset] | raw[offset + 1] << 8
        if ordinal in values:
            raise RuntimeError('duplicate E2 ordinal')
        values[ordinal] = raw[offset + 2]
    if set(values) != set(NAMES):
        raise RuntimeError('unexpected E2 ordinal list')
    return values


def make_write_payload(before, wanted):
    if before not in (XT30, STOCK, LEGACY) or wanted not in (XT30, STOCK, LEGACY):
        raise RuntimeError('unexpected pre-state; refusing to write any parameter')
    payload = '00000000'
    for ordinal in (7, 8):
        if before[ordinal] != wanted[ordinal]:
            payload += '%02x00%02x' % (ordinal, wanted[ordinal])
    return payload


@contextmanager
def paused_bridge(pid, started):
    if worker.identity(pid) != started:
        raise RuntimeError('HDVT process changed before parameter transaction')
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(write_fd)
        os.setsid()
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        try:
            # EOF means the parent exited. The hard bound also covers a stall.
            select.select([read_fd], [], [], 10)
            if worker.identity(pid) == started:
                os.kill(pid, signal.SIGCONT)
        finally:
            os._exit(0)
    os.close(read_fd)
    try:
        os.kill(pid, signal.SIGSTOP)
        yield
    finally:
        try:
            if worker.identity(pid) == started:
                os.kill(pid, signal.SIGCONT)
        finally:
            os.close(write_fd)
            os.waitpid(child, 0)


class Session:
    def __init__(self, pid, started):
        self.pid, self.started = pid, started
        self.sequence = 100

    def transaction(self, command, payload):
        self.sequence += 1
        args = [MB, '-S', 'probe_svc', '-R', 'u_pc5', '-g', '3', '-t', '6',
                '-w', '2', '-s', '3', '-q', str(self.sequence), '-c', command, payload]
        with paused_bridge(self.pid, self.started):
            result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    timeout=5, close_fds=True)
        if result.returncode:
            raise RuntimeError('DUSS parameter transaction failed: ' + command)
        return parse_response(result.stdout)

    def verify_descriptors(self):
        for ordinal in (7, 8, 9, 10):
            raw = self.transaction('e1', '0000%02x000000' % ordinal)
            if len(raw) < 23 or raw[:4] != [0, 0, 0, 0]:
                raise RuntimeError('invalid E1 response')
            name = bytes(raw[22:]).split(b'\0', 1)[0].decode('ascii')
            if (raw[4] | raw[5] << 8) != ordinal or name != NAMES[ordinal]:
                raise RuntimeError('parameter descriptor mismatch for %d' % ordinal)

    def read(self):
        return decode_values(self.transaction('e2', READ_PAYLOAD))

    def change(self, wanted):
        self.verify_descriptors()
        before = self.read()
        payload = make_write_payload(before, wanted)
        if before == wanted:
            print('Requested controller state already active; no parameter written.', flush=True)
            return
        try:
            self.transaction('e3', payload)
            if self.read() != wanted:
                raise RuntimeError('parameter write readback mismatch')
        except Exception as exc:
            # Delivery may have succeeded even when the acknowledgement failed.
            # Write both owned values back; never write roll-over or test flags.
            rollback = '00000000' + ''.join('%02x00%02x' % (n, before[n]) for n in (7, 8))
            try:
                self.transaction('e3', rollback)
                if self.read() != before:
                    raise RuntimeError('rollback readback mismatch')
            except Exception as rollback_error:
                raise RuntimeError('parameter operation failed (%s); rollback unverified (%s)' %
                                   (exc, rollback_error))
            raise RuntimeError('parameter operation failed; previous state restored: ' + str(exc))


def set_mode(mode):
    if mode not in ('XT30', 'STOCK'):
        raise RuntimeError('controller mode must be XT30 or STOCK')
    pid = worker.find_process()
    started = worker.identity(pid)
    with open('/proc/%d/exe' % pid, 'rb') as stream:
        worker.validate_image(stream.read())
    with open(STOCK_JSON, 'rb') as stream:
        routes = json.load(stream)
    if not isinstance(routes, dict) or 'probe_svc' in routes:
        raise RuntimeError('unexpected or already modified route table; reboot before retrying')
    folder = tempfile.mkdtemp(prefix='s1-xt30-params-', dir='/tmp')
    path = folder + '/routes.json'
    mounted = False
    try:
        routes['probe_svc'] = ROUTE
        with open(path, 'w') as stream:
            json.dump(routes, stream)
        subprocess.run(['/system/bin/mount', '-o', 'bind', path, STOCK_JSON],
                       check=True, timeout=3, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        mounted = True
        Session(pid, started).change(XT30 if mode == 'XT30' else STOCK)
        print('Controller state 7/8/9/10 = ' + ('0/0/1/0' if mode == 'XT30' else '1/1/1/0'), flush=True)
    finally:
        if mounted:
            try:
                subprocess.run(['/system/bin/umount', STOCK_JSON], check=True, timeout=3,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            except Exception:
                raise RuntimeError('temporary route could not be unmounted; reboot before retrying')
        if os.path.exists(path):
            os.unlink(path)
        os.rmdir(folder)
