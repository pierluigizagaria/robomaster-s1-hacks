# Lab completion and recovery investigation

Updated 23 September 2026. Direct ADB testing confirmed that the STATUS
payload exits in about 1.3 seconds and that UNINSTALL removed its files and
stopped the worker normally. A later STATUS run in Lab completed. The earlier
spinner after `UNINSTALL OK` was downstream of the payload; its exact DJI
framework call was not captured while it was stuck.

The generated Lab script prints `INSTALL OK`, `DISABLE OK` or `UNINSTALL OK`
from a wrapper after DJI's original controller exit returns, provided that
the payload completed and DJI's normal `stop()` returned. DJI still closes
its event and resets the running state afterward; only the app can display
`Execution Complete` when the whole Lab program ends. Child errors are
propagated to the framework as one final exception, without printing the same
`ERROR` line in the child relay and bridge. The observations below describe
earlier versions of the reporting protocol.

On 23 September, a real INSTALL timed out waiting 25 seconds for the estimate.
ADB showed that the detached starter was repeatedly getting `Address already in
use` while trying to open telemetry Node C9: Lab itself held that exclusive
socket until its script ended. The installer now checks the starter's process
claim instead of waiting for the worker's `active` event inside Lab. The starter
can wait up to five minutes for Lab to release the socket; `INSTALL OK` reports
completed setup and a launched starter, while a later `STATUS` confirms the
estimate actually became active. No motion test is needed to verify startup.
The corrected payload was installed through root ADB with the telemetry socket
held for 20 seconds to reproduce the conflict. INSTALL returned its completed
state rows in about five seconds; the detached starter logged the occupied
socket once, then started the worker after release. A later STATUS showed
`Battery warnings: hidden` and `Battery percentage estimate: active`. The
stationary pack-voltage samples were about 10.2–10.3 V, so no motion testing
was performed. The actual Lab console timing of this revision remains to be
checked in Lab.
The current Windows suites pass 75 repository tests and 50 XT30 tests (nine
Linux-only skips); the generated script passes its source check and
`git diff --check`. Its SHA-256 is
`A97B0405AE9B8D46FCF7C48C59A54D60BF2C9864147E2F0FEE2E64FCAC356CCE`.

## Earlier observations

The earlier reporting revision used plain label/value rows and removed the
redundant installation/auto-start summary. INSTALL reports `Battery checks`,
`Battery warnings` and `Battery percentage estimate`; STATUS uses the same
three labels and explicitly calls the percentage an estimate. DISABLE and
UNINSTALL report only the states they actually changed. The public
`INSTALL OK`, `DISABLE OK` or `UNINSTALL OK` line belonged to the outer
launcher and is printed only after child exit, the private completion record
and temporary-file cleanup. STATUS has no `STATUS OK`, because that wording
could be mistaken for a healthy runtime state.

The first real STATUS attempt with this reporting layout showed only the
launcher heading followed by `Execution Complete`: the manager completed, but
none of its state rows reached the Lab console. The state rows now use explicit
per-line flushing. A separate failure screenshot also showed only generic
`exit 1`; the launcher now extracts the final controller `ERROR` from its log
and includes it in the propagated Lab exception. These are reporting changes
only; no controller setting or installed runtime behavior changed.

In the following real INSTALL run, the user saw `INSTALL OK` and reported that
Lab then remained in `Running` for an estimated 20–30 seconds before finishing. By
the time `INSTALL OK` is emitted, controller exit, the private completion
record and launcher temporary-file cleanup have all returned. The remaining
tail is therefore inside DJI's stock finalization and is consistent with a slow,
terminating finalizer rather than an installer hang. The requested `INSTALL OK`
wording remains unchanged.

Follow-up from the user at 22:32:48 on 16 September: UNINSTALL reports native
app error reporting restored, authentication/capacity ON verified, removal
complete and auto-start OFF, but the screenshot still shows `Running--`.
This does **not** establish successful Lab termination; the earlier changes
have not been confirmed to resolve that symptom. The duration is not yet
known. There are no devices in the local ADB listing, so no live process stack
or robot log was collected. The exact outstanding call remains unidentified.

The manager prints those messages before it releases its control lock and
exits. The launcher still has to observe that exit and remove temporary files;
then the stock framework runs event registration, stop and controller/event
cleanup before the stock script manager resets its running state. The screenshot
does not distinguish these stages. Do not infer that a detached estimator is
keeping Lab running: UNINSTALL has already reported it stopped, and this
maintenance mode does not launch another background worker.

