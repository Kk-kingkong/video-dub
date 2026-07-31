# Engine Failure Lightweight Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release LocalTube Dub `0.2.1` with a temporary, customer-visible lightweight playback profile that uses YouTube page captions, Chrome on-device translation, and browser system speech whenever the companion Engine is unavailable.

**Architecture:** Add pure runtime-profile and failure-classification helpers to `content_helpers.js`, then keep one in-memory effective profile in `content.js`. Full mode keeps the existing behavior; lightweight mode bypasses Engine caption and TTS messages without mutating saved settings. Existing browser speech playback is reused, while UI rendering reflects the temporary profile and offers a bounded full-mode retry.

**Tech Stack:** Chrome Manifest V3, JavaScript content scripts, Chrome Translator API, Web Speech API, Node deterministic verification scripts, Python release/compliance verification.

## Global Constraints

- Full mode remains the default for every new playback operation.
- Lightweight mode is temporary and must never persist over customer settings.
- Lightweight captions come only from the active YouTube page.
- Lightweight source-caption translation always uses Chrome on-device translation.
- Lightweight speech always uses browser `speechSynthesis` and never calls Engine TTS.
- YouTube rate limiting, no-caption results, restricted videos, empty tracks, and Provider authentication failures must not activate lightweight mode.
- Raw Native Messaging, HTTP, port, process, and stack-trace errors must not appear in customer fallback copy.
- Existing customer-selectable `macOS system speech` remains macOS-only.
- Release version is `0.2.1`, with synchronized changelog and release metadata.

---

### Task 1: Pure Lightweight Runtime Policy

**Files:**
- Modify: `extension/content_helpers.js`
- Test: `tools/verify_extension_flows.js`

**Interfaces:**
- Produces: `createRuntimeProfile(settings, mode)` returning `{ mode, provider, ttsEngine, useCaptionEngine, useEngineTts, allowTranscription, allowFullTrackExport }`.
- Produces: `lightweightFallbackDecision(input)` returning `{ activate, reason }`.
- Produces: `isLightweightProfile(profile)` returning a boolean.

- [ ] **Step 1: Write failing policy tests**

Add assertions that define the profile without mutating the original settings:

```js
const saved = Object.freeze({
  provider: "deepseek",
  ttsEngine: "edge",
  allowAudioTranscription: true
});
const lightweight = helpers.createRuntimeProfile(saved, "lightweight");
assert.deepEqual(lightweight, {
  mode: "lightweight",
  provider: "chrome-translator",
  ttsEngine: "browser",
  useCaptionEngine: false,
  useEngineTts: false,
  allowTranscription: false,
  allowFullTrackExport: false
});
assert.equal(saved.provider, "deepseek");
assert.equal(saved.ttsEngine, "edge");
```

Add positive decisions for `CAPTION_ENGINE_UNAVAILABLE`, `ENGINE_TIMEOUT`,
`ENGINE_UPGRADE_REQUIRED`, `TTS_ENGINE_UNAVAILABLE`, and missing Edge TTS
capability. Add negative decisions for `YOUTUBE_RATE_LIMITED`,
`NO_PUBLIC_CAPTIONS`, `CAPTION_EMPTY`, `VIDEO_UNAVAILABLE`,
`AUTHENTICATION_FAILED`, and quota errors.

- [ ] **Step 2: Run the focused verification and confirm RED**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: FAIL because `createRuntimeProfile` and
`lightweightFallbackDecision` are not exported.

- [ ] **Step 3: Implement the minimal pure helpers**

Add a fixed Engine failure-code allowlist and build a fresh effective profile:

```js
const LIGHTWEIGHT_ENGINE_FAILURE_CODES = new Set([
  "CAPTION_ENGINE_UNAVAILABLE",
  "ENGINE_NOT_INSTALLED",
  "ENGINE_TIMEOUT",
  "ENGINE_UPGRADE_REQUIRED",
  "TTS_ENGINE_UNAVAILABLE",
  "EDGE_TTS_UNAVAILABLE"
]);

function createRuntimeProfile(settings = {}, mode = "full") {
  if (mode === "lightweight") {
    return {
      mode: "lightweight",
      provider: "chrome-translator",
      ttsEngine: "browser",
      useCaptionEngine: false,
      useEngineTts: false,
      allowTranscription: false,
      allowFullTrackExport: false
    };
  }
  return {
    mode: "full",
    provider: String(settings.provider || "chrome-translator"),
    ttsEngine: String(settings.ttsEngine || "edge"),
    useCaptionEngine: true,
    useEngineTts: true,
    allowTranscription: Boolean(settings.allowAudioTranscription),
    allowFullTrackExport: true
  };
}
```

