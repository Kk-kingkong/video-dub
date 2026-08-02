# Cross-Platform Kokoro TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship LocalTube Dub `0.2.0` with an optional offline Kokoro Chinese/English voice engine, macOS-only system speech, and one-click macOS Intel/ARM plus Windows x64 Engine packages.

**Architecture:** Keep Manifest V3 extension logic self-contained and route all executable TTS work through the existing loopback/Native Messaging Engine. Add a focused `server/kokoro_tts.py` module for pinned model management, lazy sherpa-onnx inference, resource limits, and same-provider voice fallback; expose it through the existing HTTP/Native protocols and thin extension controls.

**Tech Stack:** Chrome Manifest V3 JavaScript, Python 3.10+, sherpa-onnx/ONNX Runtime, standard-library HTTP and WAV handling, macOS LaunchAgent, Windows PowerShell/Task Scheduler/HKCU Native Messaging, Node and Python deterministic verification.

## Global Constraints

- Release version is `0.2.0`.
- Supported packaged platforms are macOS Intel, macOS Apple Silicon, and Windows 10/11 x64.
- Engine choices are Microsoft natural online, Kokoro high-quality local, and macOS system speech only on macOS.
- Kokoro never falls back to Microsoft or macOS system speech.
- Kokoro selected-voice failure may switch only to a disclosed same-language Kokoro voice.
- Kokoro uses at most two inference threads, one synthesis job, two prefetched future segments, and a five-minute idle unload.
- The extension downloads no executable logic and adds no Chrome permissions.
- The Engine accepts no caller-supplied model URL, path, checksum, package, or command.
- Runtime packages and model data are version-pinned and integrity-checked.
- Existing uncommitted `0.1.99` natural-online fallback fixes must remain intact.

---

### Task 1: Kokoro Model Manifest And Safe Local State

**Files:**
- Create: `server/kokoro_tts.py`
- Create: `tools/verify_kokoro_engine.py`
- Modify: `tools/verify_local_engine.py`

**Interfaces:**
- Produces: `KokoroModelManager(root: Path, manifest: dict | None = None)`.
- Produces: `KokoroModelManager.status() -> dict[str, Any]`.
- Produces: `KokoroModelManager.install(fetcher=None) -> dict[str, Any]`, `cancel()`, and `uninstall()`.
- Produces: fixed `KOKORO_MODEL_MANIFEST` with `version`, `url`, `sha256`, `archiveBytes`, `installedBytes`, and `requiredFiles`.

- [ ] **Step 1: Write failing manifest and archive-safety tests**

```python
def test_model_manifest_is_fixed_and_callers_cannot_override_url(tmp_path):
    manager = kokoro.KokoroModelManager(tmp_path)
    assert manager.status()["state"] == "not-installed"
    assert manager.install_request({"url": "https://evil.invalid/model"})["code"] == "INVALID_MODEL_REQUEST"

def test_archive_traversal_is_rejected(tmp_path):
    archive = make_tar(tmp_path, {"../escape": b"x"})
    with pytest.raises(kokoro.KokoroModelError, match="unsafe archive path"):
        kokoro.extract_verified_archive(archive, tmp_path / "stage", {"model.int8.onnx"})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_kokoro_engine.py`

Expected: FAIL because `server.kokoro_tts` does not exist.

- [ ] **Step 3: Implement immutable manifest, normalized paths, status, digest verification, safe extraction, and atomic activation**

```python
KOKORO_MODEL_MANIFEST = MappingProxyType({
    "id": "kokoro-int8-multi-lang-v1_1",
    "version": "1.1-int8",
    "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_1.tar.bz2",
    "sha256": "a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6",
    "archiveBytes": 147031220,
    "requiredFiles": (
        "model.int8.onnx", "voices.bin", "tokens.txt", "lexicon-zh.txt",
        "date-zh.fst", "number-zh.fst", "phone-zh.fst",
    ),
})
```

