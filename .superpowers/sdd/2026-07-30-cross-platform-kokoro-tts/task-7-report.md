# Task 7 Report: Windows x64 Engine Package

## Scope

Implemented and reviewed the Windows 10/11 x64 per-user Engine package without
changing Task 8 CI/docs/extension files. The package remains bound to Store ID
`ikoenamldegccnhmjjnlkffocdkbbbmo`, uses pinned offline runtime artifacts,
fails closed on runtime-integrity errors, and does not bundle a Kokoro model.

## Review Fixes

- Added one shared `manage-engine.ps1` lifecycle for installer, Scheduled Task,
  uninstaller, and Native Host launches.
- Uses quoted `.NET ProcessStartInfo` startup and quoted Scheduled Task
  arguments for paths containing spaces and Chinese characters.
- Replaced trusted PID termination with an atomic JSON instance record plus
  exact executable path, quoted server command, and loopback-listener ownership
  verification. Stale/reused PIDs are ignored; listener discovery recovers
  installer, Task Scheduler, and Native Host launches.
- Serializes concurrent lifecycle operations with a per-port Windows mutex.
- Engine health now exposes version, protocol, platform, architecture,
  `instanceId`, and `runtimeRoot`. Install/start accepts only version `0.2.0`,
  protocol `2`, Windows x64, the expected runtime, the newly launched instance,
  a live process, and that process's listener.
- Replaced the dry-run Windows smoke with a real temporary-LocalAppData flow:
  HKCU registration, limited per-user Scheduled Task, installer launch, stale
  PID recovery, Scheduled Task launch, compiled Native Messaging launch,
  repair, post-activation rollback, fail-closed preflight, uninstall, and
  guaranteed verified cleanup.

## TDD Evidence

1. Strengthened `tools/verify_windows_package.py` first.
2. Confirmed RED:
   `Native Host does not use the shared Windows Engine lifecycle manager`.
3. Implemented shared lifecycle and exact identity checks; confirmed the next
   RED:
   `Windows install smoke does not exercise Get-ScheduledTask`.
4. Replaced the dry-run smoke with real per-user assertions.
5. Added concurrent lifecycle verification; confirmed RED:
   `lifecycle manager does not serialize concurrent Task/installer/Native Host operations`.
6. Added the named mutex and reached GREEN:
   `Windows package source verification ok`.

## Final Local Verification

Passed on macOS without package downloads:

```text
python3 tools/verify_windows_package.py --source
Windows package source verification ok

python3 -m py_compile companion/native_host.py server/local_dub_server.py \
  scripts/build_release_windows.py tools/verify_windows_package.py

python3 scripts/assemble_engine_runtime.py --self-test --output <temporary>
{"ok": true, "selfTest": "runtime-assembly"}

python3 tools/verify_release_packages.py --self-test
{"ok": true, "selfTest": "runtime-package"}

python3 tools/verify_native_messaging.py
{"ok": true, "transport": "native", "engineVersion": "0.2.0", ...}
```

Template rendering with all placeholders removed and `git diff --check` also
passed.

## Windows Re-Review Gate

The real install smoke cannot execute on macOS because it requires Windows
HKCU, Scheduled Tasks, the bundled Windows runtime, and the compiled `.exe`
launcher. Re-review on Windows x64 must run:

```text
py scripts\build_release_windows.py
py tools\verify_windows_package.py --install-smoke
```

The smoke uses unique HKCU Native Host and Scheduled Task fixtures under a
temporary LocalAppData tree and removes them in a `finally` cleanup path.
