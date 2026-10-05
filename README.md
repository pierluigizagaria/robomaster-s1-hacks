# RoboMaster S1 Hacks

Practical mods and maintenance tools for the DJI RoboMaster S1: alternative
battery power, local robot access and offline app use. Each tool includes
compatibility checks, setup instructions and a way to restore the original state.

## Mods & tools

| Tool | What it does | Start here |
|---|---|---|
| **[XT30 Battery Mod](xt30-battery/README.md)** | Use a protected external battery, show estimated charge in the RoboMaster app and start automatically after reboot | One Python Lab script; experimental, restricted to documented robot builds |
| **[S1 Lab CLI](lab-cli/README.md)** | Upload/run external Python programs and stream their output | Standalone client; Windows, Python 3.10+; automatic discovery, no DJI DLL or bundled programs |
| **[Root ADB Access](root-adb/README.md)** | Open a temporary root shell over the robot's Wi-Fi for local maintenance | Run the single script in `root-adb/scripts/` through S1 Lab |
| **[Windows Offline Patch](windows-offline/README.md)** | Use the Windows app when its remote account login no longer works | PowerShell script; exact documented app assembly hashes |
| **[Android Offline APK](android-offline/README.md)** | Private copy of the Android app 1.2.0 that opens without the account login (phone and Quest 3) | Python patcher and verifier; exact APK and library hashes; not yet validated with the robot |

Choose the tool you need and follow its README. S1 Lab runs programs from the
other hack folders; it includes no robot programs of its own.
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
  network and manually power-cycle when maintenance is complete. Lab programs
  can recenter the gimbal even without driving commands.
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
lab-cli/
  s1-lab.cmd                          launcher for a standalone folder
  scripts/s1_lab.py                    terminal Lab client
s1-lab.cmd                            Windows launcher for the Lab CLI
root-adb/
  scripts/enable_root_adb.py           single root-ADB program, run through S1 Lab
windows-offline/
  scripts/patch_robomaster_windows.ps1  app patch and restore tool
android-offline/
  scripts/patch_original_android_offline.py  APK patcher (Python)
  scripts/verify_original_android_offline.py  emulated check against the APK
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
and DJI are trademarks.