- [ ] **Step 4: Run focused tests and local Engine checks**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_kokoro_engine.py`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_local_engine.py`

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add server/kokoro_tts.py tools/verify_kokoro_engine.py tools/verify_local_engine.py
git commit -m "Add safe Kokoro model state"
```

### Task 2: Model Install Protocol Over HTTP And Native Messaging

**Files:**
- Modify: `server/local_dub_server.py`
- Modify: `companion/native_host.py`
- Modify: `extension/background.js`
- Modify: `tools/verify_kokoro_engine.py`
- Modify: `tools/verify_native_messaging.py`
- Modify: `tools/verify_extension_flows.js`

**Interfaces:**
- Consumes: `KokoroModelManager`.
- Produces: HTTP `GET /api/tts-model/kokoro/status`.
- Produces: HTTP `POST /api/tts-model/kokoro/install|cancel|uninstall`.
- Produces: Native requests `kokoro-model-status|install-kokoro-model|cancel-kokoro-model-install|uninstall-kokoro-model`.
- Produces: extension messages `localtube.getKokoroModelStatus|installKokoroModel|cancelKokoroModelInstall|uninstallKokoroModel`.

- [ ] **Step 1: Write failing route and command-schema tests**

```python
assert native.handle_message({"type": "kokoro-model-status"})["model"]["state"] == "not-installed"
assert native.handle_message({"type": "install-kokoro-model", "payload": {"url": "x"}})["code"] == "INVALID_MODEL_REQUEST"
```

```javascript
assert.match(background, /localtube\.installKokoroModel/);
assert.match(background, /\/api\/tts-model\/kokoro\/install/);
assert.doesNotMatch(background, /payload\.(?:url|path|checksum|command)/);
```

- [ ] **Step 2: Run protocol tests and verify RED**

Run: `node tools/verify_extension_flows.js`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_native_messaging.py`

Expected: FAIL on missing model operations.

- [ ] **Step 3: Add loopback routes, Native dispatch, and background forwarding**

Model installation starts one daemon worker and returns immediately. Status reports `downloadedBytes`, `totalBytes`, `progress`, `state`, and a user-safe `error`. Concurrent install calls reuse the same job; cancel and uninstall are idempotent.

- [ ] **Step 4: Run protocol and Engine tests**

Run: `node tools/verify_extension_flows.js`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_native_messaging.py`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_kokoro_engine.py`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/local_dub_server.py companion/native_host.py extension/background.js tools/verify_kokoro_engine.py tools/verify_native_messaging.py tools/verify_extension_flows.js
git commit -m "Expose Kokoro model management"
```

### Task 3: Lazy Kokoro Synthesis And Same-Provider Voice Fallback

**Files:**
- Modify: `server/kokoro_tts.py`
- Modify: `server/local_dub_server.py`
- Modify: `tools/verify_kokoro_engine.py`
- Modify: `tools/verify_local_engine.py`

**Interfaces:**
- Produces: `KokoroRuntime.synthesize(text, language, voice_id, rate, output_path) -> dict`.
- Produces: `kokoro_voice_catalog() -> list[dict]`.
- Extends TTS payload with `requestedVoice`, `actualVoice`, `voiceFallback`, and `voiceFallbackMessage`.

- [ ] **Step 1: Write failing lazy-load, concurrency, fallback, and unload tests**

```python
def test_selected_voice_falls_back_only_within_kokoro(fake_runtime):
    fake_runtime.fail_voices.add("zf_xiaobei")
    result = service.synthesize("测试", "zh-CN", "zf_xiaobei", 1.0, output)
    assert result["requestedVoice"] == "zf_xiaobei"
    assert result["actualVoice"] == "zf_xiaoxiao"
    assert result["voiceFallback"] is True
    assert fake_runtime.providers == {"kokoro"}

def test_runtime_uses_one_job_two_threads_and_unloads_after_idle():
    assert service.max_concurrent_jobs == 1
    assert service.num_threads == 2
    clock.advance(301)
    service.release_if_idle()
    assert service.loaded is False
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_kokoro_engine.py`

Expected: FAIL because synthesis does not exist.

- [ ] **Step 3: Implement sherpa-onnx lazy runtime and WAV generation**

Use `sherpa_onnx.OfflineTtsConfig` with the activated model, `num_threads=2`, `provider="cpu"`, and one process-wide lock. Write 24 kHz mono PCM16 WAV with the standard library, then reuse existing duration fitting.

Retry the selected voice once, then one locale fallback. Never call Edge or system TTS from this path.

- [ ] **Step 4: Integrate `kokoro` into Engine sanitization, health, voices, live TTS, and full-track TTS**

```python
def sanitize_tts_engine(value):
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"edge", "kokoro", "system"} else "system"
```

- [ ] **Step 5: Run Kokoro and complete Engine verification**

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_kokoro_engine.py`

