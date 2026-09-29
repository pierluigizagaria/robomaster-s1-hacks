# Documentation

Documentation version: **2.0.0**

| Document | Purpose |
|---|---|
| [S1 Lab CLI](../lab-cli/README.md) | DLL-free standalone folder and automatic discovery; terminal upload/run/stop and output for external Python programs |
| [Root ADB Access](../root-adb/README.md) | Enable, verify and close temporary root access |
| [XT30 Battery Mod](XT30-BATTERY.md) | Mechanism, modes, protocol, activation, and restoration |
| [Safety](SAFETY.md) | Electrical, motion, battery, root-ADB, and desktop-patch safeguards |
| [Firmware compatibility](FIRMWARE-COMPATIBILITY.md) | Exact tested robot and Windows targets |
| [Battery power and BMS](BATTERY-POWER.md) | Mandatory independent cell protection, electrical ratings, regeneration and fire hazards |

The root [changelog](../CHANGELOG.md) records releases. The canonical version
is stored in [`VERSION`](../VERSION).

Status terms are used conservatively: **verified** means directly observed,
**supported** means exposed with a compatibility gate and recovery path, and
**unverified** identifies a result that still requires the stated hardware test.
