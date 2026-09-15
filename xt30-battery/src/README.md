# XT30 Battery Mod source

Owners use the generated [Lab script](../scripts/xt30_battery.py); they do not
copy individual source files or run a PC installer.

| File | Role |
|---|---|
| [lab_launcher.template.py](lab_launcher.template.py) | Lab entry point, checked embedded bundle, temporary extraction/cleanup |
| [lab_manage.py](lab_manage.py) | INSTALL, STATUS, DISABLE, UNINSTALL orchestration |
| [controller_settings.py](controller_settings.py) | Guarded persistent XT30/stock controller states |
| [manage.py](manage.py) | Data-only file installation, manifest, enable/disable and verified removal |
| [boot.py](boot.py) | Exact stock-service hook, telemetry priming and bounded startup |
| [worker.py](worker.py) | Internal voltage estimate, filters, presence and RAM restoration watchdog |
| [telemetry.py](telemetry.py) | Local battery-only subscription used briefly during startup |
| [s1_battery_autostart.pth](s1_battery_autostart.pth) | Added Python service startup hook |
| [build_bundle.py](build_bundle.py) | Reproducible source bundle for the generator and developer diagnostics |

From the repository root:

```powershell
python xt30-battery/build_lab_script.py
python xt30-battery/build_lab_script.py --check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/run.ps1
```

Robot code targets Python 3.6; generation/tests use current desktop Python.
No vendor executable or private capture is required to build or test the product.
The bundle contains source and hashes only. Developer modules with command-line
interfaces remain optional; the owner workflow is entirely in the Lab script.
