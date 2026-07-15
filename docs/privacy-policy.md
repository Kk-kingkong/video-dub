---
layout: default
title: LocalTube Dub Privacy Policy
---

# LocalTube Dub Privacy Policy

**Effective date:** July 15, 2026

[Home](index.html) | [Support](support.html) | [Source code](https://github.com/Kk-kingkong/video-dub)

LocalTube Dub is an open-source Chrome extension that translates, transcribes, and dubs the active YouTube video. It has no LocalTube Dub account system, advertising, analytics, payment processing, or hosted translation service.

This policy covers the Chrome extension and the optional LocalTube Dub Engine installed on the same computer.

## Data the extension handles

To provide its single purpose, LocalTube Dub may handle:

- the URL and video ID of the active YouTube video;
- YouTube caption tracks and caption text;
- playback position, duration, speed, play/pause state, and selected target language;
- user preferences such as Provider, model, voice, volume, custom Provider endpoint, and feature toggles;
- API keys entered for a user-selected translation or transcription Provider;
- short current-video or current-tab audio captured only after the user enables no-caption transcription; and
- generated transcripts, translated caption timelines, and synthesized speech.

LocalTube Dub does not use this data for advertising, profiling, credit decisions, or sale to third parties.

## Storage on the user's device

Non-secret preferences are stored with `chrome.storage.sync`. If the user has Chrome Sync enabled, Chrome may synchronize those preferences through the user's Google account. API keys are excluded from sync and stored only in `chrome.storage.local`.

The optional caption cache is also stored in `chrome.storage.local`. It may contain the YouTube video ID, language identifiers, caption text, translated text, cue timestamps, and the Provider/model identity used for an AI translation. It does not contain video, audio, cookies, or API keys. Cache entries expire after seven days and are limited to 12 timelines or approximately 4 MB. Users can disable caching or select **Clear caption cache** at any time.

Removing the extension clears its Chrome extension storage. The optional desktop Engine keeps runtime files, logs, models, and user-requested exports separately on the computer. Its uninstall command removes the runtime; the `--purge` option also removes Engine caches and logs. Local Whisper models are retained unless the user deletes them.

## YouTube captions and active-video requests

The extension communicates with YouTube only for the active video. It first uses caption information already available to the current page, then may request the active video's caption or player data from YouTube. It does not monitor unrelated browsing pages.

When the optional Engine uses yt-dlp, it first attempts public caption access. If YouTube requires authentication or a bot check, the Engine may ask yt-dlp to read the local Chrome YouTube session and send the necessary request back to YouTube for the active video. YouTube cookies are not sent to LocalTube Dub, AI Providers, or Microsoft text-to-speech. Advanced users can disable browser-cookie fallback with the Engine setting documented in `README.md`.

## Translation modes

### Chrome on-device translation

When **Chrome local translation** is selected, translation is performed by Chrome's on-device Translator API. LocalTube Dub does not send caption text to a third-party translation Provider in this mode. Chrome may download the required language pack.

### User-selected API Provider

When a user selects a cloud Provider, the extension sends caption text directly to that Provider's authorized HTTPS origin using the API key supplied by the user. Supported choices include Microsoft Translator, Google Cloud Translation, OpenAI, Gemini, Claude, DeepSeek, OpenRouter, and a user-configured OpenAI-compatible endpoint.

Cloud hosts are optional Chrome permissions. The extension requests access only after a direct user choice, derives the exact origin for the selected Provider, and checks that permission again before transmitting data. Provider requests are governed by the selected Provider's terms and privacy policy.

### Local translation

When an optional local translator such as Ollama is selected, caption text is sent only to the loopback Engine or the local Ollama endpoint on the same computer.

## Videos without captions

No-caption transcription is disabled unless the user enables it. Local transcription sends an audio-only segment to the loopback Engine, where whisper.cpp and FFmpeg process it on the same computer.

If a user selects Groq, Deepgram, or OpenAI transcription, the captured audio segment is sent directly to that selected Provider with the user's API key. If direct player capture is unavailable, the extension may request optional `tabCapture` and `offscreen` permissions and record a bounded portion of the active YouTube tab. It does not record background tabs or unrelated sites.

## Speech generation

The default **Microsoft natural online** speech mode sends only the translated subtitle text being spoken, the selected voice, and speech-rate settings through the companion Engine to Microsoft Edge's text-to-speech service. It does not send the source video, captured audio, API keys, YouTube cookies, or unrelated browsing history.

Selecting **local system voice** generates speech with the operating system's local speech service and stops sending subtitle text to Microsoft text-to-speech. Chrome browser speech may be used as a local playback fallback when Engine speech is unavailable.

## Local Engine communication

The Chrome extension communicates with the optional Engine through Chrome Native Messaging or the loopback addresses `127.0.0.1` and `localhost`. LocalTube Dub does not operate a remote Engine server. Temporary media used by local transcription or rendering is deleted when processing completes; user-requested exported audio remains until the user deletes it.

## Sharing, retention, and legal requests

LocalTube Dub does not sell user data. Data is transferred only as necessary to provide the feature and mode explicitly selected by the user, to comply with law, or to address a security issue. LocalTube Dub does not retain a server-side copy because it does not operate a hosted backend.

The public project, privacy, and support pages are hosted by GitHub Pages. GitHub may process visitor information, including IP-address logs, under the [GitHub Privacy Statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement). LocalTube Dub does not add analytics or advertising trackers to these pages.

Third-party Providers and platforms may retain requests under their own policies. Users should review the terms of YouTube, Chrome, Microsoft text-to-speech, and any API Provider they select.

## User controls

Users can:

- choose Chrome on-device translation instead of a cloud translation Provider;
- choose local system speech instead of Microsoft natural online speech;
- keep no-caption transcription disabled;
- deny optional Provider, tab capture, or offscreen permissions;
- disable or clear the caption cache;
- clear saved API keys from the extension popup;
- remove the Chrome extension; and
- uninstall or purge the optional Engine using the supplied uninstall command.

## Children

LocalTube Dub is a general-purpose developer tool and is not directed to children. It does not knowingly collect children's personal information.

## Changes

Material privacy changes will be documented in `CHANGELOG.md`, reflected in this policy, and submitted with the corresponding Chrome Web Store update when required.

## Contact

Open a [support or privacy issue](https://github.com/Kk-kingkong/video-dub/issues/new/choose) in the public source repository. For a vulnerability or a report containing sensitive information, use the repository's [private vulnerability-reporting process](https://github.com/Kk-kingkong/video-dub/security/policy).
