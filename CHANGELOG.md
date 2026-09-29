# Changelog

## Unreleased

- Removed the extra output/redirection and DJI-app footer from S1 Lab help.
- Added the Android offline patcher and private emulator verifier as source
  tools, gated to the documented original APK and library hashes. APKs,
  extracted binaries, captures and private reports are not distributed; robot
  functions remain unverified. See the Android guide for historical evidence.
- Simplified the single root-ADB program: one command helper, a direct bounded
  readiness loop and compact output. Preserve setup order, error propagation,
  port and process-identity checks; deduplicate addresses and tolerate whitespace.
  Verified offline, without a new hardware enable cycle.
- Simplified S1 Lab uploads: validate the source before connecting, transfer
  DSP bytes directly from memory and remove temporary session folders and the
  legacy synthetic upload callback. Keep one completion check for the creation
  ACK followed by fresh Idle, with byte-equivalence and failure tests offline.
- Added the standalone **S1 Lab CLI** with direct Python Wi-Fi/FTP transport.
  No DJI DLL, RoboMaster installation, extra Python package or existing ADB
  connection is required. The complete folder has its own Windows launcher.
- Added automatic S1 discovery using the Quest approach: direct Wi-Fi probing
  alongside validated UDP 45678 announcements, ready connection precedence,
  explicit-host override and refusal of ambiguous discovery. Saved receipts
  retain the selected robot address for subsequent run/stop commands.
- Added upload/run, live output, saved receipts and owned-project stop, with
  Scratch service/version and protocol integrity checks. Handle
  retransmitted output, upload ACK-before-Idle ordering and bounded FTP cleanup.
- Kept program/results on stdout and progress/errors on stderr, with normal
  pipes, redirection and optional JSON events; no automatic session logs.
- Kept S1 Lab as a standalone client with no bundled robot programs or
  hack-specific commands. Run scripts from other hack folders by file path.
- Kept one ADB program in `root-adb/scripts/enable_root_adb.py`.
  Removed the duplicate script, generator, temporary test copies and ADB caches.
  It uses bounded `pidof`/`/proc` validation of daemon identity and all four root
  UIDs, propagates setup failures and prints explicit S1 identity/model commands.
  Removed stale software-reboot recovery advice.
- Verified the native client on router Wi-Fi: automatic discovery, repeated
  upload/output/Idle, copied-folder receipt reuse, timeout-stop and successful
  rerun. The full root-ADB maintenance program also passed, followed by ADB root and
  model `L1860` checks while preserving the host ADB server port.
- Kept earlier installed-bridge error-cleanup and AP/router/AP diagnostic
  evidence separate from native hardware coverage. Record gimbal recentering,
  persistent normal Lab project files, protocol limits and manual recovery.
- Passed 129 of 130 repository tests; one optional private firmware-parser test
  is skipped. The Lab portion has 54 passes and that skip across 55 tests.
  Syntax, the generated XT30 script and Windows patch self-checks also pass.
  Syntax checks compile in memory, without recreating ADB cache files.
- Added agent maintenance instructions for authorized S1 debug work, explicit
  target verification, reuse of working ADB and preservation of XT30. No
  firmware flash, persistent ADB, Wi-Fi gesture or motion validation is implied.

- Documented the tested XT30 battery configuration with assembly photographs,
  Samsung INR18650-30Q high-discharge cells, a 3S 25A balancing BMS and an
  AliExpress product reference.
- Made Lab messages describe the whole XT30 mod, distinguish verified battery
  check changes from runtime status, and keep routine output compact.

- Integrated the reversible #5/#9 warning filter into the existing single
  XT30 Lab script and its INSTALL/STATUS/DISABLE/UNINSTALL lifecycle.
  Preserve electrical alarms and internal diagnostics; add an expiring
  native lease, guarded RAM import restoration and orphan recovery.
  All 63 existing and 13 new offline tests pass; hardware acceptance is pending.

- Fixed Lab launcher compatibility: removed the unavailable `zlib` dependency
  and an inline generator incompatible with Lab's checkpoint insertion. Added
  regression checks for both failures. Full device acceptance remains pending.

- Introduced **XT30 Battery Mod**: one Lab script for XT30 settings, internal battery
  estimation, automatic startup, status, disabling and full removal.
- Added voltage-curve filtering and publication to the RoboMaster app's battery
  indicator without modifying the app.
- Added guarded stock restoration, installation rollback and offline tests.
- Added mandatory BMS requirements and electrical, charging, regeneration and
  fire-risk documentation.
- Marked combined hardware acceptance, platform coverage and battery calibration
  as incomplete.

## 2.0.0

- Established separate battery, volatile root ADB and Windows offline tools.
- Added compatibility checks, recovery procedures and offline tests.

See each product README for its current requirements and limitations.
