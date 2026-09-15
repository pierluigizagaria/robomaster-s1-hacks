# RoboMaster S1 - enable volatile root ADB over Wi-Fi
# ===================================================
# Paste this entire file into the RoboMaster app Lab Python editor and run it.
#
# This calls the robot's stock adb_en.sh, switches adbd to TCP port 5555, and
# prints the address to use from a PC.  It writes no partition or firmware.
# A full robot reboot closes the TCP listener and restores the prior boot state.
#
# SECURITY: while the robot remains powered, another device on the same network
# may be able to open an unauthenticated root shell.  Prefer direct-mode Wi-Fi,
# disconnect shared networks, and reboot the robot as soon as maintenance ends.

ADB_TCP_PORT = 5555

import rm_define


def load_module(module_name):
    loader = rm_define.__dict__['__builtins__']['__import__']
    return loader(module_name, globals(), locals(), [], 0)


process_api = load_module('sub' + 'process')

ADB_ENABLE = '/system/bin/adb_en.sh'
BUSYBOX = '/system/xbin/busybox'


def run(command):
    job = process_api.Popen(
        ['/system/bin/sh', '-c', command],
        stdout=process_api.PIPE,
        stderr=process_api.STDOUT)
    output = job.communicate()[0]
    try:
        text = output.decode('utf-8', 'replace')
    except Exception:
        text = str(output)
    return job.returncode, text.strip()


def run_checked(command, label):
    status, output = run(command)
    if status != 0:
        raise Exception(label + ' failed: ' + output[-400:])
    return output


def find_addresses(ifconfig_output):
    addresses = []
    for line in ifconfig_output.splitlines():
        marker = 'inet addr:'
        if marker in line:
            address = line.split(marker, 1)[1].split(' ', 1)[0].strip()
            if address and not address.startswith('127.'):
                addresses.append(address)
    return addresses


def adbd_runs_as_root(process_output):
    for line in process_output.splitlines():
        fields = line.split()
        if fields and 'adbd' in fields[-1] and 'root' in fields[:2]:
            return True
    return False


def main():
    print('--- S1 volatile root ADB over Wi-Fi ---')
    print('SECURITY: use only on an isolated or direct robot network.')

    run_checked('test -f ' + ADB_ENABLE, 'stock adb_en.sh check')

    print('1/4 enabling the stock root ADB service')
    run_checked('/system/bin/sh ' + ADB_ENABLE, 'adb_en.sh')

    print('2/4 selecting TCP port ' + str(ADB_TCP_PORT))
    run_checked(
        'setprop service.adb.tcp.port ' + str(ADB_TCP_PORT),
        'ADB TCP property')

    print('3/4 restarting adbd')
    run_checked('setprop ctl.restart adbd', 'adbd restart')
    run_checked(BUSYBOX + ' sleep 2', 'restart wait')

    print('4/4 verifying volatile state')
    port = run_checked(
        'getprop service.adb.tcp.port', 'ADB TCP property readback')
    if port != str(ADB_TCP_PORT):
        raise Exception('unexpected ADB TCP port: ' + port)

    processes = run_checked(BUSYBOX + ' ps', 'process list')
    if not adbd_runs_as_root(processes):
        raise Exception('adbd root process not confirmed; reboot before retrying')

    addresses = find_addresses(
        run_checked(BUSYBOX + ' ifconfig', 'network address readback'))
    if not addresses:
        addresses = ['192.168.2.1']
        print('No address was parsed; showing the direct-mode default.')

    print('DONE: adbd is running as root on TCP port ' + port + '.')
    for address in addresses:
        print('  adb connect ' + address + ':' + port)
    print('Verify from the PC with: adb shell id')
    print('REBOOT THE ROBOT when maintenance is complete.')


try:
    main()
except Exception as exc:
    print('ERROR: ' + str(exc))
    print('Reboot the robot to clear any partial volatile ADB state.')