`lightweightFallbackDecision` must prefer a normalized explicit code and use a
small transport-error matcher only when no code is supplied. It must explicitly
reject content and Provider error codes before checking error text.

- [ ] **Step 4: Run the focused verification and confirm GREEN**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: PASS.

- [ ] **Step 5: Commit the policy boundary**

```bash
git add extension/content_helpers.js tools/verify_extension_flows.js
git commit -m "Add lightweight runtime fallback policy"
```

---

### Task 2: Temporary Session Profile And Page-Only Captions

**Files:**
- Modify: `extension/content.js`
- Test: `tools/verify_extension_flows.js`

**Interfaces:**
- Consumes: `createRuntimeProfile`, `isLightweightProfile`, and
  `lightweightFallbackDecision` from Task 1.
- Produces: `state.runtimeProfile`, `state.engineHealth`, and
  `activateLightweightMode(failure)`.
- Produces: `resolveEffectiveProvider()` and
  `resetRuntimeProfileForOperation()`.

- [ ] **Step 1: Write failing content-flow guards**

Read `extension/content.js` in `verify_extension_flows.js` and require:

```js
assert.match(content, /runtimeProfile:\s*createRuntimeProfile\(DEFAULT_SETTINGS,\s*"full"\)/);
assert.match(content, /function activateLightweightMode\(/);
assert.match(content, /function resetRuntimeProfileForOperation\(/);
assert.match(content, /if\s*\(!state\.runtimeProfile\.useCaptionEngine\)/);
assert.match(content, /resolveEffectiveProvider\(\)\s*===\s*"chrome-translator"/);
```

Also reject assigning lightweight effective values into saved settings:

```js
assert.doesNotMatch(content, /state\.settings\.(provider|ttsEngine)\s*=\s*["'](?:chrome-translator|browser)["']/);
```

- [ ] **Step 2: Run verification and confirm RED**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: FAIL on the missing runtime-profile wiring.

- [ ] **Step 3: Add runtime state and activation lifecycle**

Initialize:

```js
runtimeProfile: createRuntimeProfile(DEFAULT_SETTINGS, "full"),
engineHealth: { checked: false, ok: false, code: "", payload: null },
lightweightNoticeShown: false,
```

`resetRuntimeProfileForOperation()` recreates a full profile from
`state.settings`, clears the notice flag, and never sends
`localtube.setSettings`.

`activateLightweightMode(failure)` must:

1. call `lightweightFallbackDecision`;
2. leave state unchanged when `activate` is false;
3. cancel queued Engine voice work and active Engine audio;
4. set an in-memory lightweight profile;
5. render the effective UI state; and
6. show the approved notice once.

`refreshEngineStatus()` records a normalized health result for later playback.
Before Engine-specific Microsoft consent, Kokoro readiness, caption, or
transcription checks, a new operation resets to full mode and immediately
reapplies lightweight mode when the latest health result proves that the Engine,
the protocol, or the selected Engine-backed TTS capability is unavailable.
Call reset when the active video changes and the content runtime remounts.

- [ ] **Step 4: Bypass Engine caption resolution in lightweight mode**

In `resolveVideoCaptions`, complete the page attempt and return it directly when
`useCaptionEngine` is false:

```js
if (!state.runtimeProfile.useCaptionEngine) {
  const pageResult = await withTimeoutResult(
    pageResultPromise,
    CAPTION_TOTAL_TIMEOUT_MS,
    "页面字幕读取超时"
  );
  return pageResult?.status === "captions"
    ? pageResult
    : {
        status: pageResult?.status || "unknown",
        cues: [],
        track: null,
        code: pageResult?.code || "LIGHTWEIGHT_CAPTIONS_UNAVAILABLE",
        error: "免安装轻量模式需要当前视频提供公开的 YouTube 字幕。"
      };
}
```

Do not invoke Whisper when `allowTranscription` is false. Reuse a readable
target-language YouTube track without translation.

- [ ] **Step 5: Force only the effective translation Provider**

Add:

```js
function resolveEffectiveProvider() {
  return state.runtimeProfile.provider || state.settings.provider;
}
```

Use it for translation decisions, Provider labels, timeline cache identity, and
background batch translation. Do not mutate or save `state.settings.provider`.

- [ ] **Step 6: Run verification and confirm GREEN**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: PASS, including existing caption ordering and cache tests.

- [ ] **Step 7: Commit session and caption behavior**

```bash
git add extension/content.js tools/verify_extension_flows.js
git commit -m "Use page captions in temporary lightweight sessions"
```

---

### Task 3: Browser Speech Playback And Automatic Engine Failure Activation

**Files:**
- Modify: `extension/content.js`
- Test: `tools/verify_extension_flows.js`

