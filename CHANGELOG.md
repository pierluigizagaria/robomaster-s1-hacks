# Changelog

## Unreleased

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
