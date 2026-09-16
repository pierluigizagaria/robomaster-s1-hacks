# XT30 Battery Mod source

Owners use the generated [Lab script](../scripts/xt30_battery.py); they do not
copy individual source files or run a PC installer.

| File | Role |
|---|---|
| [lab_launcher.template.py](lab_launcher.template.py) | Lab entry point, checked embedded bundle, temporary extraction/cleanup |
| [lab_manage.py](lab_manage.py) | INSTALL, STATUS, DISABLE, UNINSTALL orchestration |
| [controller_settings.py](controller_settings.py) | Guarded persistent XT30/stock controller states |
| [process_guard.py](process_guard.py) | Bounded command/recovery waits and independent service resume |
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
are reported as verified only after `set_mode` returns successfully. The manifest
stores that historical readback; STATUS labels it `last verified`. An absent
record never implies OFF. A new parameter operation invalidates the previous
record before mutation. STATUS does not read controller parameters or infer
them from the installed files or warning-filter state.

Lab output is streamed from a regular temporary file, without waiting on pipe
EOF from descendants. The launcher uses a 90-second action deadline, 30 seconds
for graceful recovery and a final bounded 2-second reap. Recovery files remain
when shutdown or native/controller restoration cannot be confirmed. The
maintenance script replaces only the framework's exit reset helper to omit
automatic recentering; all framework stop/exit/event cleanup remains.
See [lifecycle evidence and limitations](../docs/LIFECYCLE-RECOVERY.md).

The DJI project parser expands escaped newlines/quotes before inserting loop
checkpoints. The launcher must survive that normalization unchanged;
`build_lab_script.py` enforces it. Tests model both normalization and checkpoint
insertion. The optional `tests/check_private_lab_framework.py` accepts a local
original `script_framework.py` path and checks the exact private DSP parser,
source transformations and finalizer without distributing vendor source.

The bundle now also carries 384 bytes of **our own** native ARM code encoded
in a Python source file. To change it, run `build_warning_hook.py --toolchain`
with the NDK LLVM `bin` directory, then regenerate the Lab script. `--check`
verifies that the native source still matches the embedded bytes. Native tests
require Unicorn; rebuilding requires pyelftools and NDK Clang. None of these
desktop tools are needed by the robot or the owner. See [details](WARNING_FILTER.md).
