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
| [warning_filter.py](warning_filter.py) | Exact-image RAM filter install, lease, restore, status and orphan recovery |
| [warning_hook_blob.py](warning_hook_blob.py) | Bundled original ARM code generated from `native/warning_hook.c` |
| [s1_battery_autostart.pth](s1_battery_autostart.pth) | Added Python service startup hook |
| [build_bundle.py](build_bundle.py) | Reproducible source bundle for the generator and developer diagnostics |

From the repository root:

```powershell
python xt30-battery/build_lab_script.py
python xt30-battery/build_lab_script.py --check
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests/run.ps1
python -m unittest discover -s xt30-battery/tests -p 'test_*.py'
```

Robot code targets Python 3.6; generation/tests use current desktop Python.
No vendor executable or private capture is required to build or test the product.
The bundle contains the listed files and their hashes. Developer modules with command-line
interfaces remain optional; the owner workflow is entirely in the Lab script.

`lab_manage.py` presents compact lifecycle summaries for the whole XT30 mod.
Routine helper stdout is suppressed only in the Lab orchestrator; standalone
developer CLI output is retained and exceptions propagate. Controller checks
are reported as verified only after `set_mode` returns successfully. STATUS
explicitly leaves authentication/capacity unverified instead of reading controller
parameters or inferring them from the installed files or warning-filter state.

The bundle now also carries 384 bytes of **our own** native ARM code encoded
in a Python source file. To change it, run `build_warning_hook.py --toolchain`
with the NDK LLVM `bin` directory, then regenerate the Lab script. `--check`
verifies that the native source still matches the embedded bytes. Native tests
require Unicorn; rebuilding requires pyelftools and NDK Clang. None of these
desktop tools are needed by the robot or the owner. See [details](WARNING_FILTER.md).
