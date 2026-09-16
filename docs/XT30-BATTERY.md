# XT30 Battery Mod: implementation and recovery

The [battery hardware guide](../xt30-battery/docs/HARDWARE-SETUP.md) covers the
tested Samsung high-discharge pack, 3S 25A balancing BMS and XT30 connection,
with assembly photographs and component references.

## One installation script

[scripts/xt30_battery.py](../xt30-battery/scripts/xt30_battery.py) is generated
from readable files under [src](../xt30-battery/src/README.md). Its uncompressed
JSON bundle is encoded as Base64 and checked with SHA-256. It contains all nine
required bundled files, including our own native filter encoded in Python, and needs no optional compression module. It makes no
downloads and needs no ADB. The temporary controller runs separately from Lab;
the installed runtime is independent of the extracted bundle.

The script publishes estimated battery data through the robot's normal app
telemetry path and announces the battery component. The RoboMaster app itself
is not modified. The same script filters only chassis warnings #5
(`0300C205`, battery information unavailable) and #9 (`0300C209`,
authentication failed) from the copy sent to the app. Electrical alarms
and internal diagnostics remain intact. The filter has passed offline
ARM emulation, but has not been validated on the robot. See
[the native implementation](../xt30-battery/src/WARNING_FILTER.md).

## Persistent controller settings

Before configuration, the estimate is stopped and its native reader references
are independently verified. Maintenance transactions briefly pause HDVT to use
the existing controller UART route. A separate pipe watchdog resumes the same
HDVT process on caller exit or after ten seconds; each native CLI request is
bounded to five seconds. A temporary route-table bind mount is removed afterward.
The script sends no motion command.

| Ordinal | Verified name | INSTALL | UNINSTALL |
|---|---|---|---|
| 7 | `sa_bat_capcity_check_enable` | 0 | 1 |
| 8 | `sa_bat_auth_check_enable` | 0 | 1 |
| 9 | `sa_roll_over_check_enable` | 1, retained | 1, retained |
| 10 | `sa_bat_auth_check_faile_test` | 0, retained | 0, retained |

The descriptor names are checked through E1; E2 reads the complete four-field
state; E3 writes only changed fields 7/8. Known pre-states are stock `1/1/1/0`,
XT30 `0/0/1/0`, and the auth-only `1/0/1/0` migration state. Other
states are refused. Failed write/readback attempts trigger a bounded attempt
to restore the pre-state. Any unverified rollback is reported as an error.
These parameter values survive reboot; this is not a firmware flash.

`DISABLE` leaves the controller settings intact. `UNINSTALL` deliberately
restores stock `1/1/1/0`, verifies it, then removes the estimate's files. It
does not merely restore whatever bypass state existed before this release.
If parameter recovery or native RAM restoration fails, the files remain for
another recovery attempt and success is not reported.

## Battery runtime and automatic startup

The worker reads pack voltage from the supported HDVT process.
The worker validates executable hashes, process identities, mappings and
expected reader literals. A watchdog redirects two readers to verified shadow
storage and periodically publishes the filtered estimate. The incoming cache
and receive-handler reference remain original. No on-disk executable is patched.

The worker also sends guarded common `00/F1` reports to the local broker.
Presence requires the supported system service, chassis presence, an empty
battery-specific diagnostic list and fresh variation in the original voltage.
The native report also refreshes chassis presence; it is not a display-only
flag. The worker refuses unexpected battery diagnostics instead of treating
them as ordinary voltage samples.

Installed files live under `/data/s1-battery-estimator/`:
`boot.py`, `worker.py`, `telemetry.py`, `warning_filter.py`,
`warning_hook_blob.py`, `manifest.json`, and `enabled`.
The additional startup file is
`/data/python_files/lib/python3.6/site-packages/s1_battery_autostart.pth`.
No stock startup script is replaced.

The hook matches only the exact root Lab service command launched by init.
Its detached helper briefly requests battery telemetry at 10 Hz, removes its
own subscription, frees the Lab socket and waits for ten continuous seconds
of valid changing voltage. It then starts the estimator once for that boot.

A worker run lasts at most 24 hours. Faults and service restarts do not cause
unlimited automatic retries. The worker restores native readers on normal
exit, parent death or a two-second heartbeat timeout. Software presence expires
on the native timeout after reports stop. Removing a subscription does not
undo the promoted upstream topic frequency; reboot clears that volatile setting.

The warning filter intercepts the exact supported system-service send import
in RAM. It copies and validates app-bound diagnostic rosters, removing only
the two selected codes. A native lease expires within three seconds without
watchdog renewal and then passes through the original warnings. Publishing
or restoring the import briefly pauses service threads with a separate
one-second rescue process. The robot must be stationary for these operations.
No firmware file is changed. Dormant code remains mapped until reboot to
protect in-flight calls; restoring the import and clearing its lease stops
suppression without erasing that code. DISABLE/UNINSTALL independently
verify restoration and can recover a matching expired orphan hook.

To update an older installed bundle, run the same new Lab script with
`MODE = 'UNINSTALL'`, then `MODE = 'INSTALL'`. Reboot alone does not
undo enabled automatic startup or persistent XT30 controller settings.

## Removal boundary

The manager validates named files against its manifest, refuses symlinks and
unexpected files, stops its owned process using PID/start-time/command checks,
and independently checks native reader and warning-import restoration. It does not recursively
delete unknown content. Fresh-install write or hook-publication failures roll
back the files created by that attempt. Sudden power loss may leave a partial
install, which is refused rather than guessed at.

After `UNINSTALL complete`, persistent controller gates are stock and the added
startup files are gone. Reboot once to clear volatile telemetry setup, unused
shadow RAM, dormant filter code, logs and locks. Until an error is resolved, retain the complete
Lab script: it is the management and recovery entry point.

## Validation boundary

Offline checks cover protocol parsing, parameter guards and rollback,
installation/removal failures, bundle integrity, restricted Lab builtins,
Python 3.6 syntax, Lab's loop checkpoint insertion and enclosing indentation,
and the estimator/watchdog logic. Launcher tests execute the preprocessed
script with a mocked controller process and reject imports of `zlib`, `bz2`
and `lzma` in all four modes. This covers the observed missing-`zlib` failure;
it does not establish a successful installation on the robot. Run them using the
[source instructions](../xt30-battery/src/README.md).

Lab scans physical lines for loop keywords before compiling. An inline
generator in a condition can receive a checkpoint at the wrong indentation,
causing an `IndentationError` before the launcher runs. Keep the embedded
file-name validation as an explicit loop. The regression check reproduces
this failure and verifies the generated launcher's extraction and cleanup
after preprocessing.

The existing 63 repository tests and 13 new native/runtime tests pass.
The actual bundled ARM code was emulated across all 65,536 diagnostic
words and all 65,536 module IDs, plus malformed rosters, lease failures,
ABI preservation and recovery failures. These tests do not verify the
target kernel instruction cache or actual app display. Retaining electrical
alarm codes does not supply absent current, temperature or cell measurements.

The complete Lab install/uninstall flow still requires hardware acceptance.
Record #5/#9 before activation, absent during filtering, and restored after
DISABLE; also check original internal messages, forced worker loss,
reconnect, reboot and UNINSTALL.
App/platform coverage and calibration under real battery loads are incomplete.
Cell protection and regeneration must be validated independently of these
software tests. See [Compatibility](FIRMWARE-COMPATIBILITY.md) and
[Battery power and BMS](BATTERY-POWER.md).
