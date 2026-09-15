# XT30 Battery Mod

Run the RoboMaster S1 from a protected external battery through XT30 and display
an estimated charge level in the **RoboMaster app battery indicator**.
The robot measures voltage internally. Installation, automatic startup and
removal use **one Python Lab script**. No external telemetry board, ADB,
firmware flash or app modification is required by this product.

> **An external lithium battery must have an independent BMS.** The estimate
> does not monitor individual cells, current or temperature and does not stop
> the robot at low charge. Installation disables the original capacity and
> authentication motor gates. Read [Battery power and BMS](../docs/BATTERY-POWER.md)
> and [Safety](../docs/SAFETY.md) before connecting a battery.

## Compatibility and validation

The robot runtime is restricted to exact native executable and stock-script
hashes. See [Compatibility](../docs/FIRMWARE-COMPATIBILITY.md). Unknown builds
and unsafe controller states are refused.

The runtime supports internal voltage estimation, native app telemetry and
startup after reboot. **The combined installer remains experimental:** its
end-to-end hardware acceptance test, app/platform coverage and real-battery
load calibration are not complete. The offline test suite does not validate
the safety of a connected battery or its power system.

## What you need

- The exact supported RoboMaster S1 build and its Python Lab editor.
- A suitable **3S lithium-ion/LiPo pack rated for 4.2 V maximum per cell**, with
  an independent, correctly configured BMS and cell balancing. Other chemistries
  and cell counts are outside the current estimate's scope.
- Correct polarity, insulated wiring and connectors rated for the measured
  continuous and peak current, a fuse near the source, and a physical disconnect.
- A power system designed for current returned by the motors during braking,
  including a full battery or a BMS disconnect. A BMS alone does not guarantee
  that the robot supply rail is protected from regeneration.
- A stable stand with all four wheels clear for installation, removal and the
  first motion checks. The stock Lab framework may initialize actuators.

There are no battery data-bus connections to add. The connected battery must
remain protected independently of the robot and this script.

## Install from Lab

1. Open [scripts/xt30_battery.py](scripts/xt30_battery.py) and copy the **whole
   file** into one Python program in the RoboMaster app's Lab editor.
2. Leave the line near the top as `MODE = 'INSTALL'` and run the program.
3. Wait for `INSTALL complete`. The script verifies the supported files and
   parameter names, sets the guarded XT30 state, installs the estimate and
   enables automatic startup. An existing matching installation is reused.
4. End the Lab program so the background helper can use its telemetry socket.
   Allow about 30 seconds for the percentage; startup can wait up to five minutes.
5. On later power cycles, connect the RoboMaster app normally. You do not need to
   run Lab or ADB again.

No other file needs to be copied to the robot and nothing is downloaded.

If Lab reports `No module named 'zlib'` or an `IndentationError` near the
embedded file-list check, replace the whole program with the current generated
script. It uses an uncompressed bundle and explicit validation loops. These
early launcher failures occur before it starts the installation controller.
The complete installation still requires end-to-end verification in Lab.

`INSTALL` can be run again after `DISABLE` or a fault. It stops the previous
estimate, rechecks the controller state and requests one new background run.
Matching installed files are reused. A different version must be removed
first; changed files are never silently overwritten.

## Control and reverse

Change only `MODE` and run the same complete script:

| MODE | Result |
|---|---|
| `INSTALL` | Set XT30 controller state, install/enable the estimate, start it in the background |
| `STATUS` | Show installation, automatic startup and current estimate/worker state |
| `DISABLE` | Stop the estimate and future startup; retain the files and XT30 controller settings |
| `UNINSTALL` | Stop the estimate, restore stock battery checks, remove its startup hook and files |

For a **complete reversal**, set `MODE = 'UNINSTALL'`, run it, wait for
`UNINSTALL complete`, and reboot once. The original smart battery checks are
active again; normal operation then requires a working original smart battery.
The reboot also clears temporary telemetry frequency settings, unused RAM
storage, logs and locks. This intentionally restores the documented stock
controller state, rather than leaving a pre-existing bypass enabled.

The Lab stop button does not disable the installed background process. A
reboot alone does not undo installation or the persistent controller settings.
`DISABLE` does not restore the motor gates; use `UNINSTALL` for that.

Removal checks the native battery readers are restored and verifies the stock
controller state before deleting recovery files. If a check fails, the script
reports an error and retains the installed files, normally with automatic
startup disabled. Do not treat an error message as a completed reversal.

## What the estimate means

The worker uses a piecewise 3S voltage curve, a 30-second median window and a
gradual filter. Lower percentages require repeated confirmation; upward
recovery is limited to roughly one percentage point per minute.

| Pack voltage | Approximate curve value before filtering |
|---|---|
| 10.35 V | 5% |
| 11.22 V | 20% |
| 11.46 V | 50% |
| 12.00 V | 80% |
| 12.30 V | 90% |
| 12.60 V | 100% |

The filters reduce brief load-induced changes but delay sustained changes too.
Repeated loads, temperature, aging and startup under load can bias the result. The displayed number is neither
remaining runtime nor a safe-discharge guarantee. **Never wait for 0% to decide
whether the battery is safe.**

## Expected limits and failures

- Battery information/authentication warnings such as #5 and #9 can remain.
  The script does not authenticate a smart battery or modify the app.
- A missing/frozen voltage source, unexpected native battery data, unsupported
  executable, worker fault or elapsed 24-hour run limit stops the override.
  The display can return to 0%; this does not restore the bypassed motor gates.
- Stock process restarts and faults do not cause unlimited restart attempts.
  Use `STATUS`, then explicit `INSTALL` if appropriate, or reboot.
- A source-reading guard is not an electrical cutoff. Independent cell-level
  protection remains mandatory even when the percentage looks plausible.

Implementation and source build details are in
[Battery XT30 internals](../docs/XT30-BATTERY.md). Building the script is a
**developer step only**; owners use the generated file linked above.
