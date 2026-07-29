# Task 7 Report: Windows x64 Engine Package

## Scope

Implemented a Windows 10/11 x64, current-user Engine package without changing
Task 5 UI files, release versions, changelog, or public documentation.

## TDD Evidence

1. Added `tools/verify_windows_package.py` before Windows implementation.
2. Confirmed RED: `runtime manifest is missing Windows`.
3. Added pinned Windows runtime metadata and confirmed the next RED:
   `runtime manifest must support exactly the macos platform`.
4. Added Windows runtime assembly and confirmed the next RED:
   missing `packaging/windows/Install LocalTube Dub Engine.cmd.in`.
5. Added packaging/install sources and completed GREEN:
   `Windows package source verification ok`.

## Implementation

- Pins CPython 3.11.15, ffmpeg, and every Windows x64 native wheel with exact
  HTTPS URL, byte size, and SHA-256.
- Extends the existing runtime lock and installed-tree integrity contract to
  `windows/x64`, `python.exe`, and `ffmpeg.exe`.
- Builds `LocalTube-Dub-Engine-v0.2.0-Windows-x64.zip` on Windows.
- Compiles a small in-repository C# Native Messaging launcher during the
  Windows release build.
- Installs per user under
  `%LOCALAPPDATA%\LocalTube Dub\engine-runtime`.
- Registers `com.localtube.dub.engine` under HKCU for Store extension
  `ikoenamldegccnhmjjnlkffocdkbbbmo`.
- Creates a limited, current-user startup task and verifies `/api/health`.
- Supports install, repair, rollback, uninstall, and isolated dry-run paths
  containing spaces and Chinese characters.
- Uses binary stdin/stdout framing on Windows Native Messaging.
- Keeps the Kokoro model out of the Engine package.
- Fails closed before activation when the bundled runtime lock, package
  versions, artifacts, or installed-tree digest do not match.

## Local Verification

Passed on macOS:

```text
python3 tools/verify_windows_package.py --source
Windows package source verification ok

python3 scripts/assemble_engine_runtime.py --self-test --output <temporary>
{"ok": true, "selfTest": "runtime-assembly"}

python3 tools/verify_release_packages.py --self-test
{"ok": true, "selfTest": "runtime-package"}

python3 tools/verify_native_messaging.py
{"ok": true, "transport": "native", "protocolVersion": 2, ...}
```

Python compilation, `scripts/build_release_windows.py --help`, and
`git diff --check` also passed.

## Windows CI Follow-Up

The full package was intentionally not downloaded or built on macOS. Windows
CI must run:

```text
py scripts\build_release_windows.py
py tools\verify_windows_package.py --install-smoke
```

That smoke test executes the rendered PowerShell install and repair flows in a
temporary LocalAppData path with spaces and Chinese characters, starts the
packaged Engine, checks `/api/health`, verifies fail-closed behavior, and runs
the uninstaller.
