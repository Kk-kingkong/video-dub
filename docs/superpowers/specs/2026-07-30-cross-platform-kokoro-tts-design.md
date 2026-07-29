# Cross-Platform Kokoro TTS Design

## Objective

Add an optional high-quality offline Kokoro dubbing engine to LocalTube Dub without weakening the existing Microsoft natural-online experience, subtitle synchronization, Chrome Web Store compliance, or local-only privacy promise.

The release target is `0.2.0`. It must support macOS on Intel and Apple Silicon plus Windows 10/11 x64. Linux remains source-installable, but a Linux one-click installer is outside this release.

## User-Facing Voice Engines

The UI exposes these engines in this order:

1. `Microsoft 自然在线（默认）`: cross-platform, network required, no API key.
2. `Kokoro 高质量本地`: cross-platform, offline after an explicit one-time model installation.
3. `macOS 系统配音（仅限 macOS）`: offline fallback shown only when the connected Engine reports macOS.

Selecting Kokoro never silently sends subtitle text to Microsoft. Selecting Microsoft keeps the existing natural-online behavior. Windows must not present macOS system speech as an available choice; a previously synced `system` value is normalized to Microsoft until the user installs and selects Kokoro.

## Architecture

The Chrome extension remains Manifest V3 HTML, CSS, and JavaScript. It does not download or execute remote JavaScript, WebAssembly, Python, native libraries, or arbitrary commands.

The separately installed LocalTube Dub Engine owns all local TTS execution:

- A pinned Python runtime, `sherpa-onnx`, and all executable dependencies ship inside the versioned desktop Engine package for its target platform and architecture.
- The Kokoro multilingual INT8 model is downloaded only after a user action.
- The model URL, archive layout, expected files, version, and SHA-256 digest are fixed in reviewed Engine source.
- The Engine downloads to a staging directory, rejects redirects outside HTTPS, validates archive paths and the digest, then atomically activates the model.
- Model files are treated as data. Runtime code is never updated through the model installer.

The existing extension-to-service-worker-to-Engine request path remains unchanged. `ttsEngine` gains a `kokoro` value, and the Engine health response becomes the source of truth for platform, runtime readiness, model state, installation progress, and available voices.

## Engine API

`GET /api/health` and Native Messaging health responses add:

- `platform`: `macos`, `windows`, or `linux`.
- `architecture`: normalized CPU architecture.
- `kokoroRuntime`: whether the bundled runtime can load.
- `kokoroModel`: `not-installed`, `installing`, `ready`, `failed`, or `incompatible`.
- `kokoroModelVersion`, `kokoroModelBytes`, and `kokoroInstallProgress`.
- Provider-scoped voice records with stable IDs, display names, locale, gender label when supplied by the model, and a preferred fallback ID.

Model management uses explicit Engine operations:

- `localtube.installKokoroModel`
- `localtube.getKokoroModelStatus`
- `localtube.cancelKokoroModelInstall`
- `localtube.uninstallKokoroModel`

The HTTP equivalents are loopback-only endpoints under `/api/tts-model/kokoro`. Native Messaging and HTTP validate the same command schema. Only the fixed Kokoro model can be managed; callers cannot supply a URL, path, package name, shell command, or checksum.

Speech synthesis continues through `localtube.synthesizeSpeech`. A successful Kokoro response reports `requestedVoice`, `actualVoice`, `voiceFallback`, audio duration, and synthesis timing.

## Model Lifecycle And Resources

The default Kokoro package is the multilingual Chinese/English INT8 model. The installer displays the download size and installed size before confirmation.

The Engine follows these resource limits:

- Do not load Kokoro until the user selects it and requests speech.
- Use at most two inference threads and one concurrent Kokoro synthesis job.
- Reuse one loaded model across queued segments.
- Keep the extension prefetch window bounded to the current segment plus the next two segments.
- Reuse the existing bounded audio cache.
- Cancel queued work on stop, navigation, video replacement, or engine change.
- Unload the model after five idle minutes when there is no queued work.

Playback never waits for an unbounded model queue. A late segment follows the existing time-box policy and is skipped instead of delaying subsequent segments.

## Voice Failure And Fallback

Kokoro voice selection is provider-scoped. The UI lists a curated set of Chinese voices first while preserving stable access to all compatible model voices.

If synthesis fails for the selected voice:

1. Retry once with the selected voice.
2. Retry the same text once with that locale's preferred Kokoro fallback voice.
3. If fallback succeeds, display `当前音色不可用，已切换为 <voice>` and persist the actual Kokoro voice for later segments.
4. If the Kokoro runtime or model fails, pause dubbing, restore original audio, and show repair or reinstall actions.

