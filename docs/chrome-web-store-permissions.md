# Chrome Web Store Permission Justification

This document describes the permissions requested by LocalTube Dub and is intended to be adapted directly into the Chrome Web Store privacy and permission fields.

## Required extension permissions

### `storage`

Stores non-secret preferences such as target language, Provider, model, custom endpoint, voice, volume, and feature toggles in `chrome.storage.sync`. Chrome may synchronize those preferences when the user has Chrome Sync enabled. API keys use `chrome.storage.local` and are excluded from sync. The bounded caption cache is also local-only, expires after seven days, and can be disabled or cleared by the user.

### `nativeMessaging`

Connects to the optional LocalTube Dub desktop Engine for local yt-dlp caption extraction, whisper.cpp transcription, system TTS, Engine health, and user-triggered start/restart/install actions. Captioned videos can use the extension without installing the Engine.

The native host is installed separately by an explicit desktop installer. Its `allowed_origins` list contains only the final Chrome Web Store extension ID; wildcards are not used.

### `activeTab`

Allows a user click on the extension toolbar to authorize the current YouTube tab when no-caption compatibility recording is required. The extension does not use `activeTab` for background browsing or unrelated sites.

## Required host permissions

### `https://www.youtube.com/*` and `https://youtube.com/*`

Injects the translation/dubbing panel on YouTube watch pages and reads current-video caption tracks. Same-origin YouTube caption and player requests are used only to resolve the active video's subtitle timeline.

### `http://127.0.0.1/*` and `http://localhost/*`

Communicates with the optional local Engine on the user's own computer for caption extraction, transcription, TTS, complete-track rendering, downloads, and health checks. These origins never refer to a remote LocalTube Dub server.

## Optional host permissions

### `https://*/*`

Supports user-selected cloud translation/transcription Providers and custom HTTPS OpenAI-compatible endpoints. This optional declaration is not granted at installation. The popup derives the exact origin for the selected service, for example `https://api.deepseek.com/*`, and requests only that origin from a direct user action. Permission denial leaves the previous settings in place and prevents the request. The background worker checks the exact permission again before transmitting captions or audio.

Local HTTP custom endpoints are limited to `localhost` and `127.0.0.1`, which are already covered by the required local Engine hosts. Insecure remote HTTP endpoints are rejected.

## Optional extension permissions

### `tabCapture`

Requested only when the user enables “无字幕时自动转写”. It records a short, user-triggered audio window only when the active YouTube video has no usable captions and direct current-player audio capture is unavailable. It is not used for captioned videos or passive recording.

### `offscreen`

Requested together with `tabCapture` for the same opt-in workflow. It hosts the temporary MediaRecorder required by Chrome's Manifest V3 service worker model during the tab-audio fallback. The offscreen document has no visible UI and is closed after recording.

If the user denies these optional permissions, the setting is not saved and the extension does not attempt tab-audio capture. Existing-caption translation, target-language YouTube captions, local caption extraction, and direct current-player recording remain separate paths.

## Permissions deliberately not requested

- No `downloads` permission: subtitle files use object URLs and local Engine audio files are downloaded from a fresh user click.
- No browsing-history, cookies, identity, geolocation, clipboard, notifications, or all-tab access.
- No remote HTTP wildcard permission.

## Data-flow summary

Target-language YouTube captions and Chrome on-device translation do not require a third-party AI host. When the user selects a cloud Provider, only the caption text or explicitly enabled no-caption audio is sent to the exact Provider origin the user authorized. API keys are never exposed to the YouTube page.

The default Microsoft natural-online speech mode is implemented by the separately installed Engine and sends only the translated text being spoken, selected voice, and rate settings to Microsoft text-to-speech. Choosing the local system voice stops this online speech transfer.

The optional Engine may let yt-dlp read the local Chrome YouTube session only after public caption access fails. Those credentials are used solely for a request back to YouTube for the active video and are never sent to LocalTube Dub or an AI Provider.

## Chrome Web Store privacy-field mapping

- **Website content:** YouTube caption text and active-video player state are required for translation and synchronization.
- **Web history / activity:** the active YouTube URL and video ID are handled only after the user opens or invokes LocalTube Dub on YouTube.
- **Authentication information:** user-entered Provider API keys are stored locally and sent only to the chosen Provider.
- **User activity:** play, pause, seek, playback speed, and current position are handled to keep dubbing synchronized.
- **Audio:** a bounded active-video segment is handled only after the user enables no-caption transcription.

The dashboard declarations, public privacy policy, store description, and extension behavior must remain consistent for every release.
