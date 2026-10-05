# S1 Lab CLI

Upload and run Python Lab programs on a RoboMaster S1 from a Windows terminal,
read live output, and stop the exact program you started. The original
RoboMaster GUI stays closed; an existing ADB connection is not required.
The client speaks the S1 Wi-Fi protocol and transfers projects by FTP using
only the Python standard library. **No DJI DLL, RoboMaster installation or
additional Python packages are required.** The complete `lab-cli` folder runs
independently of the rest of this repository. It contains only the client;
robot programs remain in their respective hack folders and are supplied by path.

## Requirements

- Windows and Python 3.10 or newer in PATH; no extra Python packages.
- A stationary S1 on direct-mode Wi-Fi or the same router network as the PC.
- The supported Scratch service signature and version listed in
  [Compatibility](../docs/FIRMWARE-COMPATIBILITY.md#s1-lab-cli).
- The RoboMaster GUI and other Lab clients closed. The CLI reports an occupied
  UDP 10608 port; it does not close other applications or stop their programs.

The stock Lab framework **recenters the gimbal at program start and exit**,
including a program that only prints text. Keep the gimbal clear.

## Quick start

From the repository root, check status and supply your program file:

```powershell
.\s1-lab.cmd status
.\s1-lab.cmd run path/to/your_program.py
```

Check `status` first and respect an occupied Lab. The launcher is equivalent to
`python lab-cli/scripts/s1_lab.py`; running it without arguments shows help.
With no `--host`, the client tries direct Wi-Fi at `192.168.2.1` while listening
for S1 announcements on UDP 45678, following the Quest discovery rules. A
validated router announcement replaces an unconfirmed direct attempt. A ready
connection wins; the address is shown on stderr. Announcements must contain
the sender's matching private IPv4 address, and connection readiness requires
the supported Scratch service plus a valid Lab state. The client does not scan
the subnet or save discovered addresses in configuration.

If multiple robots announce together, select one explicitly. If announcements
are blocked by the router/firewall, or another client occupies UDP 45678, use
the known robot address:

```powershell
.\s1-lab.cmd --host 192.168.1.42 status
```

An explicit `--host` disables discovery. Global options such as `--host`,
`--json` and `--connect-timeout` go before the command. Connection/discovery
defaults to 15 seconds; `--connect-timeout SECONDS` accepts 1 through 60.
Announcements are endpoint hints, not cryptographic authentication; use a
trusted local network. Discovery never changes an existing receipt's target.

## Standalone folder

Copy the complete `lab-cli` folder to the location you want to use. Its own
`s1-lab.cmd` resolves scripts relative to itself, so it works from another
working directory and needs no sibling hack folders. Program paths are relative
to your current directory, or absolute. The root-level launcher in the checkout
delegates to the same entry point.

```powershell
& 'D:\S1 Lab\s1-lab.cmd' status
& 'D:\S1 Lab\s1-lab.cmd' run 'D:\My scripts\program.py'
```

`--bridge` has been removed and `S1_LAB_BRIDGE` is not read. There is no vendor
loader or private runtime lookup. A copied-folder hardware run from another
working directory is verified below. The development PC still had RoboMaster
installed, but the client did not load or use it; a separate clean-PC acceptance
run and other host operating systems have not been tested.

A connection timeout does not show that the Lab is idle and is not permission
to stop another program.

| Command | Result |
|---|---|
| `status` | Print the Lab state and Scratch service version. |
| `upload file.py` | Upload without running; write a JSON receipt to stdout. |
| `run file.py` | Upload, run, stream output and wait for completion/error/timeout. |
| `run-project receipt.json` | Run a project already uploaded to the same robot address. |
| `stop receipt.json` | Send Exit only when the active GUID matches the receipt. |

Receipts store the resolved robot address. `run-project` and `stop` connect to
that address even when `--host` is omitted, and reject a conflicting explicit
host. They do not rediscover another robot if the saved address changes.

`run` and `run-project` default to a 60-second timeout. Override with
`--timeout SECONDS`, from 1 to 3600.

## Terminal streams and pipes

Program output and results go to **stdout**. Progress and errors go to
**stderr**. Robot output is printed immediately, without decorative prefixes
or color codes. Progress has color only when stderr is a terminal; `NO_COLOR`
disables it. There are no automatic session logs or receipts, and no
`--output` option.

```powershell
.\s1-lab.cmd run my_program.py
.\s1-lab.cmd run my_program.py > output.txt
.\s1-lab.cmd run my_program.py | Tee-Object output.txt
.\s1-lab.cmd run my_program.py 2> errors.txt | Select-String temperature
.\s1-lab.cmd --json status | ConvertFrom-Json
.\s1-lab.cmd upload my_program.py > receipt.json
.\s1-lab.cmd run-project receipt.json --timeout 120
```

Redirecting stdout leaves progress visible in the terminal. Use `2>&1` only
when you want combined streams. `--json` puts structured events on stdout
instead of the normal presentation; for a reusable receipt, use `upload`
without `--json`. PowerShell UTF-8 and UTF-16 receipt files are accepted.

Failure, timeout or interrupted execution returns a nonzero exit code.
Ctrl+C, timeout or a closed downstream pipe triggers an attempt to stop only
the owned project and disconnect cleanly. Loss of the robot connection leaves
completion unconfirmed; reconnect and inspect `status` before further actions.
Only one Lab client can own the connection. `stop receipt.json` is for recovery
in a later session, not a second simultaneous client.

## Programs and robot writes

Use the Lab's `def start():` convention:

```python
def start():
    print("Hello from S1")
```

The source file is read, checked and packaged before any robot connection, so
missing files, invalid Python and incompatible source fail immediately.
The robot runs Python 3.6 and the Lab's restricted APIs, not the PC interpreter.
The firmware changes some literal escape sequences and inserts loop checkpoints
using text matching. The client rejects source that would be changed ambiguously:
use multiline loops and `chr(10)` or `chr(34)` instead of problematic literal
backslash escapes. Names beginning `_s1_lab_` are reserved for execution markers.

Each upload uses a new GUID and the ordinary DSP XML/FTP project route.
It does not assign Skill, replace existing projects, or install
a startup task. The firmware writes normal Lab project files under
`/data/script/file/`; those projects remain after the session. **No firmware
flashing does not mean no filesystem writes.** The CLI does not modify system
files, boot scripts or the battery add-on.

The client waits for FTP completion, project-creation acknowledgement and a
fresh Idle state received after that acknowledgement. An intermediate Uploading
state after the ACK is normal.
A successful run requires the owned project's completion marker and return to
Idle without a reported error. An upload ACK or completion text alone is not
accepted as success. Error cleanup is allowed to finish before another run.

Projects are prepared and transferred in memory; the client creates no temporary
DSP files or session folders. A bounded FTP worker lets the main thread continue
Wi-Fi acknowledgements; interruption closes its sockets. Transport checks
packet checksums, session/command identities and reliable delivery order.
Duplicate packets are suppressed while distinct identical prints are retained.
Fragmented control messages are currently refused, with completion unconfirmed;
long output and arbitrary programs beyond the documented cases need validation.

## Running a hack

The client has no bundled programs or hack-specific commands. Pass the script
from the relevant hack folder to `run`. For example, from the repository root:

```powershell
.\s1-lab.cmd status
.\s1-lab.cmd run root-adb/scripts/enable_root_adb.py --timeout 40
```

The [Root ADB guide](../root-adb/README.md) describes its prerequisites,
identity verification and temporary access lifecycle. Follow each hack's own
instructions before running its program. The standalone client can execute
files anywhere on the PC; copying programs into `lab-cli` is unnecessary.

## Verification and limits

On 29 September 2026, the DLL-free client was tested on a stationary
S1 with the gimbal clear and GUI closed, using a router Wi-Fi network:

- Automatic discovery selected the S1 and `status` reported Ready and Scratch
  service `01.00.01.00` without ADB or a vendor library.
- Upload, execution, live output and return to Idle passed repeatedly for a
  print-only `start()` program. Its UTF-8 source SHA-256 was
  `d875ddbd39c9b242a8cbaeaa56a958599f3db44655910ad79399a7623ad9e08a`.
- The entire folder was copied and launched from another working directory.
  `upload` produced a shell-redirected receipt; separate `run-project` calls
  returned exactly one `Hello from direct Python Lab` line and exit code zero.
- A one-second `run-project` deadline returned nonzero, stopped only the owned
  project, and returned to Idle. Reusing the receipt then ran successfully;
  the final `stop` reported that Lab was already idle. No reboot was used.
- The root-ADB maintenance program ran over the direct Python transport:
  four setup steps, `S1_ADB_READY`, Finished and exit code zero. Explicit ADB
  readback confirmed `uid=0(root) gid=0(root)` and model `L1860`, preserving the
  existing host ADB server port. Final Lab status was Ready.

Early native tests exposed duplicate output, a project-creation ACK preceding
Idle, and a three-second FTP timeout. The client now deduplicates packet
identities, waits through the Uploading state, and uses five-second FTP socket
bounds with phase-specific errors. The complete copied-folder acceptance above
passed after those changes. This is not a long-duration reliability claim.

Earlier installed-bridge tests on this S1 also covered an intentional script
error followed by successful rerun, `Tee-Object`, temporary root ADB and Lab
access when ADB was unavailable during an AP/router/AP investigation. They are
historical evidence, not new native-client hardware coverage for those error or
Wi-Fi transition cases. That bridge's development-reference SHA-256 was
`d6238587931e90876385a91c3c7a296e8b0ffeb80168535be9365d883e55966f`;
it is neither shipped nor required. Historical build readback was
`leadcore1860` / `eng.jenkins.20221027.033121`; the commercial robot package
version was not confirmed or inferred.

An earlier Exit racing firmware error cleanup required targeted manual
recovery. The client waits for cleanup; automatic firmware/socket repair is
not a feature. On an unconfirmed stop, reconnect and inspect status before
further actions. Do not reboot autonomously as a recovery shortcut.

The ADB program was subsequently consolidated into
`root-adb/scripts/enable_root_adb.py`, outside the client. Its command handling
and messages were simplified while retaining the tested setup sequence and
bounded root checks. These changes and removal of the dedicated CLI command
were checked offline, without restarting ADB.

The subsequent upload simplification removed temporary files and the old
synthetic upload callback. Offline checks compare the exact transfer bytes,
exercise creation ACK/Idle ordering and confirm that invalid source fails before
connection. This refactor has no additional hardware acceptance run recorded;
earlier hardware evidence remains documented above and in the Root ADB guide.

The offline Lab suites run **55 tests: 54 pass and one optional private firmware
parser check is skipped**. The full repository runs **130 tests: 129 pass and
the same one is skipped**; syntax checks, the generated XT30 program and the
Windows patch self-test pass. Tests cover packet corruption/reordering and
retries, duplicate output, discovery handoff and ambiguity, version gates,
FTP errors/interruption, fresh state, owned stops, receipt targeting/encodings,
stream behavior and standalone launching without a vendor loader.

```powershell
python -m unittest discover -s tests -p 'test_s1_*.py' -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\run.ps1
```

No robot or DJI installation is needed for offline tests. Private captures,
firmware source, vendor binaries and actual device addresses are not distributed.
Native direct-mode hardware, other firmware/host versions, Wi-Fi button
gestures, Quest controls, FPV, driving and arbitrary third-party Lab programs
are outside the hardware evidence above.
