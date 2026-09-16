# Integrated #5/#9 warning filter

16 September 2026. Implemented and tested offline; **real robot acceptance pending**.
The owner uses only `../scripts/xt30_battery.py`. The ten-file Python bundle
contains the loader, lifecycle manager and the freestanding ARM payload.

## Scope

On the exact supported `dji_sys` image, intercept only event `003F0012` to
host `0200` (app). Validate the complete module roster, copy it onto the
call's stack and remove `C205` and `C209` **only from module `0300`**.
Keep module count/presence, other codes, order, duplicates of other codes,
envelope fields, send handle and return value. Adjust diagnostic counts and
payload length. Original memory and all other recipients remain untouched.
Payloads over 1008 bytes, malformed/duplicate-module rosters and other command/destination pairs use
the original function without filtering. The normal transport handles framing
and CRC; the hook does not manufacture a second network packet.

`C205` means unavailable smart-battery information; `C209` means failed
authentication. Critical/low charge `8201/8202`, temperature `8204`, current
`820B`, battery malfunction `C20A`, and all non-battery diagnostics stay intact.
These retained messages do not supply measurements absent from the XT30 pack.

## Native implementation

Supported ELF SHA-256:
`fb0df0de6080231c83fc1f87584a5baa4f237040a0ad3f2ce3cf3ef1466a8181`.
GOT import `duss_event_send` RVA `58D60`. Reserved zero gap is
`574A4..576E8`, after the first ELF LOAD's file content. The own-code payload
is 384 bytes, including a 16-byte configuration, and fits entirely in that
gap. Its Thumb entry is offset 17. It has no relocations, imports or heap use.
The original import must resolve exactly to the `duss_event_send` ELF32
dynamic function symbol in its mapped `/system/lib/` library; an unresolved
PLT slot or unrelated function is refused.

The loader checks PID/start time, image hash, mappings, complete zero/owned
padding, expected original pointer and payload integrity. It stages code
while unreachable. Publishing/restoring the aligned import occurs with all
service threads stopped (300 ms wait limit); a separately forked rescue sends
SIGCONT on control-pipe closure or a one-second timeout. The rescue owns both
STOP and CONT, drops unrelated inherited descriptors and uses a readiness
handshake, preventing a late parent STOP after rescue expiry. Reaping is bounded.
The service is never
killed/restarted. Install/uninstall should be performed on a stationary robot.

ARM Linux `copy_to_user_page` performs instruction/data-cache maintenance for
executable mappings, the kernel path used by cross-process memory writes.
See the [kernel implementation](https://android.googlesource.com/kernel/common/+/df2c1f38939aa/arch/arm/mm/flush.c).
This supports the approach; it is **not a measurement of this robot's kernel**.
Actual instruction-cache behavior and pause/recovery latency remain hardware gates.

Before filtering, native code reads CLOCK_MONOTONIC via ARM EABI syscall 263.
A missing, expired, implausibly far-future lease or failed clock read passes
the original message through. The estimator watchdog renews a maximum
three-second lease; parent loss triggers normal watchdog rollback after its
existing two-second heartbeat timeout. Even if both Python processes die,
the native lease stops suppression without requiring another Python process.
An in-flight invocation can finish under its previously checked lease.

Restoration clears the lease then restores the original import with readback.
The dormant code is deliberately left mapped until process exit: erasing it
could break an in-flight return. This is a RAM modification, not byte-for-byte
restoration of padding; reboot removes the remaining code. Reboot alone does
not reverse the separate persistent XT30 motor parameters and will reapply
the filter if the installed automatic startup remains enabled.

## Lifecycle and failures

- `INSTALL` retains the estimate's existing readiness/voltage guards and starts
  the filter with that worker. A different installed bundle is refused: remove
  it with `UNINSTALL` and install using the same new script.
- `STATUS` reads the native pointer/lease; it does not claim the UI visibly
  changed merely because the hook is armed.
- `DISABLE` stops the worker, restores the warning import, independently checks
  restoration and disables boot. It retains the XT30 motor settings.
- `UNINSTALL` also restores stock motor gates and removes manifest-owned files.
- Explicit disable/uninstall recovers a matching **expired** orphan hook. It
  refuses a live lease or foreign pointer and retains recovery files on failure.
- Installation failures do not claim success for the worker. An unsupported
  native profile stops the combined background attempt; consult `STATUS`/log.
- Changed executable, process restart, unexpected padding, changed code or
  original import stops/refuses the override. No arbitrary signature scans,
  controller firmware patches or runtime downloads are used.

## Evidence

The compiled payload is run in Unicorn against all 65,536 diagnostic words and
all 65,536 module IDs (batched), plus other destinations, malformed payloads,
lease failures and empty module lists. Tests verify ABI registers/stack,
return value and original buffer preservation. Mocked runtime tests exercise
normal restoration, orphan recovery, foreign ownership, changed code,
process restart, partial install failure and independent cleanup failures.

The existing 63 repository tests cover Lab textual preprocessing, Python 3.6
syntax, all four modes, manifest/bundle validation, estimate and controller
settings. The 13 native/filter tests are under `xt30-battery/tests`; they do not contact a
robot. The owner README and repository compatibility/recovery documentation
describe the same integrated version.

Additional lifecycle/reporting and real Linux process tests cover interrupted
maintenance, stalled/dead owners, inherited output descriptors and bounded
cleanup. See [the recovery investigation](../docs/LIFECYCLE-RECOVERY.md).

Still required: actual Lab install and A/B/A (#5/#9 before, hidden during,
returned after), packet comparison and internal diagnostics unchanged,
parent/watchdog termination, disable/uninstall, reconnect, reboot and support
for the target kernel/export mapping. No live PASS is claimed from emulation.