Kokoro never automatically switches to Microsoft because that would turn a local-only choice into an undisclosed network transfer. It never switches to macOS system speech because that would change both provider and voice quality. Microsoft mode retains its current bounded retry behavior. macOS system mode retains its browser/system recovery behavior.

## Extension UI

Both the popup and YouTube overlay show the same engine choices and provider-scoped voices.

When Kokoro is selected:

- `安装本地模型` is shown when no model exists.
- Installation progress, cancel, retry, and uninstall controls use the Engine status response.
- The start button remains disabled until the model is ready.
- A compact resource note says that the model uses local disk, memory, and CPU only while selected.

When the Engine reports Windows or Linux, the macOS system option is absent. When the Engine is disconnected, it remains absent rather than guessing the operating system.

Model installation requires an already installed desktop Engine. If no Engine is connected, the extension opens the official Engine installation/support page; Chrome does not install native software directly.

## macOS Distribution

Separate macOS Engine packages support Intel and Apple Silicon with the same installation flow. Each installer:

- bundles an architecture-matched private Python runtime, pinned `sherpa-onnx`, and executable dependencies so the customer does not need Homebrew or a preinstalled Python;
- includes the reviewed Kokoro model manifest but not the large model archive;
- preserves the current LaunchAgent and Native Messaging registration;
- reports whether Microsoft, Kokoro, macOS system speech, yt-dlp, and Whisper are ready.

The public customer package must be Developer ID signed and notarized before it is described as a one-click public installer.

## Windows Distribution

The Windows package includes:

- `Install LocalTube Dub Engine.cmd` as the user entry point;
- a PowerShell installer using the current user's Local AppData directory;
- a bundled Windows x64 embeddable Python runtime with pinned `sherpa-onnx` and executable dependencies;
- a loopback Engine startup task registered for the current user;
- the Native Messaging manifest plus the required `HKCU` Chrome registry key;
- start, restart, health-check, repair, and uninstall commands.

No administrator permission is required. The installer must handle spaces and non-ASCII user-profile paths, use binary stdio for Native Messaging, bind `allowed_origins` to the production extension ID, and leave no machine-specific paths in distributable source archives.

The Windows package is built and tested in a Windows GitHub Actions runner. Public distribution requires code signing, but unsigned development ZIPs may be used only for documented private testing.

## Security, Privacy, And Store Compliance

- The extension keeps its existing `nativeMessaging` permission and does not add Chrome permissions.
- The Store single purpose remains translating and dubbing the active YouTube video.
- The privacy policy states that Kokoro and macOS system speech process text locally, while Microsoft mode sends only synthesis text and voice settings to Microsoft.
- Model download is explicit, cancellable, version-pinned, integrity-checked, and removable.
- Model and runtime licenses are recorded in `THIRD_PARTY_NOTICES.md`.
- Store copy and reviewer instructions disclose the optional desktop Engine and model installation.
- The extension package contains no remotely hosted executable logic.

## Testing

Deterministic tests cover:

- `kokoro` settings sanitization and persistence;
- platform-dependent visibility of macOS system speech;
- health and model-state normalization;
- fixed model manifest and checksum enforcement;
- archive traversal and unexpected-file rejection;
- install, cancel, retry, uninstall, and atomic activation;
- one-job/two-thread resource limits and idle unload;
- selected-voice retry, same-provider fallback, user notification, and persisted actual voice;
- prohibition of Kokoro-to-Microsoft or Kokoro-to-system fallback;
- synthesis response metadata and existing timing/cache integration;
- Windows Native Messaging registry generation and binary stdio;
- macOS Intel/ARM and Windows x64 package metadata;
- Manifest V3, permissions, privacy, release-package, and secret scans.

The macOS test suite runs locally. GitHub Actions adds a Windows runner for installer dry runs, Native Messaging protocol tests, Engine health, Kokoro model smoke synthesis, and uninstall cleanup. A release is not ready until both platform jobs pass.

## Acceptance Criteria

- A user on supported macOS or Windows can install the matching Engine without administrator privileges.
- The extension offers Microsoft, Kokoro, and only-on-macOS system speech exactly as specified.
- A user can install the pinned Kokoro model from the extension after the Engine is present and synthesize Chinese speech without a network connection.
- Kokoro playback uses existing semantic segments, caching, rate fitting, and video synchronization.
- A selected Kokoro voice failure switches only to a disclosed Kokoro fallback voice.
- Resource limits prevent unbounded concurrent synthesis or background model use.
- Generated extension, macOS Engine, and Windows Engine packages pass platform, security, compliance, and checksum verification for version `0.2.0`.
