# Compatibility matrix

Last updated: **29 September 2026**

## XT30 Battery Mod

The complete product accepts only these exact native executables:

| File | SHA-256 |
|---|---|
| `/system/bin/dji_hdvt_uav` | `19d957e93672ce105d09eec509ec2fb873c8eb69a9287e0a505a6438538b2b38` |
| `/system/bin/dji_sys` | `fb0df0de6080231c83fc1f87584a5baa4f237040a0ad3f2ce3cf3ef1466a8181` |

Installation also checks `/init.rc`, the DJI system-start script, the Lab service
script and Python `site.py` against the hashes in
[the installer](../xt30-battery/src/manage.py). The worker validates process
identity, memory mappings and expected references before a RAM override.
A marketing/package version or matching parameter names alone is insufficient.

The parameter names and complete four-value controller state are checked at
runtime. Matching a package version or a controller version alone does not
bypass the executable and memory-layout checks.

The integrated #5/#9 filter additionally requires the exact `dji_sys`
`duss_event_send` import at RVA `58D60`, zero executable gap
`574A4..576E8`, a uniquely resolved ELF32 native export, and matching
private process mappings. It refuses unexpected code or pointer ownership.
Its own 384-byte ARM payload is bundled in the single Lab script; no
native download or compiler is required on the robot. It changes only
the app-bound copy of `3F/12` for chassis codes `C205` and `C209`.

### Release limitations

- The combined Lab installer and full stock-restoration/removal flow need an
  end-to-end hardware acceptance run. The new warning filter has passed
  13 offline native/runtime tests, in addition to the 63 existing tests;
  actual kernel cache coherence, export mapping, pause/resume latency,
  warning A/B/A, process-loss recovery and reboot remain unverified.
- The RoboMaster app indicator uses native robot telemetry. Validate it on the
  app version and platform in use; cross-platform UI coverage is incomplete.
- Motion behavior with the maintained roll-over-preserving state, real battery
  calibration, repeated load changes and long-duration operation need dedicated
  hardware acceptance.
- BMS behavior, wiring, cell ratings and regeneration are external hardware
  requirements, not properties guaranteed by passing the software checks.

See [XT30 Battery Mod](../xt30-battery/README.md) for operation and reversal.

## S1 Lab CLI

| Component | Verified baseline / gate |
|---|---|
| Host | Windows, Python 3.10+ standard library; no DJI installation or DLL required |
| Transport | Direct Python UDP Wi-Fi client and anonymous FTP; copied-folder hardware run verified on router Wi-Fi |
| Runtime service gate | `DJI SCRATCH SYS`, version bytes `00 01 00 01`, displayed as `01.00.01.00`; unknown service/version refused before upload |
| Discovery | Direct-mode candidate plus validated private IPv4 announcements on UDP 45678; explicit `--host` bypasses discovery |
| Robot | S1 model `L1860`; native Lab and root ADB verified on 29 September 2026 |
| Historical `ro.build.display.id` | `leadcore1860` |
| Historical `ro.build.version.incremental` | `eng.jenkins.20221027.033121` |

The service gate validates the observed Lab protocol, not a firmware image or
commercial package version. Model/build properties are readback evidence, not
runtime hash gates. Do not infer the root-ADB package baseline below from them.
The native service version uses its four wire bytes; it is not the older
bridge's version formatting and does not imply a firmware change.

Observed with the DLL-free client: automatic router discovery, fresh status,
upload/run/output/Idle, shell-redirected receipt reuse from a copied standalone
folder, timeout with owned-project stop and a subsequent successful run. The
root-ADB maintenance program passed in full, followed by explicit ADB root and
`L1860` verification. The existing ADB server port was preserved. The framework
can recenter the gimbal; ordinary projects remain in `/data/script/file/`.

Earlier bridge-based tests covered intentional error cleanup and Lab use while
ADB was unavailable during an AP/router/AP investigation. These remain separate
historical evidence. The bridge is no longer a dependency. See the
[verification details](../lab-cli/README.md#verification-and-limits) for source
hashes, observed native fixes and the exact boundary of hardware coverage.

The ADB program now has one maintained file in `root-adb/scripts/`. Its simplified
command handler and output preserve the tested setup sequence and bounded root
checks; failure, retry-limit and unique-address cases are verified offline.
The cleanup has no additional hardware enable cycle. The duplicate and generator
have been removed.
S1 Lab is a standalone client with no bundled robot programs; use `run FILE`
to execute a script from the relevant hack folder.

Uploads now pass the validated project bytes directly to FTP in memory, with
one completion check requiring the creation ACK and a subsequent Idle push.
Exact byte equivalence, invalid-source rejection before connection, and failure
cleanup are checked offline. This simplification has no new hardware run.

Offline: 55 Lab tests (54 pass, one optional private-parser skip); 130 repository
tests (129 pass, the same skip), plus syntax, the generated XT30 script and Windows
patch self-test. The copied-folder test blocks vendor-library loading. A
separate clean-PC installation and other host platforms have not been tested.
Fragmented control messages are refused; long output and arbitrary programs
need further validation. Native direct-mode hardware, Wi-Fi gestures, Quest
controls, FPV and driving are not validated by the router Lab tests.

## Volatile root ADB

| Robot package | Evidence | Support |
|---|---|---|
| `00.06.0515` | Stock `adb_en.sh`, root daemon and volatile TCP port observed on the robot | Supported baseline on isolated/direct-mode Wi-Fi |
| `00.06.0521` | No clean product acceptance run recorded | Unsupported until verified |

## Windows offline patch

The patch is gated by the managed assembly rather than a marketing version:

| State | `Assembly-CSharp.dll` SHA-256 |
|---|---|
| Original supported assembly | `8914F8031749CD4D08EDC556BE293783C421C918DE8B4A5FB3C9F9F6B5304371` |
| Supported offline-patched assembly | `1533520D733EAF4FBD031465784867E862760FAEF7B9E7367DD7961B076BC80E` |

The corresponding installed `RoboMaster.exe` reports file version
`2019.2.3.9328066`. That Unity version alone is not a compatibility guarantee;
the assembly hash and all expected bytes must match.

Unknown, partially patched, or vendor-updated assemblies are rejected. Restore
the original before updating or reinstalling the application.

## Android offline patch

The source-only patcher accepts the original RoboMaster Android APK 1.2.0
(versionCode 382), SHA-256
`82c86a9e77c4dbf9fb4c18660b3d0fbbfd6095c4c4b0eb03e9b2c6aae13059a1`,
and checks the ARM64/ARMv7 libraries and expected bytes before changing them.
The optional emulator verifier requires the owner's original APK and Unicorn.
Vendor APKs, extracted libraries and private audit files are not distributed.

Historical evidence covers emulator checks and installation/startup of the
privately signed revision on a Quest 3. Visual consent/menu acceptance, phone
coverage and robot functions remain unverified. See the
[Android guide](../android-offline/README.md) for exact hashes and limits.
