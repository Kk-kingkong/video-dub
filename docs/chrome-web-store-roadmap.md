# Chrome Web Store Roadmap

Recommended product architecture:

1. Chrome Web Store extension
   - Injects the YouTube UI.
   - Presents one customer workflow: free Chrome translation or the user's own API key.
   - Reads caption tracks.
   - Reads current-video tracks from the live page, embedded player response, or a same-origin YouTube player request so captioned BYOK users do not require the optional desktop Engine.
   - Uses rolling local Engine audio windows when a video has no captions, with short current-player/tab capture as fallback.
   - Synchronizes translated subtitles and audio playback.
   - Translates through the user's selected AI provider using BYOK.
   - Optionally talks to LocalTube Dub Engine through Native Messaging.

2. BYOK provider router
   - Uses Chrome's built-in desktop Translator API as the free, no-key default when supported.
   - Supports OpenAI, Gemini, Claude, DeepSeek, OpenRouter, and custom OpenAI-compatible endpoints.
   - Supports separate transcription providers: Groq Whisper, Deepgram Nova, OpenAI Whisper, and local Engine Whisper.
   - Stores API keys in `chrome.storage.local`.
   - Never sends API keys to the YouTube content script.
   - Uses the user's selected transcription provider key for BYOK no-caption audio transcription.

3. LocalTube Dub Engine
   - Installed separately as a desktop companion app.
   - Runs local Ollama, Whisper CLI, and TTS adapters.
   - The macOS developer installer registers a login LaunchAgent; a signed public installer must preserve the same no-Terminal startup behavior from a stable application path.
   - Optional for users who want fully local processing.

4. Store listing and compliance
   - Explain that video captions are sent to the user's chosen provider in BYOK mode.
   - Explain that local Engine mode processes captions on the user's computer.
   - Keep installation permissions limited to YouTube, storage, Native Messaging, and active-tab activation. Request tab recording/offscreen permissions only after the user enables no-caption transcription.
   - Provide a privacy policy that matches actual behavior.
   - Provide reviewer instructions with a test API provider and optional Engine installer.
   - Publish the Apache-2.0 source, privacy policy, support process, security policy, and third-party notices.

## Release phases

### Phase 1: Developer preview

- BYOK provider router works with OpenAI-compatible APIs.
   - No-caption local mode transcribes rolling yt-dlp audio windows; Groq, Deepgram, OpenAI, and compatibility fallback use current-player/tab capture.
- Native Messaging host remains available with the unpacked extension.
- HTTP localhost fallback remains available for debugging.
- Browser speech synthesis remains the temporary TTS layer.

### Phase 2: Private beta

- Add provider presets and first-run language-pack/API-key onboarding.
- Versioned Web Store extension ZIP and an ID-bound macOS Engine bootstrap ZIP with double-click install/uninstall are implemented; signing and notarization remain required for public distribution.
- Add Windows installer support.
- Add an in-extension first-run checklist.
- Add a caption cache and translation history controls.
- Publish an unlisted build from the same future production item; unlisted visibility still receives normal policy review.

### Phase 3: Store-ready MVP

- Default mode is BYOK so most users only install the extension and paste a key.
- Keep accounts, subscriptions, payments, advertising, and a managed LocalTube backend out of the open-source release.
- Finalize Chrome Web Store extension ID.
- Update Engine installers with the final ID in `allowed_origins`.
- Add privacy policy and support page.
- Add reviewer test instructions.
- Replace rough Browser TTS with a local TTS adapter when possible.

### Phase 4: Full dubbing

- SRT/WebVTT export from the prepared translated timeline is implemented.
- One-shot local full-video no-caption transcription is implemented with a cancellable audio-only Engine job.
- Synchronized pure-voice generation, optional full-original-audio mixing, and M4A/WAV delivery are implemented with a cancellable Engine job.
- Add source-speech/background separation and final video muxing.
- Add voice selection and timing controls.
- Add per-cue audio generation.
- Add quality fallback for long videos.