Run: `PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_local_engine.py`

Expected: both PASS without requiring a downloaded production model.

- [ ] **Step 6: Commit**

```bash
git add server/kokoro_tts.py server/local_dub_server.py tools/verify_kokoro_engine.py tools/verify_local_engine.py
git commit -m "Add offline Kokoro synthesis"
```

### Task 4: Platform-Aware Engine And Voice Settings

**Files:**
- Modify: `extension/voice_helpers.js`
- Modify: `extension/background.js`
- Modify: `extension/popup.js`
- Modify: `extension/content_helpers.js`
- Modify: `extension/content.js`
- Modify: `extension/popup.html`
- Modify: `tools/verify_extension_flows.js`

**Interfaces:**
- Produces: `normalizeTtsEngineForPlatform(ttsEngine, platform, kokoroReady)`.
- Produces: provider-scoped Kokoro voice options and macOS-only system option rendering.

- [ ] **Step 1: Write failing platform and provider tests**

```javascript
assert.equal(helpers.normalizeTtsEngineForPlatform("system", "windows", false), "edge");
assert.equal(helpers.normalizeTtsEngineForPlatform("system", "macos", false), "system");
assert.equal(helpers.normalizeTtsEngineForPlatform("kokoro", "windows", true), "kokoro");
assert.equal(helpers.normalizeTtsEngineForPlatform("kokoro", "windows", false), "kokoro");
```

Static checks require all three labels and forbid rendering the system option when platform is unknown or non-macOS.

- [ ] **Step 2: Run extension tests and verify RED**

Run: `node tools/verify_extension_flows.js`

Expected: FAIL because `kokoro` and platform policy are absent.

- [ ] **Step 3: Implement three engine options and provider-scoped voices**

Both popup and overlay use Engine health as the platform source. Kokoro remains selected while uninstalled so the UI can display its install action; only Start is disabled. A synced system value on Windows is normalized to Edge and saved.

- [ ] **Step 4: Run extension tests**

Run: `node tools/verify_extension_flows.js`

Run: `node tools/verify_provider_registry.js`

Expected: both PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/voice_helpers.js extension/background.js extension/popup.js extension/content_helpers.js extension/content.js extension/popup.html tools/verify_extension_flows.js
git commit -m "Add platform-aware Kokoro settings"
```

### Task 5: Model Controls, Resource Copy, And Playback Fallback Notice

**Files:**
- Modify: `extension/popup.html`
- Modify: `extension/popup.css`
- Modify: `extension/popup.js`
- Modify: `extension/content.js`
- Modify: `extension/content.css`
- Modify: `tools/verify_extension_flows.js`

**Interfaces:**
- Consumes: model-management background messages and Kokoro TTS response metadata.
- Produces: install/progress/cancel/retry/uninstall controls in popup and compact status in overlay.
- Produces: persistent actual Kokoro voice after a fallback response.

- [ ] **Step 1: Write failing UI wiring and fallback-notice tests**

```javascript
assert.match(popupHtml, /id="kokoroModelInstall"/);
assert.match(popup, /localtube\.installKokoroModel/);
assert.match(content, /当前音色不可用，已切换为/);
assert.match(content, /response\.payload\.actualVoice/);
assert.doesNotMatch(kokoroFailureBody, /speakSegmentWithBrowserTts|ttsEngine\\s*=\\s*"edge"/);
```

- [ ] **Step 2: Run extension tests and verify RED**

Run: `node tools/verify_extension_flows.js`

Expected: FAIL on absent model controls and notice.

- [ ] **Step 3: Implement stable controls and playback behavior**

Poll every second only while installing and every five seconds otherwise. Confirm before uninstall. Disable Start until ready. On fallback, save the returned Kokoro voice through `localtube.setSettings`, refresh voice selection, and display the notice once per changed voice.

Limit Kokoro prefetch to the active segment plus two future segments without changing Edge/system prefetch behavior.

- [ ] **Step 4: Run extension tests and syntax checks**

Run: `node tools/verify_extension_flows.js`

Run: `node --check extension/popup.js && node --check extension/content.js && node --check extension/background.js`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add extension/popup.html extension/popup.css extension/popup.js extension/content.js extension/content.css tools/verify_extension_flows.js
git commit -m "Add Kokoro model controls"
```