**Interfaces:**
- Consumes: `state.runtimeProfile` and `activateLightweightMode` from Task 2.
- Produces: `usesBrowserSpeechProfile()` and
  `handleEngineVoiceFailure(error, segment, generation)`.

- [ ] **Step 1: Add failing speech-path verification**

Require the lightweight branch before Engine prefetch and synthesis:

```js
assert.match(content, /if\s*\(usesBrowserSpeechProfile\(\)\)\s*\{\s*speakSegmentWithBrowserTts/);
assert.match(content, /if\s*\(!state\.runtimeProfile\.useEngineTts\)\s*\{\s*return null/);
assert.match(content, /activateLightweightMode\(\{\s*code:\s*"TTS_ENGINE_UNAVAILABLE"/);
```

Require the lightweight branch to call the existing browser-speech lifecycle,
which already owns cancellation after stop and seek, and reject a
`localtube.synthesizeSpeech` call inside that branch.

- [ ] **Step 2: Run speech verification and confirm RED**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: at least one FAIL because full and lightweight speech are not yet
separated.

- [ ] **Step 3: Route lightweight voice directly to browser speech**

Add:

```js
function usesBrowserSpeechProfile() {
  return isLightweightProfile(state.runtimeProfile);
}
```

In `maybeSpeakVoiceSegment`, call `speakSegmentWithBrowserTts` immediately for
the lightweight profile. In `scheduleVoicePrefetchWindow`,
`prewarmVoiceAroundTime`, `beginVoiceEngineWarmup`, `getVoiceSegmentAudio`, and
`requestVoiceSegmentAudio`, return without Engine work when
`useEngineTts` is false.

Browser voice selection continues to prefer a matching local voice and then a
matching browser-exposed voice. The saved Microsoft/Kokoro voice ID remains
untouched; lightweight selection passes `auto` to `pickBrowserVoice`.

- [ ] **Step 4: Activate fallback only for Engine TTS transport failures**

When full-mode synthesis exhausts its existing bounded retry, classify the
response code/error. If it is an Engine capability failure:

```js
const activated = activateLightweightMode({
  code: response?.code || "TTS_ENGINE_UNAVAILABLE",
  error: response?.error || error?.message
});
if (activated) {
  speakSegmentWithBrowserTts(segment, playbackGeneration);
  return;
}
```

Content-specific Microsoft failures keep the existing same-provider
per-segment skip policy and must not activate a session-wide fallback.

- [ ] **Step 5: Run speech verification and confirm GREEN**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: PASS with no duplicate browser speech and no Engine TTS request in
lightweight mode.

- [ ] **Step 6: Commit lightweight speech**

```bash
git add extension/content.js tools/verify_extension_flows.js
git commit -m "Fall back to browser speech when Engine is unavailable"
```

---

### Task 4: Customer Notice, Disabled Controls, And Full-Mode Retry

**Files:**
- Modify: `extension/content.js`
- Modify: `extension/content.css`
- Test: `tools/verify_extension_flows.js`

**Interfaces:**
- Consumes: `activateLightweightMode` and `resetRuntimeProfileForOperation`.
- Produces: `renderRuntimeProfileState()` and `retryFullModeFromWidget()`.

- [ ] **Step 1: Write failing UI-state verification**

Require the approved copy and retry action:

```js
assert.match(content, /Engine 暂不可用，已切换免安装轻量模式：Chrome 翻译 \+ 系统配音。本次播放有效。/);
assert.match(content, /data-action="retry-full-mode"/);
assert.match(content, /async function retryFullModeFromWidget\(/);
assert.doesNotMatch(content, /轻量模式[^\\n]*(Native|HTTP|127\\.0\\.0\\.1|端口|stack)/i);
```

Require a `.is-lightweight` status style and control disabling tied to the
runtime profile.

- [ ] **Step 2: Run verification and confirm RED**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: FAIL because the notice and retry action do not exist.

- [ ] **Step 3: Render one non-technical lightweight state**

Add a hidden `重试完整模式` button to the Engine actions. When lightweight mode
is active:

- set the Engine status box to `is-lightweight is-warn`;
- use only the approved customer notice;
- show the retry action;
- disable Kokoro model actions, local transcription preparation, and full-track
  export;
- keep subtitle export available after captions load; and
- leave saved Provider and voice selects displaying the customer's choices.

Tooltips for disabled Engine-only actions say:

```text
免安装轻量模式暂不支持此功能
```

- [ ] **Step 4: Implement bounded full-mode retry**

`retryFullModeFromWidget()` performs one `localtube.captionEngineHealth` request.
On success it clears the temporary profile, refreshes Engine/voice state, stops
the current lightweight operation, and starts the current video again in full
mode. On failure it keeps lightweight playback available and shows:

```text
Engine 暂未恢复，继续使用免安装轻量模式。
```