## Report and findings

Follow-up at 22:41:18 and 22:41:36: only the INSTALL introduction appeared,
followed by `Execution Complete`. The user confirmed two separate Run presses
without Stop. The app's saved DSP project from 22:41:18 decodes to the exact
complete generated script at commit `7eab199`; no truncated paste was found.
The user then reported another run succeeded, after the earlier issue following
UNINSTALL. This is a reported successful retry, not a diagnosis of the transient
failure or full hardware acceptance. No robot output/stack from those runs is
available to establish why the result rows were absent.

One independent reporting defect was corrected: launcher exceptions were
printed and swallowed, allowing Lab to report normal completion after an error.
They now propagate to the original framework. Exit zero also requires a private
per-action completion line, written by the child after the action and control
lock cleanup return. Missing, partial, wrong-mode or nonfinal confirmation is an
error. The protocol line is not displayed; normal INSTALL has one introduction,
three state rows and a final `INSTALL OK` (five rows total).
This does not claim to reproduce or fix the transient post-UNINSTALL issue.

Timing audit: INSTALL and UNINSTALL each have an unconditional `sleep(7)` before
their final result lines, intended to cover the native battery presence timeout
and outgoing roster cadence. Other waits end early when their condition is met.
The launcher 90-second action deadline and 30+2-second termination bounds apply
to failure/recovery, not every normal execution. No fixed seven-second delay
follows the controller state rows. `INSTALL OK`/`UNINSTALL OK` now follow
child/launcher exit and temporary cleanup; only DJI framework cleanup remains
after them. The background estimator startup is detached. Timers and native/
robot behavior were not changed in this reporting update.

Verification at that earlier revision: Windows repository suite 63 PASS; XT30 suite 46 cases,
37 PASS and nine Linux-only skips. All 23 reporting/launcher cases pass on
Windows. Generated bundle, Python 3.6 syntax, modeled DJI parser/checkpoints and
completion/error paths pass. No new private-framework or robot run was made.
Current generated SHA-256:
`E1E675B23FB68AEA9FC0E02BA8D08E7982189AF46F9D45B45D7C3BE2ED027AE2`.

The user reported UNINSTALL remaining in `Running--`. A later INSTALL screenshot
showed verified battery checks and `INSTALL complete` followed by `Running--`.
This proves that the installer had printed its result before Lab finished;
it does not identify which finalization call was waiting on that run.

Inspection found these concrete software problems:

- The launcher killed a timed-out child and then called `communicate()` without
  a timeout. A descendant retaining its output pipe could keep that call waiting.
- Service-pause rescue children inherited unrelated output, lock and heartbeat
  descriptors. Parent cleanup also used unbounded `waitpid(child, 0)`.
- The worker could block writing to a full heartbeat pipe or waiting for its
  restoration child. Killing that child is not a valid substitute for recovery.
- The original DJI framework calls `robot_exit()` after user code, whose
  `robot_reset()` starts another gimbal recenter task. The task framework allows
  a 60-second completion wait. This is a possible explanation for the delay
  after `INSTALL complete`, **not a hardware-confirmed diagnosis**.

The private, unmodified framework reference examined has SHA-256
`F939A0F896AB03F4CBAB9ECF955758776CBC3BB7DB66889363C498D781E91338`.
Its source is not distributed here. Its actual finalizer was executed locally
with controller/event mocks: all stop, exit and event cleanup calls remain,
and only the additional recenter task is omitted by the maintenance script.
The initial `ready()`/robot initialization has already run before user code.

## Follow-up: Lab syntax error before startup

The user then reported `SyntaxError: EOL while scanning string literal` at
line 73 of the new launcher. The exact original `DSPXMLParser.parseDSPString`
replaces escaped newlines with actual newlines, including inside a Python
string literal. The initial test model covered loop checkpoints but omitted
this earlier normalization, so its PASS did not cover the failing path.

The old newline byte literal reproduces the error through that original parser.
The launcher now constructs its separator with `b''.fromhex('0a')`. The
generator refuses source that DJI normalization would alter, and the test
model now includes the missing transformation. All four generated modes
compile through the original parser, checkpoint insertion, indentation and
full framework. This failure happens before launching the install controller.

