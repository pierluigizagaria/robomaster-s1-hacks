# Contributing

RoboMaster S1 Hacks accepts focused changes that help owners maintain
their robots after vendor services, applications, or consumables become
unavailable.

## Scope

- Each mod or tool must remain user-facing, reversible, and
  compatibility-gated.
- Keep captures, exploratory probes, device dumps, and unfinished hardware work
  out of this public repository.
- Do not describe a result as supported until it has repeatable hardware
  evidence and a documented recovery path.
- Do not commit DJI binaries, extracted proprietary assets, device dumps,
  credentials, account data, serial numbers, or raw logs that may contain them.

## Pull requests

Keep each change narrow. Document the exact hardware and software version used,
what was observed directly, what is inferred, and how the original state can be
restored. Update compatibility and safety documentation whenever behavior at a
hardware boundary changes.

Run the offline checks before opening a pull request:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\run.ps1
```

Hardware results should include commands, non-sensitive output, hashes of local
inputs where appropriate, and an explicit statement of which safety controls
were in place. Never include a secret key or a vendor binary as evidence.
