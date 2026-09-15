# External battery power and BMS requirements

## Mandatory independent protection

**Do not connect an unprotected lithium pack to use the XT30 Battery Mod.** Use a
properly assembled 3S pack with a BMS that works without the RoboMaster, its
application, or this script. Do not bypass the BMS discharge terminals or FETs.
A balance lead, balance charger, voltage alarm or percentage display alone
is not discharge protection.

The BMS must monitor each series cell/group and control charge and discharge
when limits are exceeded. Required functions include cell overvoltage and
undervoltage, charge/discharge overcurrent, short-circuit protection, and
appropriate cell temperature limits. These are distinct protection functions;
check the complete pack/BMS specification. [TI battery protection overview](https://www.ti.com/product-category/battery-management-ics/battery-protectors/overview.html)
and [TI protection example](https://www.ti.com/product/BQ77307).

The complete pack needs a suitable balancing arrangement. A normal total pack
voltage can hide one cell below its safe limit and another above it. The robot
reads only pack voltage and cannot detect that condition.

## Choose and verify the whole power system

| Requirement | What must be established |
|---|---|
| Chemistry and cell count | 3S cells specified for a 4.2 V charge ceiling per cell; BMS and charger match the actual cell datasheet |
| Voltage | This project's operating ceiling is 12.6 V at the robot rail, including overshoot and returned motor energy; it is not a measured absolute maximum rating |
| Current | Cell, BMS, fuse, wire and connector ratings cover measured continuous load and startup/stall/braking peaks |
| Temperature | Sensors, trip limits and permitted charging temperature match the cells and installation |
| Wiring | Correct measured XT30 polarity, insulated connections, strain relief and protection from abrasion/short circuits |
| Fuse and disconnect | A suitably rated fuse close to the source and a reachable physical disconnect |
| Regeneration | The power system handles returned current even when the pack is full or its BMS opens |

This project has not characterized the complete current/thermal envelope and
therefore does **not** prescribe a universal BMS amp rating, fuse value, wire
gauge or cutoff threshold. A connector name or a marketplace “A” label is not
a design validation. Use traceable specifications and have the assembled
power system reviewed by someone competent in battery and motor-drive design.

## Regenerative braking

A motor can return energy to its supply. The rail can rise above its normal
voltage and damage electronics if that energy is not handled. This is a known
motor-drive issue, not a function of the software battery percentage.
[TI motor regeneration discussion](https://www.ti.com/document-viewer/lit/html/SSZT878/GUID-72E4FF4E-0508-4018-A599-5B6605492BD5).

A full battery may be unable to accept more charge. Its BMS may block charging
or disconnect during a fault, removing the energy sink. Selecting a BMS does
not by itself solve rail overvoltage. The complete design must safely accept
or dissipate returned energy within the robot's voltage ceiling in those
conditions. Do not bypass a BMS, put an arbitrary diode in the supply lead or
add an unvalidated clamp as a shortcut.

A conventional bench supply often sources current without being able to sink
it. Do not assume that its current limit or nominal “12 V” setting makes it
suitable for driving or braking. A supply used for stationary diagnostics is
not automatically suitable for motion tests.

## Fire, injury and charging

Lithium-cell faults can cause severe heating, venting and fire. Overcharge,
overdischarge, excess current and excessive temperature need independent
protection. [TI Battery Protection 101](https://www.ti.com/video/3881954625001).

- Do not use swollen, damaged, leaking or abnormally hot packs. Isolate them
  safely and follow the manufacturer's handling/disposal instructions.
- Do not build or repair lithium packs without the appropriate expertise;
  use a professionally assembled, protected pack with documented ratings.
- Use a charger approved for the exact pack chemistry and cell count. A BMS
  is not a charger. Do not assume the original DJI charger suits an aftermarket pack.
- Disconnect all power before soldering or changing wiring. Check polarity
  electrically before connection; reversed polarity can destroy equipment.
- Do not connect a bench supply and battery in parallel without a designed
  power-sharing system that handles backfeed and reverse current.
- Charge and operate only as permitted by the pack manufacturer, away from
  combustible material and with appropriate supervision.

## Software is not the final protection

`INSTALL` disables the robot's battery capacity and authentication gates,
while retaining its roll-over check. The estimate cannot measure individual
cells, current or temperature and does not command a low-battery motion stop.
Its smoothing deliberately delays displayed changes, including a real sustained
discharge. A watchdog restoring native telemetry can leave a 0% display while
XT30 motor-gate settings remain active.

The BMS, fuse, electrical design and operator must therefore remain effective
when the script stops, freezes, reports an incorrect percentage or is absent.
Even a BMS cannot make incorrect wiring, unsuitable cells or an unvalidated
regenerative path safe. See [Safety](SAFETY.md) for motion precautions and the
[product instructions](../xt30-battery/README.md) for the complete reversal.
