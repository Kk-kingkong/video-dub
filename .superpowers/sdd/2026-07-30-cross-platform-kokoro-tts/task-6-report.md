# Task 6 Report: Pinned macOS Runtime Packages

## Outcome

- Added architecture-labelled macOS Engine packages. A local build emits only
  the host package: `LocalTube-Dub-Engine-v<VERSION>-macOS-arm64.zip` or
  `LocalTube-Dub-Engine-v<VERSION>-macOS-x64.zip`.
- Added a fixed runtime manifest and release assembler. All build artifacts use
  HTTPS with an exact byte count and SHA-256 before extraction or installation.
- The packaged Engine now includes a private CPython runtime, offline-pinned
  Python wheels, `ffmpeg`, `runtime-lock.json`, and `server/kokoro_tts.py`.
  It deliberately excludes the Kokoro model archive and activated model files.
- Customer installation validates the bundled runtime, atomically copies the
  whole package to Application Support, then registers the existing Native Host
  and LaunchAgent. It does not run pip, Homebrew, curl, or a compiler.
- Customer mode is explicit and fail-closed. Missing or damaged release
  metadata never falls through to Homebrew, pip, or another network dependency
  path. Source setup remains available only through
  `--source-development`/`LOCAL_DUB_SOURCE_DEVELOPMENT=1`.
- Runtime lock schema 2 now binds platform, architecture, exact Python version,
  the complete 19-package set, all selected artifact records, the reviewed
  Kokoro model-manifest identity, and a deterministic installed-tree SHA-256.
  `release.json` independently pins the lock-file and tree digests.
- Runtime replacement is a two-phase operation. The previous runtime remains
  available until Native Host registration and LaunchAgent health verification
  succeed. A later failure removes the failed service, restores the backup, and
  re-runs the previous runtime's registration/health path.

## Pinned Runtime

- CPython standalone: `3.11.15+20260718` from the official
  `astral-sh/python-build-standalone` release.
- Kokoro runtime: `sherpa-onnx==1.13.4` and
  `sherpa-onnx-core==1.13.4`.
- Existing Engine Python dependencies: `yt-dlp==2026.7.4`,
  `curl-cffi==0.13.0`, `edge-tts==7.2.8`, `aiohttp==3.14.1`, and their
  pinned runtime requirements recorded in `packaging/runtime-manifest.json`.
- Bundled audio executable: `ffmpeg-static b6.1.1`, matched to macOS arm64 or
  x64. The private Python startup hook makes it available to the Engine even
  when LaunchAgent supplies a minimal PATH.

## Verification

- `python3 tools/verify_release_packages.py --self-test` passed with synthetic
  archives and wheels, including HTTPS/digest, architecture normalization and
  unsafe archive checks, deterministic tree hashing, and symlink mutation.
- `python3 -m py_compile scripts/assemble_engine_runtime.py tools/verify_release_packages.py` passed.
- `bash -n scripts/build_release_macos.sh scripts/install_engine_deps_macos.sh tools/smoke_release_macos.sh` passed.
- `git diff --check` passed.
- Built and smoke-tested the host Apple Silicon package for version `0.1.99`:
  private-runtime imports, installer copy dry run, Native Host/LaunchAgent dry
  registration, isolated Engine start and health request, and uninstall dry run
  all passed. Adversarial cases also passed: a missing lock failed before
  developer tools, a tampered lock and tampered runtime tree were rejected, and
  an injected post-move failure after Native Host/LaunchAgent verification
  restored the previous runtime. No Kokoro model was downloaded.

## Concern

- The generated development/private-beta package is intentionally unsigned and
  not notarized. Do not describe it as a public one-click macOS installer until
  Developer ID signing and Apple notarization are complete.
