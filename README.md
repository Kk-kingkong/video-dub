# LocalTube Dub

[简体中文](README.zh-CN.md) | English

An open-source Chrome extension that translates YouTube captions into Chinese and plays synchronized Chinese dubbing.

LocalTube Dub prefers an existing Chinese YouTube caption track. When Chinese captions are unavailable, it can use Chrome's free on-device Translator or a translation Provider chosen by the user. Videos without captions can use the optional local Whisper Engine.

> **Status:** `0.1.98` developer preview. The Chrome Web Store release and signed desktop Engine installer are being prepared.

## Highlights

- Reuses existing Chinese YouTube captions before calling a translation service.
- Supports Chrome on-device translation with no API key.
- Supports user-provided Microsoft, Google, OpenAI, Gemini, Claude, DeepSeek, OpenRouter, and compatible API keys.
- Synchronizes translated subtitles and generated speech with play, pause, seek, and playback speed.
- Provides Microsoft natural online voices and private macOS system voices.
- Supports optional local no-caption transcription with yt-dlp, FFmpeg, and whisper.cpp.
- Exports translated subtitles as SRT/WebVTT and complete voice tracks as M4A/WAV.
- Stores API keys locally and contains no LocalTube account, advertising, analytics, or payment system.

## How it works

1. Use a readable Chinese caption track supplied by YouTube.
2. Otherwise translate source captions with Chrome on-device translation or the user's selected Provider.
3. If the video has no captions, optionally transcribe a bounded audio segment with local Whisper or the user's transcription Provider.
4. Present translated captions and speech on the original video timeline.

## Try the source build

1. Open `chrome://extensions` in Chrome.
2. Enable **Developer mode**.
3. Select **Load unpacked** and choose the `extension/` directory.
4. Open a YouTube video, choose a target language, and click **Start translation**.

The companion Engine is optional for basic page-caption translation and recommended for reliable yt-dlp caption extraction, natural/local TTS, no-caption transcription, and audio export. See [companion setup](companion/README.md).

## Privacy

- Non-secret preferences can use Chrome Sync.
- API keys and caption caches remain in local extension storage.
- Cloud requests go only to the Provider explicitly selected by the user.
- Microsoft natural speech receives only the translated text and voice settings required for synthesis.
- Local system speech and local Whisper processing remain on the user's computer.

Read the public [privacy policy](https://kk-kingkong.github.io/video-dub/privacy-policy.html) and [permission explanation](docs/chrome-web-store-permissions.md).

## Development checks

```bash
node tools/verify_extension_flows.js
node tools/verify_provider_registry.js
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_local_engine.py
PYTHONPYCACHEPREFIX=/private/tmp/localtube-pycache python3 tools/verify_native_messaging.py
python3 tools/verify_open_source_compliance.py
```

## Documentation

- [中文说明](README.zh-CN.md)
- [Project site](https://kk-kingkong.github.io/video-dub/)
- [Support](https://kk-kingkong.github.io/video-dub/support.html)
- [Engine setup](companion/README.md)
- [Privacy policy](docs/privacy-policy.md)
- [Chrome Web Store permissions](docs/chrome-web-store-permissions.md)
- [Release process](docs/release-process.md)
- [Changelog](CHANGELOG.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## Current limitations

- The public macOS Engine installer is not yet signed or notarized.
- A production Windows Engine installer is not yet available.
- Mixed audio export does not separate original dialogue from background sound.
- Final video muxing and voice cloning are not included.

## License

Apache-2.0. See [LICENSE](LICENSE) and [third-party notices](THIRD_PARTY_NOTICES.md).

LocalTube Dub is not affiliated with, sponsored by, or endorsed by Google, YouTube, Microsoft, or any supported AI Provider. Users are responsible for applicable platform terms, copyright rules, voice consent, and local law.
