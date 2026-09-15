# Compatibility matrix

Last updated: **15 September 2026**

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

### Release limitations

- The combined Lab installer and full stock-restoration/removal flow need an
  end-to-end hardware acceptance run.
- The RoboMaster app indicator uses native robot telemetry. Validate it on the
  app version and platform in use; cross-platform UI coverage is incomplete.
- Motion behavior with the maintained roll-over-preserving state, real battery
  calibration, repeated load changes and long-duration operation need dedicated
  hardware acceptance.
- BMS behavior, wiring, cell ratings and regeneration are external hardware
  requirements, not properties guaranteed by passing the software checks.

See [XT30 Battery Mod](../xt30-battery/README.md) for operation and reversal.

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