### Task 6: Pinned Runtime Packaging For macOS Intel And Apple Silicon

**Files:**
- Create: `packaging/runtime-manifest.json`
- Create: `scripts/assemble_engine_runtime.py`
- Modify: `scripts/build_release_macos.sh`
- Modify: `scripts/install_engine_deps_macos.sh`
- Modify: `packaging/macos/Install LocalTube Dub Engine.command.in`
- Modify: `packaging/macos/README.md.in`
- Modify: `tools/verify_release_packages.py`
- Modify: `tools/smoke_release_macos.sh`

**Interfaces:**
- Produces: `assemble_engine_runtime.py --platform macos --arch arm64|x64 --output PATH`.
- Produces: separate architecture-labeled macOS Engine ZIPs containing pinned runtime code but not the Kokoro model.

- [ ] **Step 1: Write failing package-manifest and archive checks**

Require HTTPS URLs, exact SHA-256 digests, supported architecture keys, bundled Python executable, installed sherpa-onnx metadata, model manifest, and no model archive.

- [ ] **Step 2: Run release-package checks and verify RED**

Run: `python3 tools/verify_release_packages.py --self-test`

Expected: FAIL because runtime manifest and architecture packages are absent.

- [ ] **Step 3: Add pinned runtime assembly and architecture-specific build output**

The assembly script downloads only build-time artifacts listed in `packaging/runtime-manifest.json`, verifies each digest, installs wheels into the staged private runtime, and writes `runtime-lock.json`. Customer installation copies the complete runtime and never invokes pip or Homebrew.

- [ ] **Step 4: Build and smoke-test the host architecture package**

Run: `LOCAL_DUB_SUPPORT_URL=https://kk-kingkong.github.io/video-dub/support.html ./scripts/build_release_macos.sh ikoenamldegccnhmjjnlkffocdkbbbmo`

Expected: host-architecture extension/Engine package checks and isolated installer smoke test PASS.

- [ ] **Step 5: Commit**

```bash
git add packaging/runtime-manifest.json scripts/assemble_engine_runtime.py scripts/build_release_macos.sh scripts/install_engine_deps_macos.sh packaging/macos tools/verify_release_packages.py tools/smoke_release_macos.sh
git commit -m "Bundle pinned macOS Engine runtime"
```

### Task 7: Windows x64 Engine Installer And Native Messaging

**Files:**
- Create: `packaging/windows/Install LocalTube Dub Engine.cmd.in`
- Create: `packaging/windows/install-engine.ps1.in`
- Create: `packaging/windows/uninstall-engine.ps1.in`
- Create: `scripts/build_release_windows.py`
- Create: `tools/verify_windows_package.py`
- Modify: `companion/native_host.py`
- Modify: `server/local_dub_server.py`
- Modify: `packaging/runtime-manifest.json`

**Interfaces:**
- Produces: `LocalTube-Dub-Engine-v0.2.0-Windows-x64.zip`.
- Produces: per-user runtime under `%LOCALAPPDATA%\\LocalTube Dub\\engine-runtime`.
- Produces: HKCU Native Messaging registration and per-user startup task.

- [ ] **Step 1: Write failing Windows path, registry, stdio, install, and uninstall tests**

```python
assert package.native_manifest["allowed_origins"] == [
    "chrome-extension://ikoenamldegccnhmjjnlkffocdkbbbmo/"
]
assert package.registry_root == r"HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.localtube.dub.engine"
assert "O_BINARY" in native_host_source
```

Dry-run installation uses a temporary LocalAppData path containing spaces and Chinese characters.

- [ ] **Step 2: Run Windows package verifier and verify RED**

Run: `python3 tools/verify_windows_package.py --source`

