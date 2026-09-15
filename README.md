# RoboMaster S1 Hacks

**Keep your RoboMaster S1 running.**

Practical mods and maintenance tools for the DJI RoboMaster S1: alternative
battery power, local robot access and offline app use. Each tool includes
compatibility checks, setup instructions and a way to restore the original state.

## Mods & tools

| Tool | What it does | Start here |
|---|---|---|
| **[XT30 Battery Mod](xt30-battery/README.md)** | Use a protected external battery, show estimated charge in the RoboMaster app and start automatically after reboot | One Python Lab script; experimental, restricted to documented robot builds |
| **[Root ADB Access](root-adb/README.md)** | Open a temporary root shell over the robot's Wi-Fi for local maintenance | Python Lab script; robot package `00.06.0515` |
| **[Windows Offline Patch](windows-offline/README.md)** | Use the Windows app when its remote account login no longer works | PowerShell script; exact documented app assembly hashes |

These tools are independent. Choose the one you need and follow its README.
Support is limited to the exact targets in the
[compatibility guide](docs/FIRMWARE-COMPATIBILITY.md).

## Getting started

1. Open a tool's guide above and check its requirements and limitations.
2. Read the [safety guide](docs/SAFETY.md), then follow the installation steps.
3. Keep the tool's disable or restore instructions available before making changes.

Download the source using GitHub's **Code > Download ZIP**, or clone it:

```sh
git clone https://github.com/pierluigizagaria/robomaster-s1-hacks.git
```

## Before you connect or modify anything

- **Battery power:** an external lithium battery must have an independent BMS,
  suitable wiring and a fuse. Charge estimation is not cell protection or an
  automatic low-battery stop. Read [Battery power & BMS](docs/BATTERY-POWER.md).
- **Robot maintenance:** keep all four wheels clear for initial tests and have
  an immediate physical power disconnect. Use root ADB on an isolated robot
  network and reboot when maintenance is complete.
- **App changes:** the Windows patch requires a supported file and a validated
  backup. Its README covers verification and restoration.

## Documentation & development

Each tool keeps its runnable files in `scripts/`. The XT30 mod also includes
readable source and a generator:

```text
xt30-battery/
  scripts/xt30_battery.py              complete Python Lab script
  src/                                readable runtime source
  build_lab_script.py                 regenerate the Lab script
root-adb/
  scripts/enable_root_adb.py           temporary root access
windows-offline/
  scripts/patch_robomaster_windows.ps1  app patch and restore tool
docs/                                 shared guides
tests/                                offline checks
```

The [documentation index](docs/README.md) covers compatibility, safety and
implementation details. See the [changelog](CHANGELOG.md) for changes and
[contributing guide](CONTRIBUTING.md) to help improve the tools.

Run the offline checks from this repository with Python 3 and PowerShell:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\run.ps1
```

The checks use local fixtures and require no connected robot or installed app.
Report security or hardware-safety issues using the [security policy](SECURITY.md).

## License & affiliation

Source code and original documentation are released under the [MIT License](LICENSE).
This independent project is not affiliated with or endorsed by DJI. RoboMaster
and DJI are trademarks of their respective owner.
