# Engine Failure Lightweight Fallback Design

## Goal

Keep the existing Engine-backed experience as the normal path while allowing a
customer to continue watching with translated dubbing when the companion Engine
is missing, incompatible, offline, or unable to synthesize speech.

The fallback is temporary. It must not overwrite the customer's saved
translation Provider, speech engine, voice, transcription, or export settings.

## Runtime Profiles

The YouTube content runtime has two effective profiles:

- `full`: use the customer's saved settings and all available Engine features.
- `lightweight`: use page-readable YouTube captions, Chrome on-device
  translation, and browser `speechSynthesis`.

`full` remains the default for every new playback operation. Lightweight mode
is an in-memory override for the current page session, not a persisted customer
mode.

## Activation Policy

Lightweight mode activates only for an Engine capability failure:

- the Engine or Native Messaging host is not installed;
- the Engine is offline or its health request times out;
- the Engine version or protocol is incompatible;
- the selected Engine-backed speech capability is unavailable; or
- an Engine-backed TTS request fails because the Engine transport is
  unavailable.

These conditions do not activate lightweight mode:

- YouTube caption rate limiting;
- a private, unavailable, age-restricted, or region-restricted video;
- a confirmed video with no public captions;
- a readable caption track that happens to be empty; or
- a translation Provider authentication or quota error unrelated to Engine
  availability.

The classification lives in a deterministic helper rather than scattered
regular expressions in UI event handlers.

## Caption Flow

In full mode, the existing page-first and Engine-fallback caption strategy is
unchanged.

In lightweight mode:

1. Read caption metadata and caption content from the active YouTube page.
2. Prefer a readable target-language track, including a YouTube-translated
   target-language track.
3. Otherwise select the best readable source-language track.
4. Do not call the local caption Engine or wait for yt-dlp.
5. If no readable page track exists, stop cleanly and explain that lightweight
   mode requires public YouTube captions.

No-caption Whisper transcription remains an Engine feature and is unavailable
inside lightweight mode.

## Translation Flow

A target-language YouTube track bypasses translation exactly as it does in full
mode.

Source captions in lightweight mode always use Chrome on-device translation.
The customer's saved Provider remains unchanged and is restored automatically
when the next full-mode operation begins. If Chrome Translator is unavailable
or its language pack cannot be prepared, playback continues without dubbing and
the customer receives a short actionable message.

## Speech Flow

Lightweight speech uses the page's `window.speechSynthesis` API directly. It
selects an available voice matching the target-language prefix, preferring a
local voice and then another browser-exposed matching voice. It never sends a
TTS request to the Engine.

The existing subtitle timeline, pause, resume, seek, playback-rate, duplicate
suppression, and segment boundary behavior remain in control. Browser speech is
cancelled when an operation stops or becomes stale.

This internal browser-speech fallback is cross-platform. It does not change the
existing customer-selectable `macOS system speech` option or make that manual
option visible on unsupported platforms.

## Customer Experience

When fallback activates, show one persistent, non-technical notice:

> Engine 暂不可用，已切换免安装轻量模式：Chrome 翻译 + 系统配音。本次播放有效。

Raw Native Messaging, HTTP, process, port, and stack-trace details remain
available only in developer logs.

The Engine status area identifies the effective lightweight session and offers
the existing start, restart, and help actions. An additional `重试完整模式`
action clears the temporary fallback, rechecks Engine health, and restarts the
current operation only when recovery succeeds.

Engine-only transcription, Kokoro model management, and full-track export
controls are disabled while lightweight mode is active, with concise
lightweight-mode explanations.

## Recovery

The runtime override is cleared when:

- the customer explicitly retries full mode and Engine health succeeds;
- the active video changes;
- the YouTube page runtime is recreated; or
- the extension is reloaded.

Every new playback operation begins by reconsidering Engine health. A previous
temporary failure therefore cannot permanently keep a recovered installation in
lightweight mode.

The saved configuration is never rewritten during activation or recovery.

## Error Handling

Only Engine capability and transport failures may cross the lightweight
activation boundary. Content failures and YouTube service pressure retain their
existing retry and cooldown behavior.

If Microsoft natural speech fails for a content-specific reason while Engine
health remains good, the existing bounded same-provider retry and per-segment
skip policy remains unchanged. It does not silently change the whole session to
browser speech.

## Test Strategy

Add deterministic tests for:

- Engine error classification, including negative cases for YouTube rate
  limits, no captions, and Provider authentication errors;
- temporary runtime-profile activation without saved-setting mutation;
- page-only caption resolution in lightweight mode;
- target-language YouTube caption reuse without translation;
- forced Chrome translation for source captions;
- browser speech selection and the absence of Engine TTS requests;
- one customer-facing fallback notice without raw transport details;
- disabled Engine-only controls;
- explicit and next-operation recovery; and
- release metadata and changelog synchronization for version `0.2.1`.

Run the complete JavaScript verification suite, Python Engine verification,
open-source compliance verification, release-package verification, and a manual
Chrome smoke test covering full-mode failure, lightweight playback, and
full-mode recovery.

## Release Scope

Release `0.2.1` adds only automatic temporary lightweight fallback and its
customer-facing state. It does not remove Engine support, change the normal
default path, add a manually persisted lightweight setting, or change the
external data disclosures for existing Providers.
