# Chrome Web Store Listing Draft

## Name

LocalTube Dub

Chrome Web Store Item ID: `ikoenamldegccnhmjjnlkffocdkbbbmo`

## Short description

Translate YouTube captions and play synchronized dubbing with free local tools or your own AI key.

## Single purpose

Translate, transcribe when necessary, and play synchronized dubbing for the active YouTube video.

## Detailed description

LocalTube Dub adds a translation and dubbing panel to YouTube. It prefers an existing target-language YouTube caption track, translates source captions only when needed, and synchronizes translated subtitles and speech with video playback.

The default translation option uses Chrome's on-device Translator API and does not require an API key. Users can instead connect their own Microsoft Translator, Google Cloud Translation, OpenAI, Gemini, Claude, DeepSeek, OpenRouter, or compatible API account.

Features available in this release:

- Direct use of an existing target-language YouTube caption track when available.
- Chrome on-device caption translation with downloadable local language packs.
- Optional bring-your-own-key translation and transcription Providers.
- Synchronized translated subtitle overlay and voice playback.
- Microsoft natural online voices without a separate TTS API key, or local system voices for private on-device speech.
- Local, bounded caption caching with a visible disable and clear control.
- SRT and WebVTT caption export.
- Complete M4A or WAV voice-track rendering for complete caption timelines.
- Optional local no-caption transcription with whisper.cpp.

The separate open-source LocalTube Dub Engine is recommended for reliable yt-dlp caption extraction, natural or system speech generation, local transcription, and complete audio export. Chrome extensions cannot install native software silently, so Engine installation is a separate, explicit user action. Basic page-caption translation can work without the Engine when YouTube exposes a readable caption track and Chrome supports the required language pair.

No-caption transcription is opt-in. Local mode processes audio on the user's computer. Users who select Groq, Deepgram, or OpenAI transcription send a bounded active-video audio segment directly to that Provider with their own key.

The extension has no LocalTube Dub account, subscription, advertising, analytics, or managed translation backend. API keys remain in local Chrome extension storage and are sent only to the Provider selected by the user.

Current limitations:

- The public companion installer must match the Chrome Web Store extension version and extension ID.
- Local no-caption transcription requires the separate Engine, FFmpeg, whisper.cpp, and a local model.
- Mixed audio export attenuates the original track but does not separate dialogue from background sound.
- Final video muxing and voice cloning are not included.

LocalTube Dub is open-source software and is not affiliated with, sponsored by, or endorsed by Google, YouTube, Microsoft, or the listed AI Providers.

## Category

Productivity

## Language

Chinese (Simplified) for the first listing, followed by an English localization.

## Required listing assets

- 128 x 128 store icon.
- At least one 1280 x 800 screenshot, up to five.
- 440 x 280 small promotional tile.
- Optional 1400 x 560 marquee tile.
- Optional public YouTube demonstration video.

Screenshots must show the shipping `0.1.98` UI and must not contain API keys, private videos, account information, or unavailable features.

## Publisher URLs

- Homepage: `https://kk-kingkong.github.io/video-dub/`
- Source repository: `https://github.com/Kk-kingkong/video-dub`
- Privacy policy: `https://kk-kingkong.github.io/video-dub/privacy-policy.html`
- Support page: `https://kk-kingkong.github.io/video-dub/support.html`
- Matching signed Engine download page and checksum, when the Engine is publicly distributed.

## Reviewer instructions

1. Test first with a public YouTube video that has captions and select Chrome local translation.
2. Confirm that a target-language YouTube track is used directly when available.
3. Confirm that cloud host permission is requested only after selecting a cloud Provider.
4. Test Engine-only features with the signed companion installer matching the submitted extension ID and version.
5. Enable no-caption transcription only for the separate opt-in capture/local transcription test.

Provide the reviewer with public test video URLs, the matching Engine installer URL and checksum, and exact fresh-profile steps. Do not provide a personal API key in listing text or screenshots.