It must not loop and must not save settings.

- [ ] **Step 5: Run verification and confirm GREEN**

Run:

```bash
node tools/verify_extension_flows.js
```

Expected: PASS.

- [ ] **Step 6: Commit the customer experience**

```bash
git add extension/content.js extension/content.css tools/verify_extension_flows.js
git commit -m "Show and recover temporary lightweight mode"
```

---

### Task 5: Version 0.2.1, Documentation, And Release Verification

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `companion/README.md`
- Modify: `docs/development-audit.md`
- Modify: `extension/manifest.json`
- Modify: `extension/popup.html`
- Modify: `extension/release-info.json`
- Modify: `scripts/build_release_windows.py`
- Modify: `tools/verify_extension_flows.js`
- Modify: `tools/verify_open_source_compliance.py`
- Modify: `tools/verify_windows_package.py`
- Modify: `docs/release-process.md`

**Interfaces:**
- Consumes: completed lightweight behavior from Tasks 1-4.
- Produces: synchronized extension and Engine release identity `0.2.1`.

- [ ] **Step 1: Change release assertions to 0.2.1 and confirm RED**

Update only test expectations first:

```js
assert.equal(manifest.version, "0.2.1");
```

```python
EXPECTED_VERSION = "0.2.1"
```

Update Windows package verification constants to
`LocalTube-Dub-Engine-v0.2.1-Windows-x64.zip` and expected Engine version
`0.2.1`.

Run:

```bash
node tools/verify_extension_flows.js
python3 tools/verify_open_source_compliance.py
python3 tools/verify_windows_package.py --source
```

Expected: FAIL on current `0.2.0` metadata.

- [ ] **Step 2: Synchronize production release metadata**

Set manifest, popup fallback text, release info, Windows builder constants,
current README status, companion package examples, development audit, and
release-process commands to `0.2.1`. Do not rewrite historical changelog,
historical specs, or historical plans.

Add the changelog entry:

```markdown
## 0.2.1 - 2026-07-31

- Added automatic temporary lightweight mode when the companion Engine is unavailable.
- Lightweight mode uses readable YouTube page captions, Chrome on-device translation, and browser system speech without changing saved settings.
- Added a clear customer notice and one-click full-mode retry while keeping YouTube rate limits, no-caption results, and Provider errors outside the Engine-failure fallback.
```

- [ ] **Step 3: Run complete deterministic verification**

Run:

```bash
node tools/verify_extension_flows.js
node tools/verify_provider_registry.js
python3 tools/verify_local_engine.py
python3 tools/verify_native_messaging.py
python3 tools/verify_open_source_compliance.py
python3 tools/verify_release_packages.py --self-test
python3 tools/verify_windows_package.py --source
```

Expected: all PASS.

- [ ] **Step 4: Build and verify the local release candidate**

Run with the permanent Store extension ID and public release page:

```bash
LOCAL_DUB_RELEASE_CHANNEL=private-beta \
LOCAL_DUB_ENGINE_DOWNLOAD_URL=https://github.com/Kk-kingkong/video-dub/releases \
LOCAL_DUB_SUPPORT_URL=https://kk-kingkong.github.io/video-dub/support.html \
./scripts/build_release_macos.sh ikoenamldegccnhmjjnlkffocdkbbbmo
```

Verify the generated extension ZIP and host-architecture Engine ZIP:

```bash
python3 tools/verify_release_packages.py \
  dist/LocalTube-Dub-extension-v0.2.1.zip \
  dist/LocalTube-Dub-Engine-v0.2.1-macOS-arm64.zip \
  ikoenamldegccnhmjjnlkffocdkbbbmo \
  0.2.1
```

Expected: PASS with licenses, release-info, package identity, runtime lock, and
checksums validated.

- [ ] **Step 5: Perform manual Chrome smoke**

Use the built ZIP in a clean Chrome profile and verify:

1. normal Engine-backed caption and Microsoft speech playback;
2. Engine stop followed by automatic lightweight notice;
3. readable YouTube captions translated with Chrome and spoken by browser
   speech;
4. no raw Engine error in customer UI;
5. saved Provider and Microsoft voice unchanged;
6. Engine restart plus `重试完整模式` returns to Microsoft speech; and
7. a YouTube rate-limit/no-caption result does not claim Engine failure.

- [ ] **Step 6: Commit the release candidate**

```bash
git add CHANGELOG.md README.md README.zh-CN.md companion/README.md docs/development-audit.md docs/release-process.md extension/manifest.json extension/popup.html extension/release-info.json scripts/build_release_windows.py tools/verify_extension_flows.js tools/verify_open_source_compliance.py tools/verify_windows_package.py
git commit -m "Release lightweight Engine fallback 0.2.1"
```
