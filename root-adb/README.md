# Root ADB Access

This script opens a temporary root ADB connection to the RoboMaster S1 over
Wi-Fi. It is intended for owner maintenance and diagnostics when a USB ADB
cable is unavailable.

The script calls the robot's stock `/system/bin/adb_en.sh`, selects TCP port
`5555`, restarts `adbd`, and verifies that the daemon is running as root. It
does not install an executable, modify a partition, or persist across a reboot.

## Security boundary

While enabled, another device on the same network may be able to obtain an
unauthenticated root shell on the robot. Use the robot's direct-mode Wi-Fi,
avoid shared networks, do not expose port 5555 through a router, and reboot the
robot immediately after maintenance.

Root access can damage firmware, expose identifiers and calibration data, or
make the robot unsafe. The product only opens the connection; commands entered
through that connection are outside its safety guarantees.

## Compatibility

The maintained baseline is robot package `00.06.0515`, whose Android system
contains the stock ADB enable script and reports target
`full_xw607_dz_ap0002_v4`. Other packages are unsupported until the same
volatile behavior has been verified.

## Enable

1. Connect the PC and robot using the robot's direct-mode Wi-Fi.
2. Open the RoboMaster app's Lab Python editor.
3. Paste the complete
   [`scripts/enable_root_adb.py`](scripts/enable_root_adb.py) file and run it.
4. Copy the printed `adb connect` command to a PC with Android platform tools.
5. Confirm the target and privilege level:

```text
adb devices -l
adb shell id
```

Proceed only if exactly the expected robot is listed and `id` reports user
`root`. If multiple ADB targets are attached, always select the robot explicitly
with `adb -s <address:port> ...`.

## Close and recover

Finish the host connection with:

```text
adb disconnect <address:port>
```

Disconnecting the PC does not close the listener. Fully reboot the robot, then
verify that `adb connect <address:port>` no longer succeeds. A reboot is also
the recovery action after any partial or failed script run.

Never enable this product during a firmware update or while the robot is
capable of unexpected motion. Do not publish ADB logs without checking them for
serial numbers, network details, account identifiers, and calibration data.
