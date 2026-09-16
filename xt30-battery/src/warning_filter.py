"""Guarded RAM-only outgoing C205/C209 filter for one exact dji_sys image.

Python 3.6. No network, flash, original file writes or controller commands.
Native code remains dormant until process exit after restoring the import,
so an in-flight call never returns into unmapped/overwritten memory.
"""
from contextlib import contextmanager
import hashlib
import importlib.util
import os
import select
import signal
import struct
import time

EXE = '/system/bin/dji_sys'
SHA256 = 'fb0df0de6080231c83fc1f87584a5baa4f237040a0ad3f2ce3cf3ef1466a8181'
PAD = 0x574A4
PAD_END = 0x576E8
GOT = 0x58D60
MAGIC = b'S1WARN02'


def native():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'warning_hook_blob.py')
    spec = importlib.util.spec_from_file_location('s1_warning_blob', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if (hashlib.sha256(module.BLOB).hexdigest() != module.SHA256 or
            module.BLOB[:16] != bytes(16) or module.ENTRY != 17 or
            len(module.BLOB) > PAD_END - PAD):
        raise RuntimeError('invalid embedded warning hook')
    return module


def identity(pid):
    with open('/proc/%d/stat' % pid) as stream:
        return stream.read().rsplit(')', 1)[1].split()[19]


def mappings(pid):
    with open('/proc/%d/maps' % pid) as stream:
        rows = []
        for line in stream:
            p = line.split()
            a, b = [int(v, 16) for v in p[0].split('-')]
            rows.append((a, b, p[1], int(p[2], 16), p[5] if len(p) > 5 else ''))
        return rows


def symbol_value(blob, wanted):
    """Read a defined ELF32 dynamic function symbol without robot dependencies."""
    if blob[:7] != b'\x7fELF\x01\x01\x01':
        raise RuntimeError('expected little-endian ELF32 library')
    shoff = struct.unpack_from('<I', blob, 32)[0]
    size, count = struct.unpack_from('<HH', blob, 46)
    if size != 40 or shoff + size * count > len(blob):
        raise RuntimeError('invalid library section table')
    sections = [struct.unpack_from('<10I', blob, shoff + i * size) for i in range(count)]
    found = []
    for section in sections:
        if section[1] != 11:  # SHT_DYNSYM
            continue
        if section[9] != 16 or section[6] >= count:
            raise RuntimeError('invalid dynamic symbol table')
        strings = sections[section[6]]
        names = blob[strings[4]:strings[4] + strings[5]]
        for at in range(section[4], section[4] + section[5], 16):
            name, value, _, info, _, index = struct.unpack_from('<IIIBBH', blob, at)
            end = names.find(b'\0', name)
            if index and info & 15 == 2 and end >= name and names[name:end] == wanted:
                found.append(value)
    if len(found) != 1:
        raise RuntimeError('original duss_event_send export not uniquely identified')
    return found[0]


@contextmanager
def paused(pid, started):
    """Briefly stop all service threads; independent rescue resumes after death/stall."""
    if identity(pid) != started:
        raise RuntimeError('system service identity changed')
    with open('/proc/%d/status' % pid) as stream:
        status = stream.read()
    if '\nState:\tT' in status or '\nState:\tt' in status:
        raise RuntimeError('system service was already stopped')
    rd, wr = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(wr)
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        try:
            select.select([rd], [], [], 1)
            if identity(pid) == started:
                os.kill(pid, signal.SIGCONT)
        finally:
            os._exit(0)
    os.close(rd)
    try:
        os.kill(pid, signal.SIGSTOP)
        deadline = time.monotonic() + 0.3
        while True:
            tasks = os.listdir('/proc/%d/task' % pid)
            stopped = True
            for tid in tasks:
                try:
                    with open('/proc/%d/task/%s/stat' % (pid, tid)) as stream:
                        state = stream.read().rsplit(')', 1)[1].split()[0]
                    stopped = stopped and state in ('T', 't')
                except FileNotFoundError:
                    stopped = False
            if stopped and tasks == os.listdir('/proc/%d/task' % pid):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('could not quiesce system threads')
            time.sleep(0.005)
        if identity(pid) != started:
            raise RuntimeError('system service changed while pausing')
        yield
    finally:
        try:
            if identity(pid) == started:
                os.kill(pid, signal.SIGCONT)
        finally:
            os.close(wr)
            os.waitpid(child, 0)


class WarningFilter:
    def __init__(self, readonly=False):
        self.fd = None
        self.owned = False
        self.image = native()
        matches = []
        for item in os.listdir('/proc'):
            if item.isdigit():
                try:
                    if os.readlink('/proc/%s/exe' % item) == EXE:
                        matches.append(int(item))
                except OSError:
                    pass
        if len(matches) != 1:
            raise RuntimeError('expected exactly one dji_sys process')
        self.pid = matches[0]
        self.started = identity(self.pid)
        try:
            with open('/proc/%d/exe' % self.pid, 'rb') as stream:
                image = stream.read()
            if hashlib.sha256(image).hexdigest() != SHA256:
                raise RuntimeError('unsupported dji_sys image')
            if image[PAD:PAD_END] != bytes(PAD_END - PAD):
                raise RuntimeError('unexpected native padding')
            self.regions = mappings(self.pid)
            bases = [a for a, b, perms, offset, path in self.regions
                     if path == EXE and offset == 0 and perms == 'r-xp']
            if len(bases) != 1:
                raise RuntimeError('unexpected system mapping')
            self.base = bases[0]
            for rva, length, executable in [(PAD, PAD_END - PAD, True), (GOT, 4, False)]:
                if not any(a <= self.base + rva and self.base + rva + length <= b and
                           path == EXE and perms.endswith('p') and 'r' in perms and
                           (not executable or 'x' in perms)
                           for a, b, perms, offset, path in self.regions):
                    raise RuntimeError('unexpected hook memory region')
            self.fd = os.open('/proc/%d/mem' % self.pid, os.O_RDONLY if readonly else os.O_RDWR)
            self.hook = self.base + PAD + self.image.ENTRY
            padding = self.read(PAD, PAD_END - PAD)
            block = padding[:len(self.image.BLOB)]
            if padding[len(block):] != bytes(len(padding) - len(block)):
                raise RuntimeError('remaining system padding changed')
            current = self.pointer()
            if block == bytes(len(block)):
                self.original = current
                if current == self.hook:
                    raise RuntimeError('dangling warning hook')
                self.retained = False
            elif block[8:16] == MAGIC and block[16:] == self.image.BLOB[16:]:
                self.original = struct.unpack('<I', block[:4])[0]
                self.retained = True
                if current not in (self.original, self.hook):
                    raise RuntimeError('send import changed by another actor')
            else:
                raise RuntimeError('system padding already changed; reboot required')
            self.verify_original()
            self.check_identity()
        except BaseException:
            self.close()
            raise

    def check_identity(self):
        if identity(self.pid) != self.started:
            raise RuntimeError('dji_sys restarted')

    def verify_original(self):
        address = self.original & ~1
        candidates = [path for a, b, perm, off, path in self.regions
                      if a <= address < b and 'x' in perm and path.startswith('/system/lib/')]
        if len(candidates) != 1:
            raise RuntimeError('send import is unresolved or outside a stock library')
        path = candidates[0]
        bases = [a for a, b, perm, off, p in self.regions if p == path and off == 0]
        with open(path, 'rb') as stream:
            value = symbol_value(stream.read(), b'duss_event_send')
        if len(bases) != 1 or self.original != bases[0] + value:
            raise RuntimeError('send import does not match its native export')

    def read(self, rva, size):
        data = os.pread(self.fd, size, self.base + rva)
        if len(data) != size:
            raise RuntimeError('short system memory read')
        return data

    def write(self, rva, data):
        self.check_identity()
        if os.pwrite(self.fd, data, self.base + rva) != len(data) or self.read(rva, len(data)) != data:
            raise RuntimeError('system memory write/readback failed')

    def pointer(self):
        return struct.unpack('<I', self.read(GOT, 4))[0]

    def install(self):
        if self.pointer() != self.original:
            raise RuntimeError('warning filter already installed; disable it first')
        self.owned = True  # Retain recovery responsibility even on partial publication.
        if not self.retained:
            # Unreachable code is fully staged before publishing the pointer.
            # Linux ARM /proc/mem writes use copy_to_user_page cache maintenance.
            block = struct.pack('<II', self.original, 0) + MAGIC + self.image.BLOB[16:]
            self.write(PAD, block)
        self.write(PAD + 4, bytes(4))
        with paused(self.pid, self.started):
            if self.pointer() != self.original:
                raise RuntimeError('send import changed before installation')
            self.write(GOT, struct.pack('<I', self.hook))
        self.update()

    def update(self):
        self.check_identity()
        if self.pointer() != self.hook:
            raise RuntimeError('warning hook lost ownership')
        block = self.read(PAD, len(self.image.BLOB))
        if (block[:4] != struct.pack('<I', self.original) or block[8:16] != MAGIC or
                block[16:] != self.image.BLOB[16:]):
            raise RuntimeError('warning hook code or config changed')
        # No native clock/heartbeat means passthrough within at most three seconds.
        self.write(PAD + 4, struct.pack('<I', int(time.monotonic()) + 3))

    def status(self):
        self.check_identity()
        lease = struct.unpack('<I', self.read(PAD + 4, 4))[0] if self.retained or self.owned else 0
        left = lease - int(time.monotonic())
        return {'hook_installed': self.pointer() == self.hook,
                'filter_active': self.pointer() == self.hook and 0 < left <= 3,
                'suppressed': ['0300C205', '0300C209'], 'electrical_alarms_preserved': True}

    def restore(self):
        if not self.owned:
            return
        self.check_identity()
        self.write(PAD + 4, bytes(4))
        with paused(self.pid, self.started):
            current = self.pointer()
            if current == self.hook:
                self.write(GOT, struct.pack('<I', self.original))
            elif current != self.original:
                raise RuntimeError('send import changed; refusing overwrite')
        self.owned = False

    def verify_restored(self):
        self.check_identity()
        if self.pointer() != self.original:
            raise RuntimeError('native warning import is not restored')
        if self.retained and self.read(PAD + 4, 4) != bytes(4):
            raise RuntimeError('warning filter lease not cleared')

    def recover_expired(self):
        """Explicit DISABLE/UNINSTALL recovery only; never take over an active lease."""
        state = self.status()
        if state['filter_active']:
            raise RuntimeError('warning filter still has a live lease')
        if state['hook_installed']:
            self.owned = True
            self.restore()
        elif self.retained:
            self.write(PAD + 4, bytes(4))
        self.verify_restored()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
