# Repository working instructions

Read [CONTRIBUTING.md](CONTRIBUTING.md) before making changes. Keep each tool's
README, shared compatibility/safety guidance and changelog consistent with its
actual behavior and evidence. Preserve unrelated work. Do not commit or push
unless requested.

## Public repository boundary

Do not add private captures, raw device logs, firmware extracts, vendor
binaries, credentials, device identifiers or workstation-specific user paths.
Use non-sensitive summaries and hashes to document evidence. Any local DJI
bridge used as a development reference is private, not redistributable code.
The S1 Lab CLI runtime uses Python sockets and FTP without a vendor DLL.

## S1 Lab and ADB maintenance

The owner authorizes agents working on an explicitly requested S1 debug task
to connect and enable temporary root ADB themselves with
`s1-lab.cmd run root-adb/scripts/enable_root_adb.py --timeout 40`
(`python lab-cli/scripts/s1_lab.py run root-adb/scripts/enable_root_adb.py --timeout 40`).
Do not ask the owner to open the original RoboMaster GUI, paste a program, or
repeat approval for that maintenance step. Keep the GUI closed; neither its
installation nor its bridge DLL is needed by the standalone CLI.

Check `s1-lab.cmd status` first and respect an occupied Lab. Never stop or
replace an unrelated program. Run with the S1 stationary: the stock Lab
framework can recenter the gimbal at program start and exit. Use the CLI's
matching project receipt for stops; no broad stop-all or implicit Skill install.

Reuse an already working, identity-verified S1 ADB connection. Run
the root-ADB program only when needed. Automatic discovery probes direct robot Wi-Fi
at `192.168.2.1` while listening for validated S1 router announcements. Use
`--host` for an explicitly identified private endpoint when discovery is
unavailable or ambiguous. Receipts retain the selected host for run/stop.
After enabling ADB, verify `id` and model `L1860` on the explicit S1 serial.
Always select the robot with `adb -s ADDRESS:5555`; never accidentally target
an attached Quest or another device. Preserve the workstation's established
ADB server port and do not kill shared ADB servers.

Temporary ADB closes after a full power cycle. Do not reboot autonomously as
a substitute for clean teardown: a software-only restart has previously left
the motion controller unavailable in an XT30 setup. This authorization does
not extend to firmware flashing, persistent root/ADB startup, Wi-Fi credential
changes, or unrelated motion/programs. Preserve the existing battery add-on.

## Terminal interface and verification

Program output/results belong on stdout; progress/errors belong on stderr.
Do not create automatic session logs or add an output-directory requirement.
Use shell redirection or `Tee-Object` when evidence is needed; `--json` emits
structured events. `upload file.py > receipt.json` explicitly saves a reusable
project receipt. Review captures for private data before sharing them.

Run the relevant offline checks, including the suite in
[tests/run.ps1](tests/run.ps1), without contacting a robot unless the active
task authorizes hardware work. Distinguish offline results, skipped private
reference checks and direct hardware evidence. Never promote tests of the
Lab path into claims about Wi-Fi gestures, motion, FPV or other integrations.
See [S1 Lab CLI](lab-cli/README.md) for commands, tested behavior and limitations.
