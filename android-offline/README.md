# Original RoboMaster APK without login

Last updated: October 5, 2026.

The patch targets the original RoboMaster Android app on Android phones and
Meta Quest 3, separately from the Godot controller. It retains the DJI app's
Android interface and the `com.dji.robomaster` package; on Quest it does not
become an OpenXR app.

## Artifact and status

- Current APK: `android-offline/build/RoboMaster-1.2.0-offline-r2.apk`.
- Original version: 1.2.0, versionCode 382; ARM64 and ARMv7 in the same APK.
- Size: 426,557,899 bytes.
- SHA-256: `CF19708A115AEFEA23E61246DD543C9831A4E156E5DC70E41474BBAE1AAD3D1E`.
- Local debug-key signature, v1/v2/v3 schemes verified; alignment verified.
- Eight Python tests PASS, covering ARM64/ARMv7 transitions and ARM64/Thumb
  bootstrap execution in Unicorn.
- Full comparison of 6,469 payload entries before signing: the two
  `libil2cpp.so` and two `libbaiduprotect.so` files change; signed APK audit in
  `android-offline/build/signed-apk-audit-r2.json`.
- **R2 installed as an update on Quest 3 on September 28, 2026**, with a
  matching `base.apk` hash and no further data reset. First launch at
  21:05:31 CEST, wake from sleep at 21:06:22: Unity initialized and the
  `ViewLoginAndRegister` scene loaded, with the process remaining alive
  without SIGABRT. Visual verification, completion of consent/menu flow,
  phone testing and robot functions still require testing. The capture of
  the Quest physical display is black and does not establish which screen
  appeared in the headset.

## Behavior

Startup uses the local privacy choice instead of account status. If the
privacy notice has already been accepted, it opens the menu. On a fresh
installation, it preserves the original scene displaying the notice; its
update waits for the user's choice and then proceeds to the menu without
authentication. The remote token check on menu entry is removed. An invalid
token and logout lead to the menu. No tokens, profiles or login flags are
fabricated, and the privacy notice is not accepted automatically.

The initial privacy notice remains in the DJI `LoginAndRegister` scene: the
login screen may appear briefly during that transition. Device testing must
verify dialog order, completion of the first launch, restarting without a
network and initialization of robot services. The patch does not enable
online features that require an account.

Unlike the Windows patch, Android already uses `persistentDataPath` for local
data: no paths are changed. The manifest, resources, IL2CPP metadata, DEX,
robot libraries and assets remain identical to the original.

### Startup crash fix (r2)

The first APK, `C35EE0A2…9EABDE60`, could be installed but failed on first
launch: `XOX: state=526` followed by SIGABRT within about two seconds,
reproduced via ADB. The Baidu bootstrap compares the certificate with DJI's.
An intermediate test with only the certificate check adapted produced
`state=527` for the rebuilt ZIP entries. R2 modifies three local checking
functions (certificate, entry digests, ZIP inventory) in each ABI. It
preserves class loading, privacy consent and Android signature verification.
The patcher checks the source, libraries and entire payload before signing.
The patched APK is not authenticated by DJI.

The ARM64 functions are at RVAs `0x22C68`, `0x2307C`, `0x237E4`; the Thumb
functions are at `0x17D0C`, `0x18030`, `0x1852C`. The bootstrap code is stored
with inverted bytes: the patches target the corresponding file locations.
The tests reproduce this transformation and verify return behavior, stack
and registers. Logs of the reproduced failures and R2 startup are in
`android-offline/build/crash-20260928/`; no robot tests were performed.

## Private reproduction

`android-offline/scripts/patch_original_android_offline.py` uses only the
Python 3.11+ standard library. It requires a local copy of the original APK and
checks the entire APK's SHA-256, library hashes and bytes at every modified
location. It rejects other versions, already modified inputs and existing
outputs. It does not overwrite the original.

```powershell
python android-offline/scripts/patch_original_android_offline.py `
  "<ORIGINAL_APK>" `
  android-offline/build/RoboMaster-1.2.0-offline-r2-unsigned.apk

python android-offline/scripts/verify_original_android_offline.py `
  "<ORIGINAL_APK>"

$buildTools = '<ANDROID_SDK>/build-tools/36.1.0'
& "$buildTools/zipalign.exe" -p 4 `
  android-offline/build/RoboMaster-1.2.0-offline-r2-unsigned.apk `
  android-offline/build/RoboMaster-1.2.0-offline-r2-aligned.apk
java -jar "$buildTools/lib/apksigner.jar" sign `
  --ks <DEBUG_KEYSTORE> --ks-key-alias androiddebugkey `
  --ks-pass pass:android --key-pass pass:android `
  --out android-offline/build/RoboMaster-1.2.0-offline-r2.apk `
  android-offline/build/RoboMaster-1.2.0-offline-r2-aligned.apk
java -jar "$buildTools/lib/apksigner.jar" verify --verbose `
  android-offline/build/RoboMaster-1.2.0-offline-r2.apk
& "$buildTools/zipalign.exe" -c -p 4 `
  android-offline/build/RoboMaster-1.2.0-offline-r2.apk
```

The private tests require Unicorn and the local APK, without a robot. They
simulate reading consent and entering Unity functions: they verify
instructions, branches, stack integrity and registers, not Android/Unity
operation. Method and address analysis was performed with
[Il2CppDumper 6.7.46](https://github.com/Perfare/Il2CppDumper/releases/tag/v6.7.46)
and Capstone disassembly; dumps and binaries are under
`android-offline/build/private_reference/`, ignored by Git.

Source APK SHA-256:
`82C86A9E77C4DBF9FB4C18660B3D0FBBFD6095C4C4B0EB03E9B2C6AAE13059A1`.
Details of offsets, before/after instructions and library hashes are in
`android-offline/build/patch-report-r2.json`. Test and signing logs are in
the same directory. The apksigner warnings about AndroidX
`META-INF/*.version` files concern the JAR v1 scheme; v2/v3 verification of
the complete APK passes.

## Initial installation and data preservation

The local debug-key signature differs from DJI's: the APK cannot directly
update a DJI-signed copy. Initial installation therefore requires replacing
the existing app and clears any internal preferences that cannot be backed
up. On the test headset, the DJI 1.2.0/382 copy was uninstalled and the offline
copy installed. The Godot package `com.robomaster.questcontroller` was not
modified.

Before replacement, the previous APK (with a hash identical to the source
APK) and all 3,067 external files, totaling 145,658,593 bytes, were
saved. All external files were restored with matching individual hashes.
Pushing the directories via ADB encountered `secure_mkdirs`; restoration
succeeded using a tar archive extracted from the shell, then removed from
the Quest temporary directory. Internal preferences could not be read
(`run-as` denied, app not debuggable) and were cleared during replacement. No
dialog was accepted.

Backup and per-file audit: `android-offline/build/private_reference/quest-before-install/`.
Installation log: `android-offline/build/quest-install.log`.
Final audit: `android-offline/build/quest-installed-apk-audit.json`:
matching APK hash, external data restored, `stopped=true`, `notLaunched=true`,
no RoboMaster process. **PASS for deployment only.**

The subsequent R2 uses `adb install --no-incremental -r` with the same
local debug-key signature: no uninstall and no second preference reset.
Current audit: `android-offline/build/quest-installed-apk-audit-r2.json`.

Follow-up testing on Quest and, after installation, on the phone: privacy
choice, menu access without credentials, restarting without Internet and
logout; then separate verification of robot functions. Testing this app
does not validate the Godot controller.
