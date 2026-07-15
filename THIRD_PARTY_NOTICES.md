# Third-Party Notices

LocalTube Dub source code is licensed under Apache-2.0. The project integrates with or can install software and services that retain their own licenses and terms.

## Optional local dependencies

| Component | Purpose | License / terms |
| --- | --- | --- |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | YouTube caption metadata and audio-only extraction | Unlicense |
| [curl-cffi](https://github.com/lexiforest/curl_cffi) | Optional TLS/browser impersonation used by yt-dlp | MIT |
| [edge-tts](https://github.com/rany2/edge-tts) | Optional Microsoft Edge online speech client | LGPL-3.0 |
| [whisper.cpp](https://github.com/ggerganov/whisper.cpp) | Optional local speech transcription | MIT |
| [FFmpeg](https://ffmpeg.org/) | Audio conversion, fitting, mixing, and export | LGPL/GPL depending on the installed build |
| [Ollama](https://github.com/ollama/ollama) | Optional local translation adapter | Upstream license and model-specific terms |

These components are not vendored into the Chrome extension ZIP. The companion installer downloads or calls them separately. Model files used with Whisper or Ollama may have additional licenses.

## External platforms and services

The extension can communicate with YouTube, Chrome's on-device Translator API, Microsoft Edge text-to-speech, and user-selected translation or transcription providers. Those products are governed by their respective terms and privacy policies. Their names identify compatibility only and do not imply endorsement.

LocalTube Dub is not affiliated with, sponsored by, or endorsed by Google, YouTube, Microsoft, OpenAI, Anthropic, DeepSeek, Groq, Deepgram, OpenRouter, or Ollama.