Expected: FAIL because Windows package files do not exist.

- [ ] **Step 3: Implement Windows-safe platform paths and binary Native Messaging**

Replace macOS-only cache/model defaults with `platformdirs`-style standard-library path helpers. On Windows call `msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)` and the same for stdout before Native Messaging I/O.

- [ ] **Step 4: Implement build, per-user install, repair, startup, health, and uninstall**

The staged package contains the x64 embedded runtime and pinned dependencies from the runtime manifest. PowerShell writes the Native manifest, registers HKCU, creates a current-user startup task, starts the loopback Engine, and verifies `/api/health`.

- [ ] **Step 5: Run source verifier locally and Windows CI smoke commands**

Run locally: `python3 tools/verify_windows_package.py --source`

Run in Windows CI: `py tools\\verify_windows_package.py --install-smoke`

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add packaging/windows scripts/build_release_windows.py tools/verify_windows_package.py companion/native_host.py server/local_dub_server.py packaging/runtime-manifest.json
git commit -m "Add Windows Engine package"
```

### Task 8: Cross-Platform CI, Documentation, Compliance, And `0.2.0` Release

**Files:**
- Create: `.github/workflows/cross-platform-engine.yml`
- Modify: `extension/manifest.json`
- Modify: `extension/release-info.json`
- Modify: `extension/popup.html`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `CHANGELOG.md`
- Modify: `THIRD_PARTY_NOTICES.md`
- Modify: `docs/privacy-policy.md`
- Modify: `docs/store-listing-draft.md`
- Modify: `docs/chrome-web-store-permissions.md`
- Modify: `docs/release-process.md`
- Modify: `docs/development-audit.md`
- Modify: `tools/verify_open_source_compliance.py`
- Modify: `tools/verify_extension_flows.js`

**Interfaces:**
- Produces: synchronized version `0.2.0`.
- Produces: macOS and Windows CI jobs plus verified extension/Engine packages and checksums.

- [ ] **Step 1: Write failing version, disclosure, license, and CI checks**

Require `0.2.0` everywhere; require local Kokoro processing, explicit model installation, Microsoft transfer disclosure, macOS-only system speech, sherpa-onnx/Kokoro notices, Windows review instructions, and both platform CI jobs.

- [ ] **Step 2: Run compliance checks and verify RED**

Run: `python3 tools/verify_open_source_compliance.py`

Run: `node tools/verify_extension_flows.js`

Expected: FAIL on old version and missing disclosures.

- [ ] **Step 3: Update metadata, bilingual documentation, privacy, Store copy, notices, and changelog**

Document that the model is data downloaded by the optional native Engine, not remotely hosted extension code. Do not claim unsigned development packages are signed or notarized.

- [ ] **Step 4: Add cross-platform CI and release verification**

macOS runs JS/Python checks and host-architecture installer smoke tests. Windows runs JS/Python checks, package build, Native Messaging install smoke, Kokoro fake-runtime synthesis, and uninstall cleanup.

- [ ] **Step 5: Run the complete local verification matrix**

Run:

```bash
node tools/verify_extension_flows.js
node tools/verify_provider_registry.js
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_kokoro_engine.py
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_local_engine.py
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_native_messaging.py
python3 tools/verify_windows_package.py --source
python3 tools/verify_open_source_compliance.py
node --check extension/background.js
node --check extension/content.js
node --check extension/popup.js
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 -m py_compile server/kokoro_tts.py server/local_dub_server.py companion/native_host.py
bash -n scripts/*.sh companion/*.sh
git diff --check
```

Expected: every command exits 0.

- [ ] **Step 6: Build final packages and verify checksums**

Build the Store extension, macOS host-architecture Engine package, and Windows x64 Engine package. Verify exact extension ID `ikoenamldegccnhmjjnlkffocdkbbbmo`, version `0.2.0`, archive paths, licenses, runtime locks, model exclusion, and SHA-256 files.

- [ ] **Step 7: Commit**

```bash
git add .github extension README.md README.zh-CN.md CHANGELOG.md THIRD_PARTY_NOTICES.md docs tools
git commit -m "Release cross-platform Kokoro TTS 0.2.0"
```
