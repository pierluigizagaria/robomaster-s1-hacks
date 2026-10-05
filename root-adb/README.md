# Root ADB Access

Open a temporary root ADB connection to the RoboMaster S1 over Wi-Fi for
maintenance and diagnostics. On Windows with Python 3.10+, use the
[S1 Lab CLI](../lab-cli/README.md) to do this without opening the original GUI
or already having ADB. There is one maintained program:
[scripts/enable_root_adb.py](scripts/enable_root_adb.py). It belongs to this
hack; the standalone S1 Lab client runs it by file path.

The program calls the robot's stock `/system/bin/adb_en.sh`, selects TCP port
`5555`, restarts `adbd`, and verifies that the daemon runs as root. It does not
flash firmware, modify a partition image, or install an ADB startup hook.
The Lab route stores normal project files on the robot; the ADB listener itself
is temporary.

The former duplicate script and generator have been removed. Edit this program
directly when maintaining it. One command helper reports setup errors; only
optional address readback may fail without aborting confirmed root access.
Readiness checks retry up to ten times, validating `Name: adbd` and all four
root UIDs in `/proc/PID/status`, rather than the truncated `ps` display. Setup
failures propagate, and the printed PC commands select the S1 serial explicitly.
The daemon/port check does not prove that a PC can complete the ADB handshake.
Output contains one setup message, the `S1_ADB_READY` result and connection
instructions. Address readback tolerates whitespace, omits loopback/unspecified
addresses and prints each address once.

## Security boundary

While enabled, another device on the same network may be able to obtain an
unauthenticated root shell on the robot. Use direct-mode or isolated Wi-Fi,
never expose port 5555 through a router, and manually power-cycle the robot
when maintenance is complete.

Root commands can damage firmware, expose identifiers and calibration data,
or make the robot unsafe. This tool only opens the connection; arbitrary
commands entered through it are outside its safety guarantees. Keep the S1
stationary: the stock Lab framework can recenter its gimbal at start and exit.

## Compatibility

The original root-ADB baseline is robot package `00.06.0515`,
whose Android system contains the stock ADB enable script and reports target
`full_xw607_dz_ap0002_v4`. Other packages require the same volatile behavior to
be verified. The DLL-free CLI path was verified on an S1 reporting model `L1860` on
router Wi-Fi, with Scratch service `01.00.01.00`. Historical build readback was
`leadcore1860` / `eng.jenkins.20221027.033121`; the commercial robot package
version is not inferred from those values.

The maintenance program passed through the native Python transport:
`S1_ADB_READY`, Finished and exit code zero, followed by explicit ADB confirmation
of root identity and model `L1860`. The Lab returned to Ready, and the host's
existing ADB server port was preserved. That hardware evidence predates the
current cleanup of command handling and output. The revised script keeps the
same setup commands and order; offline tests cover their failures, incorrect
port readback, ten-check retry limits, process identity and unique endpoint
instructions. No additional hardware enable cycle is claimed for this revision.

See [Firmware compatibility](../docs/FIRMWARE-COMPATIBILITY.md) for the separate
baselines. A matching model alone does not prove a firmware revision.

## Enable from a terminal

From the repository root, with Python 3.10+ in PATH, the original GUI closed
and the PC on direct S1 Wi-Fi (no DJI installation or DLL needed):

```powershell
.\s1-lab.cmd status
.\s1-lab.cmd run root-adb/scripts/enable_root_adb.py --timeout 40
adb connect 192.168.2.1:5555
adb -s 192.168.2.1:5555 shell id
adb -s 192.168.2.1:5555 shell getprop ro.product.model
```

The CLI also runs from a copied `lab-cli` folder with its own launcher. It
automatically discovers an S1 on the same router network; use the selected
address in the ADB commands instead of the direct-mode example above. An
explicit `--host ADDRESS` bypasses discovery. See
[Standalone folder](../lab-cli/README.md#standalone-folder) for prerequisites
and hardware verification.

Check the Lab state first and leave an unrelated program alone. Reuse an
already working, identity-verified connection instead of enabling ADB again.
The tested target returned `uid=0(root) gid=0(root)` and `L1860`. Select the
S1 serial explicitly in every command, especially when a Quest or another ADB
device is attached. Preserve your configured ADB server port if it is not the
default, adding the same `-P PORT` consistently; do not kill a shared server.

CLI output is printed immediately in the terminal. Program output/results go
to stdout and progress/errors to stderr. Use normal pipes or shell redirection
when you want to save them; there are no automatic logs. See the
[CLI guide](../lab-cli/README.md) for router addresses, receipts and timeouts.

## Close and recover

Finish the host connection with:

```powershell
adb disconnect 192.168.2.1:5555
```

Disconnecting the PC does not close the listener. Manually perform a full
power cycle and then verify that `adb connect` no longer succeeds. Do not use
a software-only reboot as a generic recovery step: in an XT30 setup it can
restart the computer without restoring the motion controller. Agents must not
reboot autonomously to clear a failed Lab session; inspect the reported state
and use the documented owned-program teardown first.

Never enable ADB during a firmware update. Do not publish captures before
checking them for device identifiers, network details, account information
and calibration data.