Private reference hashes: project parser
`F700D3417C5508C042CE1EBE8C0D4446A8B544A1C27FFBE61263947B5E85DAD9`;
script manager
`0F470D12C2FF856F98C36DECC45A50FC55A9B85D96A1C679BA3B5D335D6D594C`.
The optional local check is `tests/check_private_lab_framework.py`; vendor
code remains outside this repository.

## Changes

- An immediate `please wait` line explains the selected maintenance action.
  Subsequent result lines are streamed from a regular file, without requiring
  EOF from background processes. Normal INSTALL ends with `INSTALL OK`, emitted
  only after verified controller completion and launcher cleanup.
- The launcher has a 90-second action deadline, then up to 30 seconds for
  graceful rollback and route cleanup, followed by a bounded 2-second reap
  after forced termination. Temporary sources remain if termination is not
  confirmed. Lab Stop also enters cleanup; removing the ten known temporary
  files does not use a loop that Lab can interrupt with injected checkpoints.
- `process_guard.py` owns bounded native command waits and service pauses.
  A separate child owns both STOP and CONT, announces readiness, closes
  unrelated inherited descriptors, and resumes on parent death or deadline.
  This avoids a delayed parent issuing STOP after its rescue has expired.
  Already-stopped services and changed PID identities are refused.
- Native CLI output uses a regular file. A timeout terminates only that owned
  command's process group. A one-second cleanup deadline replaces unbounded
  pipe draining.
- The worker heartbeat is nonblocking; watchdog reaping is limited to five
  seconds. A surviving restorer keeps its inherited worker lock. Removal
  refuses to proceed while that lock is held or native restoration cannot be
  independently verified. Existing release manifests remain removable, and
  warning recovery uses the new bounded helper with the same native guards.
- Cancellation enters parameter rollback/route cleanup. A mount that succeeded
  just before cancellation is recognized by file identity and unmounted.
  Detached startup exits through cleanup on termination.
- The maintenance script's exit reset preserves mode reset and gimbal resume
  but does not issue a recenter task. It does not replace framework stop calls,
  `robot_exit()`, event cleanup, DJI files, or LED behavior.

## What the messages mean

`Battery checks: disabled` is printed by INSTALL only after readback and
temporary-route cleanup succeed. The installation manifest records those
verified values. STATUS reports `Battery checks: disabled (last verified)`;
it does not perform another controller transaction. Before any new parameter
operation the old record is cleared. Old installations without a record report
`Battery checks: not verified` rather than fabricating a state.

`Battery warnings` describes the authentication and missing-information
categories handled by the filter. STATUS independently reads the filter's
lease/state. `Battery percentage estimate` deliberately says estimate because
it is voltage-derived, not a precise smart-battery measurement. The estimate
remains detached.

UNINSTALL restores original battery checks, which can legitimately make XT30
motion unavailable. This is separate from a stuck Lab program. An error or
unverified recovery retains the installation and is never reported as a
completed uninstall.

## Previous revision verification (before the completion-record update)

- 63 repository tests pass on Windows and Linux, including generated bundle,
  Python 3.6 syntax, Lab preprocessing, lifecycle and controller rollback.
- 13 existing ARM/Unicorn filter tests pass on Windows. Native C/blob unchanged;
  no NDK rebuild was performed in this change.
- 14 reporting/launcher tests pass on Windows and Linux, including readback
  history, failed startup, late background processes, partial progress lines,
  bounded shutdown, retained recovery sources, Lab Stop cleanup and the three
  new parser/build regressions.
- 10 process-guard tests pass on Linux, with real disposable Python children:
  parent death, parent stall, delayed rescue startup, preexisting stop,
  identity mismatch, exception cleanup, inherited descriptors and native
  command timeout/output inheritance. Windows runs the portable deadline test
  and skips the nine Linux-specific cases.
- The generated script matches its sources; `git diff --check` passes.

That revision had 100 distinct automated tests across the two platforms, plus the private
parser/framework/finalizer checks. The corrected script SHA-256 is
`B6E3C540699DB96BD227ECC301E8B6C0907F3D0C8A3BB9071DBAF295E922850E`.

Still required on hardware: time INSTALL and UNINSTALL through Lab's actual
`Execution Complete`, observe connection/controls, verify settings and app
errors before/during/after, and repeat stop/reconnect/reboot checks. Local
process tests do not establish pause latency, instruction-cache behavior,
gimbal behavior or complete recovery on the robot.
