# Safety

Disabling the battery checks removes protections that the robot normally
expects. Treat the procedure as a controlled laboratory modification.

**A lithium battery connected for the XT30 Battery Mod must use an independent BMS.**
It must protect each series cell/group against voltage, current and temperature
faults while the robot or script is absent or malfunctioning. The complete pack
also needs suitable balancing, wiring, fusing and a validated regeneration path.
See [Battery power and BMS](BATTERY-POWER.md) before choosing or connecting a pack.
The voltage estimate neither provides those protections nor stops motion at
low charge. A plausible percentage is not evidence that the cells are safe.

## First motion test

- Put the chassis on a stable stand with all four wheels clear of the bench.
- Remove or disable the gimbal, blaster, and other actuators where practical.
- Use the lowest possible command speed and keep a physical power disconnect
  within reach.
- Restore the checks immediately if readback is incomplete, telemetry is
  implausible, or the robot resets.

## Power

- Never exceed 12.6 V at the robot power rail, including tolerance, ripple,
  turn-on overshoot, and regenerative transients.
- Verify XT30 polarity with a meter before connection. Disconnect all power
  before soldering or changing wiring; insulate exposed conductors.
- Do not route traction current through a breadboard, small signal lead or
  logic board. Match cells, BMS, cables, connectors and fuse to measured loads.
- The 12.6 V project ceiling includes transients; the source guard in software
  does not enforce that electrical limit.
- A standard one-quadrant bench supply can source current but cannot safely sink
  regenerative energy. Do not use it for driving, gimbal motion, or braking.
- Use appropriately rated conductors, a fuse close to the source, current
  limiting, and an emergency disconnect.

## Battery and charging

- Do not open, puncture, bridge, recell, or bypass the FETs/BMS of a lithium
  pack unless the work is performed by a qualified battery professional.
- Do not charge an aftermarket pack with the DJI `E1C28` charger without
  explicit manufacturer approval for the exact model.
- Do not connect a supply and a smart battery in parallel without a designed
  power-sharing system that handles backfeed and reverse current.
- Quarantine a pack after swelling, leakage, impact, odor, abnormal heat, or
  enclosure damage, and follow local disposal rules.

## Battery software and firmware

- No battery data-bus connection is needed for the XT30 Battery Mod.
- Do not flash the robot or accept firmware updates from an unstable supply.
- Treat physical flash dumps as sensitive because they may contain device
  identifiers, calibration data or secrets.

`INSTALL` selects controller state `0/0/1/0`: the capacity and authentication
motor gates are disabled, while the roll-over check remains enabled. The
external power system must provide cell-level voltage/current/temperature
protection independently. The estimate uses smoothing and can lag a real
voltage drop; source faults may return the display to 0% without stopping motion.

`DISABLE` stops the estimate but retains those controller settings.
`UNINSTALL` restores stock state `1/1/1/0` and removes the estimate. Power-cycle
once after successful removal; a working original smart battery is then required
for normal use. Reboot alone does not undo the persistent bypass settings.
States with the roll-over check disabled are refused by this product.

## Root ADB

- Root ADB over TCP may allow any device on the same network segment to control
  the robot without authentication. Use only direct-mode or an isolated Wi-Fi
  network; never forward port 5555 through a router.
- Keep the chassis unable to move while using a root shell. A mistyped command
  can stop safety services, damage persistent data, or expose calibration and
  identity material.
- Fully reboot the robot immediately after maintenance. Disconnecting the host
  does not close the listener.
- Never enable root ADB during an update, and do not publish raw logs or dumps
  before removing device identifiers, network data, and credentials.

## Windows application patch

- Close RoboMaster before status-changing actions and run the shell with the
  permissions required by its installation directory.
- Apply the patch only when the exact original assembly hash and every expected
  byte match. Never force it onto an updated or partially modified assembly.
- Keep the validated original backup until the application has been restored or
  intentionally uninstalled.
- Restore the original assembly before accepting a vendor update or performing
  application repair.
- Logs and application data may contain account identifiers or credentials; do
  not publish them with an issue report.
