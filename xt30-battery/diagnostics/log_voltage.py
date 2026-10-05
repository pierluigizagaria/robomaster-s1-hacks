#!/usr/bin/env python3
"""Read-only 4 Hz voltage trace for the supported RoboMaster S1.

Run on the robot as root with its installed XT30 Battery Mod. The CSV lives in
/tmp and must be copied off the robot before rebooting. This does not alter
controller settings, battery telemetry, or motion.
"""
import argparse
import os
import struct
import sys
import time

sys.dont_write_bytecode = True

ROOT = '/data/s1-battery-estimator'
OUTPUT = '/tmp/s1-battery-voltage.csv'
LOG = '/tmp/s1-battery-voltage-monitor.log'
PERIOD = 0.25


def trace(duration):
    sys.path.insert(0, ROOT)
    import worker

    pid = worker.find_process()
    identity = worker.identity(pid)
    with open('/proc/%d/exe' % pid, 'rb') as stream:
        worker.validate_image(stream.read())
    with open('/proc/%d/maps' % pid) as stream:
        base = worker.base_from_maps(stream.read())
    fd = os.open('/proc/%d/mem' % pid, os.O_RDONLY)
    try:
        start = time.monotonic()
        sample_number = 0
        # Preserve an earlier trace until it is explicitly copied or removed.
        with open(OUTPUT, 'x', buffering=1) as output:
            output.write('elapsed_s,voltage_mv\n')
            while True:
                now = time.monotonic()
                if now - start >= duration:
                    break
                if worker.identity(pid) != identity:
                    raise RuntimeError('HDVT process changed during trace')
                record = os.pread(fd, 10, base + worker.CACHE)
                if len(record) != 10 or record[2:9] != bytes(7):
                    raise RuntimeError('native battery source changed during trace')
                voltage = struct.unpack_from('<H', record)[0]
                output.write('%.3f,%d\n' % (now - start, voltage))
                sample_number += 1
                pause = start + sample_number * PERIOD - time.monotonic()
                if pause > 0:
                    time.sleep(pause)
        print('Captured %d voltage samples in %s' % (sample_number, OUTPUT), flush=True)
    finally:
        os.close(fd)


def detach(duration):
    pid = os.fork()
    if pid:
        print('Voltage logger PID: %d' % pid, flush=True)
        return
    os.setsid()
    null_fd = os.open('/dev/null', os.O_RDONLY)
    log_fd = os.open(LOG, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    os.dup2(null_fd, 0)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(null_fd)
    os.close(log_fd)
    try:
        trace(duration)
    except BaseException as exc:
        print('Voltage logger error: %s' % exc, flush=True)
        os._exit(1)
    os._exit(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=int, default=600, help='capture seconds (1 to 3600)')
    parser.add_argument('--detach', action='store_true', help='keep recording after ADB exits')
    args = parser.parse_args()
    if not 1 <= args.duration <= 3600:
        parser.error('duration must be 1 to 3600 seconds')
    if os.geteuid() != 0:
        parser.error('root shell required')
    if args.detach:
        detach(args.duration)
    else:
        trace(args.duration)


if __name__ == '__main__':
    main()
