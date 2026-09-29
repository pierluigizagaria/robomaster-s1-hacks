# RoboMaster S1 - enable volatile root ADB over Wi-Fi
# ===================================================
# Run with: s1-lab.cmd run root-adb/scripts/enable_root_adb.py
# This executes on the robot through S1 Lab, not in the PC's Python runtime.
#
# This calls the robot's stock adb_en.sh, switches adbd to TCP port 5555, and
# prints the address to use from a PC.  It writes no partition or firmware.
# A manual full power cycle closes the temporary TCP listener.
#
# SECURITY: while the robot remains powered, another device on the same network
# may be able to open an unauthenticated root shell.  Prefer direct-mode Wi-Fi,
# disconnect shared networks, and manually power-cycle after maintenance.
# Keep the S1 stationary and the gimbal clear at Lab start and exit.

import rm_define

# The stock Lab exposes the host module loader through rm_define.
process_api = rm_define.__dict__['__builtins__']['__import__'](
    'sub' + 'process', globals(), locals(), [], 0)
ADB_TCP_PORT = '5555'
ADB_ENABLE = '/system/bin/adb_en.sh'
BUSYBOX = '/system/xbin/busybox'


def run(command, optional=False):
    job = process_api.Popen(
        ['/system/bin/sh', '-c', command],
        stdout=process_api.PIPE,
        stderr=process_api.STDOUT)
    output = job.communicate()[0].decode('utf-8', 'replace').strip()
    if job.returncode != 0:
        if optional:
            return ''
        raise Exception(command + ' failed: ' + output[-400:])
    return output


def find_addresses(ifconfig_output):
    addresses = []
    for line in ifconfig_output.splitlines():
        fields = line.partition('inet addr:')[2].split()
        if fields:
            address = fields[0]
            if address != '0.0.0.0' and not address.startswith('127.') and address not in addresses:
                addresses.append(address)
    return addresses


def adbd_runs_as_root():
    # Android init restarts asynchronously. ps may truncate the process name.
    pids = run(BUSYBOX + ' pidof adbd || true').split()
    for pid in pids:
        if not pid.isdigit():
            continue
        status = run(BUSYBOX + ' cat /proc/' + pid + '/status 2>/dev/null || true')
        rows = {}
        for line in status.splitlines():
            key, separator, value = line.partition(':')
            rows[key] = value.split()
        if rows.get('Name') == ['adbd'] and rows.get('Uid') == ['0', '0', '0', '0']:
            return True
    return False


def wait_for_root():
    for attempt in range(10):
        if adbd_runs_as_root():
            return
        if attempt < 9:
            run(BUSYBOX + ' sleep 1')
    raise Exception('Root adbd process not confirmed within 10 checks')


def start():
    print('Enabling temporary root ADB; use isolated or direct robot Wi-Fi.')
    run('test -f ' + ADB_ENABLE)
    run('/system/bin/sh ' + ADB_ENABLE)
    run('setprop service.adb.tcp.port ' + ADB_TCP_PORT)
    run('setprop ctl.restart adbd')
    port = run('getprop service.adb.tcp.port')
    if port != ADB_TCP_PORT:
        raise Exception('Unexpected ADB TCP port: ' + port)
    wait_for_root()

    print('S1_ADB_READY port=' + port + ' root=true volatile=true')
    addresses = find_addresses(run(BUSYBOX + ' ifconfig', optional=True))
    for address in addresses:
        endpoint = address + ':' + port
        print('  adb connect ' + endpoint)
        print('  adb -s ' + endpoint + ' shell id')
        print('  adb -s ' + endpoint + ' shell getprop ro.product.model')
    if not addresses:
        print('No address was read. Use the known S1 address; direct Wi-Fi defaults to 192.168.2.1.')
    print('Use only the identified S1 endpoint; expect uid=0(root) and model L1860.')
    print('If using a custom ADB server port, add the same -P PORT to each command.')
    print('Manually POWER-CYCLE THE ROBOT when maintenance is complete.')
    print('A software reboot is not a substitute for a full power cycle.')
