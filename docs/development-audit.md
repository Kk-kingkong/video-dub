# LocalTube Dub Development Audit

Last reviewed: 2026-07-23
Current reviewed version: 0.1.98

## 0.1.98 Verification Evidence

- The first Chrome Web Store draft established permanent Item ID `ikoenamldegccnhmjjnlkffocdkbbbmo`. Release documentation and compliance checks now reject a missing or different Store ID.
- Release assembly binds both the Store-candidate extension metadata and macOS Native Messaging `allowed_origins` to that exact ID while leaving the source checkout in development mode.
- Caption extraction, translation, transcription, TTS, and synchronization implementation files are unchanged from `0.1.97`.
- Open-source compliance, extension-flow, Provider-registry, local Engine, Native Messaging, JavaScript syntax, Python compilation, release-package, isolated installer, exact package-ID metadata, and SHA-256 checks pass for `0.1.98`.

## 0.1.97 Verification Evidence

- The `docs/` publishing source contains a bilingual public homepage, a privacy-safe bilingual support page, a complete privacy policy, and a minimal GitHub Pages configuration.
- README, support, release-process, and Chrome Web Store listing documents use the stable `kk-kingkong.github.io/video-dub` homepage, privacy, and support URLs plus the public `Kk-kingkong/video-dub` source repository.
- Compliance verification requires the Pages source files, direct support/security links, public Store publisher URLs, and matching `0.1.97` release metadata. Caption extraction, translation, transcription, TTS, and synchronization implementation files are unchanged from `0.1.96`.
- Open-source compliance, extension-flow, Provider-registry, local Engine, Native Messaging, JavaScript syntax, Python compilation, release-package, isolated installer, and SHA-256 checks pass for `0.1.97`.

## 0.1.96 Verification Evidence

- The repository landing page is now a concise English overview with a first-line Simplified Chinese link. `README.zh-CN.md` provides the same product, setup, privacy, limitation, documentation, and license information in Chinese.
- Detailed Engine, privacy, permission, release, contribution, and security material remains in focused linked documents instead of being repeated on the landing page.
- Compliance verification requires both README languages and matching `0.1.96` release metadata. Caption extraction, translation, transcription, TTS, and synchronization implementation files are unchanged from `0.1.95`.
- Open-source compliance, extension-flow, Provider-registry, local Engine, Native Messaging, Python compilation, release-package, isolated installer, and runtime byte-identity checks pass for `0.1.96`.

## 0.1.95 Verification Evidence

- Apache-2.0 licensing, contribution guidance, security reporting, support, community conduct, third-party notices, and GitHub issue/pull-request templates are present at the repository root.
- The privacy policy now matches the implementation: non-secret settings use Chrome sync, API keys and bounded caption timelines use local extension storage, no-caption audio is opt-in, the Engine can use Chrome YouTube cookies only for an active-video request back to YouTube, and Microsoft natural speech receives only the text and voice settings needed for synthesis.
- The store draft describes one implemented purpose and does not advertise a LocalTube account, subscription, payment system, analytics, advertising, or managed translation backend. It discloses the separate Engine and current platform/release requirements.
- Permission and release documents cover exact optional Provider origins, optional tab capture, localhost/Native Messaging, final extension-ID binding, signing/notarization, public HTTPS pages, reviewer instructions, listing assets, and fresh-profile acceptance tests.
- Runtime caption extraction, translation, transcription, TTS, and playback synchronization files are unchanged from `0.1.94`; this release changes repository governance, public documentation, release metadata, and deterministic compliance checks only.
- Generated extension and Engine ZIP files both carry `LICENSE` and `THIRD_PARTY_NOTICES.md`; release verification rejects either artifact when those files are absent.
- Open-source compliance, extension-flow, Provider-registry, JavaScript syntax, Python compilation, local Engine, Native Messaging, shell syntax, release-package, isolated macOS installer, and SHA-256 checks pass for `0.1.95`. The reviewed `0.1.94` and `0.1.95` caption, translation, TTS, and Engine runtime implementation files are byte-identical.

## 0.1.94 Verification Evidence

- Engine logs reproduced the actual failure: `POST /api/captions` returned HTTP 429 at 18:11 while health requests remained HTTP 200, then the same caption endpoint recovered to HTTP 200 at 18:16. The failure was YouTube request throttling, not an Engine, TTS, or Chrome Translator outage.
- Start-up caption lookup now uses this strict order before any live YouTube request: cached target-language YouTube captions, completed Provider translation, cached source captions, current-page captions, then yt-dlp only as the final extractor.
- Public source captions are cached immediately under a dedicated `youtube-source` identity. Provider translations and direct target-language YouTube captions retain their existing independent cache identities.
- The current-page path returns any readable caption track before yt-dlp. It reserves at most two attempts for target-language aliases and one for a source track, and each track has only raw, JSON3, and WebVTT fetch candidates.
- HTTP 429 remains an unknown/cooldown result and cannot trigger no-caption Whisper transcription. The extension restores original playback during the cooldown and performs at most one automatic retry.
- Deterministic helper and flow checks cover the request budget, cache-before-network order, page-before-Engine return, source-cache identity, and playback restoration path.
- A single live Engine request for public video `zYPgz6sOy74` returned 747 readable Simplified Chinese cues (`zh-Hans`), beginning with `动画制作曾经是工作室的专属领域，`; no Provider translation was needed.
- The installed HTTP Engine and both source and installed Native Host launchers report `0.1.94`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready. Both Native Messaging checks returned 201 voices, and the installed server/native-host files are byte-identical to source.
- JavaScript flow, Provider registry, syntax, Python Engine checks and compilation, release package verification, isolated macOS installer smoke tests, and both SHA-256 checks passed for the 0.1.94 packages.

## 0.1.93 Verification Evidence

- Root cause reproduction: the natural-online path intentionally joins up to five adjacent caption fragments into one fluent clip, but the overlay formerly advanced through those fragments one by one. This made correctly bounded audio sound late because the text being heard and the text being shown represented different units.
- Voice-enabled caption presentation now resolves each underlying cue to its immutable semantic voice segment and displays that segment's exact spoken text. With dubbing disabled, the original per-cue subtitle text remains unchanged.
- TTS target duration and its cache identity now use `segment.end - segment.start`; `timeboxEnd` remains only the emergency hard stop. A representative 2.2-second spoken segment no longer requests the former 2.85-second silence-extended target.
- Deterministic checks cover both cues in a joined Chinese sentence, the subtitle-only fallback, and exclusion of reserved silence from synthesis duration.
- A real Xiaoxiao request for the representative joined sentence used the 2.2-second subtitle window and returned 2.053 seconds of speech with no duration compression. This leaves about 147 ms before the caption boundary, matching the natural-online 140 ms finish reserve instead of spilling into the next subtitle.
- The installed HTTP Engine and Chrome Native Host both report `0.1.93`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready; Native Messaging returned 201 voices.
- JavaScript flow and Provider-registry checks, Python Engine checks, syntax validation, release package verification, isolated macOS installer smoke tests, and both SHA-256 checks passed for the 0.1.93 packages.

## 0.1.92 Verification Evidence

- PCM analysis of a real Microsoft natural-online response found about 170 ms of leading near-silence before the first stable voiced window. The former 120 ms scheduling lead could not fully hide that media padding plus browser startup time.
- Edge WAV preparation now requires two consecutive voiced 10 ms windows, preserves 35 ms of pre-roll, and trims only when at least 40 ms can be removed. System TTS and the existing live speed plan remain unchanged.
- Duration fitting now measures the trimmed speech file, preventing silent padding from increasing the requested compression rate. Engine responses expose the measured trim duration for direct verification.
- Synthetic PCM regression checks cover a 160 ms padded clip and a short 30 ms natural pause that must remain untouched.
- Reprocessing the saved 0.1.90 Xiaoxiao WAV removed 135 ms from its 3.499-second media duration. A fresh 0.1.92 HTTP request reported the same 135 ms trim and a stable voiced onset around 10 ms after final duration fitting, instead of the former roughly 170 ms onset.
- The installed HTTP Engine and Chrome Native Host both report `0.1.92`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready. Native voice discovery returned 201 voices.
- JavaScript flow and Provider-registry checks, Python Engine checks and compilation, release package verification, isolated macOS installer smoke tests, and both SHA-256 checks passed for the 0.1.92 packages.

## 0.1.91 Verification Evidence

- The popup contains only the `免费 / 自带 Key` workflow. The unfinished local and managed cards and panels are absent, and the remaining card uses a full-width compact layout.
- The managed-service Provider was removed from the popup, service worker registry, and YouTube panel fallback list. Provider-registry parity checks prevent it from returning in only one UI surface.
- Legacy `local` settings deterministically migrate to `byok` with Chrome local translation and native transcription. Legacy `managed` settings migrate to `byok` with Chrome local translation.
- Public README, store-listing, roadmap, and privacy wording now describe only implemented behavior while retaining the companion Engine as an available component of the supported workflow.
- The installed HTTP Engine and Chrome Native Host both report `0.1.91`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready. Release verification, isolated installer smoke tests, source/package comparison, and both SHA-256 checks passed for the 0.1.91 packages.

## 0.1.90 Verification Evidence

- Root cause reproduction: the live plan was created before `audio.play()` resolved. With a representative 120 ms media startup loss, the stable-plan drift limiter could improve the rate by only 3%, leaving the translated phrase perceptibly behind even when it avoided the hard cutoff.
- Natural-online timing now targets a 120 ms early start and 140 ms finish reserve. Comfort preparation remains unchanged, while deadline-only total ceilings increase by 0.02x to 1.40x, 1.34x, and 1.30x for short, medium, and long phrases.
- Playback clears the provisional pre-play anchor immediately after `audio.play()` resolves, then derives one stable plan from the real video/audio start position. Ordinary playback still never seeks past translated words.
- A deterministic regression compares the stale and refreshed plans for a 3.2-second segment. The refreshed plan is more than 0.03x faster, remains below 1.09x, and reaches the perceptual finish target.
- A real Xiaoxiao natural-online request returned a valid 3.499-second WAV after 1.16x Engine preparation. With a simulated 50 ms late start, the final budget selects about 1.155x live playback, remains within the 1.34x total ceiling, and finishes about 121 ms before the source boundary.
- The installed HTTP Engine and Chrome Native Host both report `0.1.90`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready. Native voice discovery returned 201 voices.
- Release verification, isolated macOS installer smoke tests, package/source byte comparison, and both SHA-256 checks passed for the 0.1.90 extension and Engine packages.

## 0.1.89 Verification Evidence

- Root cause reproduction: a 3.2-second source timebox with 3.5 seconds of prepared speech requires about 1.115x live playback. The former natural-online comfort-only budget left no live headroom after preparation, predicted a late finish, and then stopped the clip at the hard segment boundary.
- Live speech now has separate comfort and deadline budgets. Natural-online preparation remains capped at 1.12x-1.22x, while measured deadline recovery may use a total 1.28x-1.38x ceiling depending on segment length; the actual rate is still only the minimum required to finish.
- The playback plan is anchored when the clip starts and retains the existing 3% drift correction. No ordinary late start seeks past translated words, and `preservesPitch` remains enabled.
- A deterministic regression proves the reproduced clip now selects about 1.115x, finishes before the 3.2-second boundary, reports no late risk, and stays below its total deadline budget.
- The installed HTTP Engine and Chrome Native Host both report `0.1.89`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready after restart.
- Release verification, isolated macOS installer smoke tests, and both SHA-256 checks passed for the 0.1.89 extension and Engine packages.

## 0.1.88 Verification Evidence

- Caption lookup is page-first. The content script completes its bounded page-caption attempt before starting yt-dlp, so a readable target-language YouTube track produces no Engine request.
- The service worker and local Engine each apply same-key single-flight protection. Concurrent requests for one video/language tuple share one HTTP/yt-dlp operation, while unrelated videos remain independent.
- Successful Engine captions remain local for one hour with a 24-entry bound. The target download shortlist is capped at three direct URL attempts and Simplified Chinese uses explicit `zh-Hans`, `zh-CN`, `zh`, and `zh-Hans.*` selectors instead of broad `zh.*` matching.
- YouTube HTTP 429 remains an unknown temporary state. The Engine supplies a decreasing retry delay, the service worker preserves it, and the page displays a countdown before one automatic retry; this path never invokes no-caption transcription.
- Deterministic Python and JavaScript tests cover Engine single-flight behavior, service-worker request coalescing, retry-delay propagation, cache policy, page-before-Engine ordering, and the absence of misleading Whisper guidance in 429 messages.
- The installed LaunchAgent runtime is byte-identical to the reviewed server. HTTP and the Chrome-installed Native Host both report Engine `0.1.88`, protocol 2, yt-dlp, Whisper, local TTS, and Edge TTS ready.
- Release package verification and the isolated macOS installer smoke test passed for `LocalTube-Dub-extension-v0.1.88.zip` and `LocalTube-Dub-Engine-v0.1.88-macOS.zip`; both SHA-256 entries verify successfully for extension ID `ehnbmodfpecdmfmeakcjkikpgpjjpkfh`.

## 0.1.87 Verification Evidence

- yt-dlp composite target tags now retain their target identity: `zh-Hans-en` maps to Simplified Chinese, `zh-Hant-en` maps to Traditional Chinese, and `pt-BR-en` maps to Brazilian Portuguese. The source suffix is retained as evidence that YouTube performed the translation.
- Both direct metadata candidates and downloaded subtitle files propagate `translatedByYouTube`. The content script therefore treats these cues as ready-to-speak target captions and does not call DeepSeek, Chrome Translator, or another translation Provider.
- yt-dlp metadata discovery explicitly enables automatic subtitles and applies a bounded source/target selector. Existing author target captions remain highest priority, followed by YouTube target/translated captions, then source captions for local or Provider translation.
- Startup checks only the `youtube-captions` cache before resolving current tracks. A prior Provider cache is considered after target-caption resolution, preventing stale AI translations from hiding newly available YouTube Chinese captions.
- New installations default to Microsoft natural online speech; an explicitly saved local-system choice is preserved. The online privacy disclosure is visible in the README, install guide, store draft, and privacy-policy template.
- Deterministic JavaScript and Python checks cover language normalization, candidate scoring, download identity, metadata flags, cache order, default speech selection, and explicit local-system preservation.
- A live `yt-dlp --list-subs` check on public video `zYPgz6sOy74` confirmed that YouTube currently advertises `zh-Hans`, `zh-Hant`, `en-orig`, and `en` automatic tracks. The pre-fix live request reproduced the bad priority by returning readable `en-orig` after the first Chinese URL format was empty. The corrected path now has a regression test that exhausts the bounded target-language direct attempts and target download before any source-language URL can be accepted. A second live API call was blocked by YouTube HTTP 429 after the diagnostic requests, so loaded-extension acceptance should be repeated after that temporary cooldown.
- The installed LaunchAgent runtime is byte-identical to the reviewed 0.1.87 server and reports protocol 2 with yt-dlp, Whisper, local TTS, and Edge TTS ready. A final HTTP natural-speech request selected `zh-CN-XiaoxiaoNeural` and produced a 3.048-second WAV without time compression.
- Release smoke tests and package verification passed for `LocalTube-Dub-extension-v0.1.87.zip` and `LocalTube-Dub-Engine-v0.1.87-macOS.zip` using extension ID `ehnbmodfpecdmfmeakcjkikpgpjjpkfh`.

## 0.1.86 Verification Evidence

- Natural online speech is an explicit user setting and never replaces the private local default silently. The extension sends `ttsEngine: edge` only after the user selects that mode; the Engine returns the effective engine in every TTS payload.
- The project-private Python environment successfully installed `edge-tts 7.2.8`. End-to-end Engine synthesis with `zh-CN-XiaoxiaoNeural` returned a playable 24 kHz WAV/data URL; after module warmup, a real Chinese clip completed in 1.152 seconds and required no timing compression.
- Natural online voice selectors are filtered by both provider and target language. Automatic Simplified Chinese selects Xiaoxiao; Traditional Chinese selects HsiaoChen. System and browser voices remain isolated from the online selector.
- Contiguous Chinese/Japanese/Korean fragments no longer gain an artificial comma at every subtitle boundary. Natural online segments may cover up to 6.2 seconds/five cues, reducing independent prosody resets, while total prepared-plus-live acceleration is capped at 1.12x for longer phrases, 1.16x for medium phrases, and 1.22x for short phrases.
- Online speech dependencies, privacy behavior, Engine readiness, full-track identity, cache identity, and explicit pitch preservation are guarded by deterministic JavaScript/Python checks. Loaded-extension listening remains the final subjective acceptance test for voice preference.
- Upgrade recovery was verified against a real stale HTTP Engine: the machine initially reported 0.1.82 while source was 0.1.86. One restart replaced it successfully, and health then reported `engineVersion: 0.1.86`, `edgeTts: true`. The start script now requires the same version instead of accepting any protocol-2 process.

## 0.1.85 Verification Evidence

- Cached-timeline compatibility: both fresh YouTube captions and timelines saved by earlier versions pass through rolling-caption normalization. When a cached cue contains `translatedText`, normalization trims that target-language field while preserving the original source text.

- Reproduced the remaining repeat on a current public YouTube target-language track. The raw track contained 747 rolling caption snapshots and 13,235 characters; normalization produced 369 novel cues and 4,244 characters, removing 68% cumulative repetition before translation or TTS.
- Rolling snapshots now become an incremental timeline. Exact duplicates, contained fragments, suffix/prefix carry-over, music, applause, laughter, and noise annotations are removed; each new phrase begins no earlier than the previous novel phrase ends.
- Direct YouTube target-language captions are normalized and loaded as one complete timeline rather than split across background batches. AI translation receives the normalized source timeline, reducing duplicate translation calls as well as duplicate speech.
- Playback retains both segment-key history and a short overlapping text fingerprint window, so different subtitle IDs carrying the same adjacent sentence cannot replay it.
- Local TTS accepts a per-segment `maxFitRate`. Prepared Engine compression and live media catch-up now share one total comfort ceiling instead of multiplying into an unexpectedly fast final rate. A real macOS `say` check limited a two-second stress case from 2.176x to the requested 1.2x.
- The real HTMLMediaElement harness passes after the cache compatibility fix: a one-second-late start uses a stable 1.156x rate and completes at 4.94 seconds inside the 5.0-second boundary, with no playback error.

## 0.1.84 Verification Evidence

- Every semantic voice segment is immutable once added to the playback timeline. Later translation batches append only uncovered cue keys, so an active or completed sentence cannot be rebuilt under a new key and restarted from its beginning.
- The live session tracks all spoken segment keys rather than only the most recent key. A completed clip cannot be selected a second time during the same uninterrupted playback; an explicit seek or a new session intentionally resets that history.
- Adjacent rolling captions remove exact suffix/prefix overlap before TTS. Short neighboring sentences are grouped to at least 1.6 seconds, reducing repeated system-voice startup pauses and avoiding duplicate words from cumulative YouTube captions.
- Local TTS now starts at the selected natural base rate and fits against the complete segment timebox. Live catch-up is capped at 1.3x for very short clips, 1.25x for medium clips, and 1.2x for longer clips; browser fallback is capped at 1.3x.
- The real HTMLMediaElement harness passes with a late planned rate of 1.156x, an unchanged stable rate of 1.156x, and completion at 4.94 seconds inside the 5.0-second hard boundary.

## 0.1.83 Verification Evidence

- Live dubbing now assigns each semantic segment a generation token. Delayed browser speech, local TTS completions, seeks, stops, preview transitions, and reshaped translation batches cannot revive an older segment after ownership changes.
- Browser speech start timers are retained and cancelled. Local TTS no longer falls back after an arbitrary 250 ms race; browser speech is used only after a confirmed local synthesis or playback failure.
- Local media playback calculates one bounded rate per segment and then permits only a 3% drift correction. Short segments are capped at 1.55x, medium segments at 1.5x, and longer segments at 1.45x; a late segment may borrow the reserved silence instead of accelerating toward 2x.
- A document-level widget ownership guard prevents two enabled LocalTube Dub copies from mounting independent players on the same YouTube page.
- Live local audio and browser speech both pause while the YouTube player is buffering, preserving the same plan anchor when video playback resumes.
- Deterministic extension-flow, Provider registry, Python compile, and local Engine checks pass. The real HTMLMediaElement harness also passes with a late fixed rate of 1.395x, an unchanged stable rate of 1.395x, and completion at 4.94 seconds inside the 5.0-second hard boundary. Loaded-extension YouTube listening remains the final acceptance check because automated browser media playback cannot judge audible overlap or speech naturalness.

This document records the current architecture, verified behavior, historical failure modes, and remaining product gaps. Update it together with `CHANGELOG.md` whenever a change affects a core workflow.

## Product Goal

LocalTube Dub should translate and dub YouTube videos through one customer-facing workflow and optional components:

1. Free / BYOK workflow: use target-language YouTube captions directly, Chrome local translation, or the user's API Provider.
2. Optional local Engine component: add local yt-dlp, whisper.cpp, system/natural TTS, export, and advanced Ollama translation without introducing a separate product mode.

Accounts, subscriptions, payment processing, advertising, analytics, and a managed LocalTube backend are outside the open-source release scope.

The playback experience should prefer existing target-language captions, keep translated speech aligned to caption timeboxes, survive seeking and pausing, and clearly distinguish videos with usable captions from videos that require transcription.

## Current Architecture

- `extension/page_probe.js`: runs in YouTube's main world and exposes the current player response and Innertube configuration to the isolated content script.
- `extension/content.js`: owns the YouTube panel, caption acquisition race, translation queue, audio capture, subtitle overlay, TTS prefetch, and playback synchronization.
- `extension/background.js`: stores secrets, routes translation/transcription providers, owns tab capture, calls the local HTTP Engine, and falls back to Native Messaging.
- `extension/offscreen.js`: records tab audio while preserving audible tab playback.
- `server/local_dub_server.py`: exposes health, caption, translation, transcription, TTS, and restart endpoints on `127.0.0.1:8787`.
- `companion/native_host.py`: implements Chrome Native Messaging and starts/restarts the HTTP Engine or fixed installers.
- `scripts/`: prepares Python/yt-dlp, starts the Engine, and installs whisper.cpp plus ffmpeg and a multilingual model.

## 0.1.82 Verification Evidence

- JavaScript syntax checks, Provider registry checks, extension-flow assertions, Python compilation, local Engine tests, Native Messaging tests, and shell syntax checks pass.
- The installed HTTP Engine and installed Native Host both report `engineVersion: 0.1.82`, protocol 2, yt-dlp ready, Whisper ready, and TTS ready.
- The real voice-picker browser harness discovered 175 system voices, displayed 19 Chinese-matching voices, and preserved the multi-word `Bad News` voice ID.
- The live HTML media synchronizer self-test passed with natural-end completion at 4.29 seconds, seek alignment, and no late-risk result.
- A real local `Reed (中文（中国大陆）)` WAV request completed at 2.780 seconds for a 2.8-second target, with pitch-preserving fit rate 1.079.
- The six-segment live TTS prefetch benchmark completed in 1.593 seconds within its 10-second budget. The complete 12-second track benchmark produced byte-identical-duration outputs and improved from 5.878 seconds with one worker to 2.581 seconds with three workers (2.28x speedup).
- A public YouTube test returned an existing `zh-Hans` track with 82 Chinese cues and bypassed AI translation before the later diagnostic request burst triggered YouTube 429 throttling. The 0.1.82 alias and bounded-candidate behavior is covered deterministically; another live target-caption check should be run after the YouTube cooldown before store release.
- Chrome inspection confirmed the currently open YouTube tab still runs extension 0.1.80 while Engine 0.1.82 is installed. Chrome's internal Extensions page cannot be controlled by the browser test channel, so the unpacked extension must be reloaded manually before final YouTube acceptance testing.

## Verified Workflows

### Caption videos

- Page and Engine caption resolution run in parallel.
- The main-world page probe prioritizes the current `#movie_player` response and current `ytd-watch-flexy` player data before the initial page response, which may belong to an older video after YouTube SPA navigation.
- If current page snapshots and embedded scripts still expose no tracks, the extension makes one same-origin `youtubei/v1/player` request using only the API key, client identity, client version, visitor data, locale, and current video ID already provided by that YouTube page. This gives captioned BYOK/Chrome-local sessions a no-Engine recovery path.
- A real target-language track wins and bypasses translation.
- YouTube's translated caption URL is preferred before a paid or local translation provider when it returns usable cues.
- Simplified Chinese instant-translation URLs use a bounded `zh`, `zh-Hans`, `zh-CN` alias set from one best source track instead of duplicating every subtitle format. Traditional Chinese uses `zh-TW` and `zh-Hant`.
- The Engine uses current yt-dlp with a bounded caption deadline and a small subtitle-language shortlist.
- Direct yt-dlp caption URLs are attempted round-robin across translated and source tracks. A rate-limited target translation cannot consume every format attempt before a usable source-language track is tried.
- Caption responses are parsed from JSON3, SRV XML, TTML, and WebVTT.
- Simplified Chinese, Traditional Chinese, and Brazilian Portuguese identities are kept distinct.

### Translation

- Chrome local Translator is the default free translation provider for new installs.
- One-click local mode also uses Chrome local Translator by default, while keeping caption extraction, transcription, and TTS on the local Engine. It no longer requires a separate Ollama installation to complete its basic workflow.
- Ollama remains selectable as an advanced local provider. If it is unavailable, the Engine returns an explicit failure and never reports untranslated source text as a successful translation.
- OpenAI, Gemini, Claude, DeepSeek, OpenRouter, Microsoft Translator, Google Cloud Translation, and custom OpenAI-compatible endpoints remain available.
- Translation and transcription providers are independent. Chrome local translation can be combined with local whisper.cpp transcription.
- Translation batches with missing or empty items are retried as smaller halves; original text is not silently presented as a successful translation.
- API keys are stored in `chrome.storage.local`; page content scripts receive only boolean key state and safe settings.
- Remote Provider errors are classified as authentication, quota, rate limit, model, permission, timeout, or generic failures. Raw messages containing masked Key suffixes are not shown on the YouTube page.
- A remote Provider failure falls back to Chrome local translation for the current session. The common source-to-target language pack is silently warmed from the original Start click, and fallback output is cached under the Chrome Provider rather than the failed remote Provider.

### No-caption videos

- The user must explicitly enable audio transcription.
- `tabCapture` and `offscreen` are optional runtime permissions. They are requested only when the user enables no-caption transcription; captioned videos and ordinary translation do not receive an install-time recording warning.
- Caption discovery keeps media-format selection separate from subtitle metadata. A playable video with no caption tracks is confirmed as `NO_PUBLIC_CAPTIONS`, while unavailable, private, members-only, age-restricted, or placeholder metadata is reported as `VIDEO_UNAVAILABLE` and never used to trigger transcription.
- When both public and cookie-aware metadata contain no caption candidates, the Engine skips subtitle-file download attempts that cannot produce a result. Live verification reduced no-caption confirmation from 14.783 seconds to 6.909 seconds before local transcription begins.
- Direct video-element recording is attempted first; tab capture is the fallback.
- Local whisper.cpp uses ffmpeg to convert input to mono 16 kHz PCM WAV and returns timestamped cues.
- Local transcription prefers the running HTTP Engine and falls back to Native Messaging.
- Local no-caption playback first transcribes a bounded YouTube audio window through yt-dlp, then prepares later windows ahead of playback with overlap deduplication and boundary buffering.
- Player/tab recording remains the fallback when direct Engine audio-window extraction is unavailable.
- The one-click macOS installer installs whisper.cpp, ffmpeg, and the multilingual base model, then starts or restarts the Engine.
- Local rolling sessions can launch a cancellable one-shot full transcript job. Engine downloads only a low-bitrate audio stream, runs whisper.cpp over the complete file, removes temporary media, and retains the resulting cue timeline in memory for one hour.
- Only one heavy full transcript job runs at a time, and the default maximum video duration is two hours. Chrome polls small status objects; complete audio never crosses the extension or Native Messaging boundary.

### Voice playback

- macOS local TTS uses `say` to generate validated PCM WAV; invalid or unavailable local audio falls back to browser speech synthesis.
- Voice selectors are populated from the running Engine's real `say -v ?` inventory through HTTP or Native Messaging, then merged with browser voices. The popup and YouTube panel show voices matching the current target language and reset to automatic matching when that language changes.
- System voice parsing preserves complete names containing spaces or localized parentheses. An unavailable saved voice is never passed blindly to `say`; the Engine chooses an installed preferred or same-language voice instead.
- Voice audio is generated with an 18-second rolling prefetch window, at most six queued segments, and three concurrent local TTS workers. Subtitle and translation preparation starts a silent system-voice warmup so the first visible cue does not pay the full cold-start cost.
- A live segment waits only 250 ms for an uncached local clip before starting browser speech at the subtitle boundary. The local request keeps completing into cache for later playback, while stale queued jobs are removed whenever translated batches reshape semantic segments.
- Stopping a session cancels queued TTS promises without falsifying the count of requests that are already running.
- Speech segments are grouped from nearby cues, assigned fixed timeboxes, started from subtitle timing, and rate-adjusted against remaining video time.
- Fragmented captions continue merging until a sentence boundary or a bounded gap, duration, cue-count, or character limit. A fragment longer than the minimum cue duration no longer forces an artificial speech break by itself.
- Local macOS TTS measures each generated WAV and uses bounded ffmpeg `atempo` fitting when it exceeds the original subtitle segment duration, preserving pitch before browser drift correction.
- Hiding subtitle text during a cue gap does not stop speech; active local or browser audio remains governed by the voice segment timebox.
- Normal TTS generation delay is corrected with playback rate rather than skipping translated words; proportional audio seeking is used only after an explicit video seek.
- Live segment playback uses one shared timebox synchronizer. It converts remaining video media time into wall-clock budget, reserves 60 ms at the segment end, and raises the active clip rate only as much as needed to finish inside that budget.
- The synchronizer uses two ending boundaries: it targets the source subtitle's natural end for normal playback, while the following silence remains only a hard overflow boundary for unusually long speech. Browser-speech fallback uses the same natural-end budget instead of deliberately stretching every line into that silence.
- Short delayed clips can catch up to 2.2x, medium clips to 2.05x, and longer clips to 1.9x relative to the current video rate. Clips that finish early remain silent until the next semantic segment; a normal TTS delay never seeks past translated words.
- Pause, resume, seek, and stop cancel or realign active speech and restore the original video audio settings.

### Subtitle export

- The YouTube panel exports translated cues as UTF-8 SRT or WebVTT with no `downloads` permission.
- A captioned timeline is labeled complete only when every source cue is represented. Rolling no-caption output is explicitly labeled partial and contains only the prepared range.
- Changing the target language or provider during an active run cancels the previous translation pipeline so exported cues cannot mix languages.

### Dubbed voice-track export

- A complete translated timeline can be rendered as downloadable pure voice or as translated voice mixed with the video's complete original audio through a cancellable local Engine job, with compact M4A and lossless WAV outputs.
- Live TTS and batch rendering share the same validated macOS `say` plus ffmpeg `atempo` path. Batch clips use adaptive request rates and stronger pitch-preserving fitting before timeline assembly.
- Complete-track input reuses the live semantic voice segments instead of raw fragmented captions. Up to three independent TTS/ffmpeg segment jobs run concurrently in isolated directories; completed results are sorted by original timestamps before the streaming writer sees them.
- Parallel render cancellation propagates into active `say` and ffmpeg child processes. The worker limit is bounded to four by configuration and defaults to three; it is never derived from an unbounded cue count.
- The streaming writer inserts silence, places each clip at its cue timestamp, truncates at the cue/next-cue boundary, and never allocates the entire two-hour track in memory.
- Mixed mode downloads only a low-bitrate source audio stream, applies the visible original-volume setting, and uses ffmpeg to align, mix, limit, and encode an exact-duration mono PCM WAV. It does not download video.
- M4A mode always starts from that exact WAV timeline, then runs a separate cancellable 96 kbps AAC pass. ffprobe verifies final duration when available, and direct download uses the format-appropriate MIME type.
- Completed tracks can be previewed in the YouTube panel. A dedicated audio element follows video pause, rate, and seek state; small clock drift uses bounded speed correction and larger drift seeks to the video clock.
- Preview treats YouTube buffering as a first-class state: `waiting` pauses the dub track, `playing` resumes and realigns it, pending play requests are deduplicated, and an intentional `AbortError` caused by that pause is retried instead of shown as a failure.
- Preview sessions carry operation IDs so a stopped or replaced media request cannot affect the next session. Video end exits preview cleanly rather than leaving a stale active button.
- Track downloads support `HEAD` and single HTTP byte ranges. Preview uses inline disposition, while explicit user download remains an attachment.
- Mixed mode retains the source speaker because it mixes the complete original audio; source-speech/background separation is still a separate unfinished feature.
- Chrome polls small job metadata and downloads the completed file directly from localhost after a fresh user click. WAV bytes do not cross extension messages, and the extension still does not request `downloads` permission.

### Engine lifecycle

- The popup and page show live HTTP/Native Engine health.
- HTTP and Native health include the exact Engine release version and Engine protocol version. Protocol compatibility, not a bare HTTP 200 response, decides whether the UI can report Engine as current.
- Caption timelines use a bounded local-only cache. Readable public source captions are saved immediately with a `youtube-source` identity; AI-translated timelines are keyed by video, target language, Provider, and model; timelines already supplied in the target language by YouTube use a Provider-neutral `youtube-captions` key and are checked first. Entries expire after 7 days, are capped at 12 timeline entries/about 4 MB, and never include audio, video, API keys, or partial rolling transcription.
- A missing or older protocol is shown as an Engine update requirement. A different release version with the current protocol is shown as compatible but worth updating; restart controls state clearly that restarting cannot replace old runtime files.
- Health distinguishes yt-dlp readiness from local Whisper readiness.
- Native Host launcher restores a stable PATH and records the project virtual-environment Python path.

### Release packaging

- `scripts/build_release_macos.sh` creates a root-manifest Chrome Web Store ZIP, an optional macOS Engine bootstrap ZIP bound to a supplied extension ID, and matching SHA-256 checksums.
- Installation-time host access is limited to YouTube and the local Engine. Cloud translation/transcription and custom HTTPS endpoints use optional host access; the popup requests only the exact selected origin from a direct user action, and the background verifies that origin again before transmitting text or audio.
- The Engine ZIP contains double-click commands for core install, optional no-caption Whisper install, and complete uninstall. It does not contain the developer `.venv`, caches, API keys, or absolute development paths.
- The build verifies every manifest-referenced extension asset, ZIP path safety, version/ID metadata, unresolved templates, Native Messaging `allowed_origins`, installer executable permissions, isolated LaunchAgent generation, and uninstall dry-run.
- Current release metadata deliberately marks the macOS bundle unsigned and unnotarized. It is suitable for controlled private beta, not yet for frictionless public download.
- Release assembly injects a customer `release-info.json` containing the exact channel, version, extension ID, Engine ZIP name, and optional HTTPS download/support links. The source tree keeps development metadata, and the install page uses that distinction to hide checkout paths, Terminal commands, and developer diagnostics from customers.
- Native Host launcher prefers the private `.venv` beside the installed runtime, and each atomic runtime update recreates `.localtube_python_path`; replacing the runtime must never make Native health fall back to a system Python without yt-dlp.
- The macOS Native Host installer creates a self-contained runtime under `~/Library/Application Support/LocalTube Dub/engine-runtime`, registers Native Messaging from that stable path, and registers a user LaunchAgent that starts Engine at login, restarts it after an unexpected exit, and writes persistent logs under the user's Library folder.
- The LaunchAgent installer refuses to terminate an unrelated process on port 8787, and Native restart reuses an Engine instance already restored by launchd.
- Start/restart checks HTTP health after Native Host exit because the detached Engine may still have started successfully.
- Caption resolution now wires the previously dormant Engine auto-start path into real requests. A connection refusal gets one bounded 4.5-second start attempt and one HTTP retry before Native caption fallback; rate limits, confirmed no-caption responses, unavailable videos, HTTP errors, and request timeouts never trigger a restart loop.
- Enable/disable changes now mount or unmount the YouTube UI without requiring a page refresh.

## Historical Failure Modes That Must Not Return

- Do not infer that a caption track is usable merely because its metadata exists; require parsed cues.
- Do not classify a temporary Engine/page failure as a confirmed no-caption video.
- Do not classify an unavailable or access-restricted video as no-caption, and do not let yt-dlp media-format selection prevent subtitle metadata inspection.
- Do not run yt-dlp subtitle-file download after successful metadata has already confirmed there are no caption candidates; use the cookie-aware metadata recheck, then return the authoritative no-caption result.
- A page-level no-caption decision is authoritative only after the player response is matched to the current YouTube video ID; an unrelated or stale page response is not enough.
- Do not treat `ytInitialPlayerResponse` as the only main-world source after YouTube SPA navigation. Prefer current player/watch data and require every page or Innertube response to match the active video ID before using its tracks or declaring no captions.
- Do not send a captioned video to Whisper simply because a YouTube ad is playing at the start.
- Do not fetch every subtitle language with yt-dlp; it creates long waits and rate limiting.
- Do not exhaust the direct-caption budget on every format of one translated track before trying the first format of a usable source track, and do not let a subtitle-download subprocess timeout escape as an unclassified crash.
- Do not use Apple's Python 3.9 for current yt-dlp; the project `.venv` must use Python 3.10 or newer.
- Do not generate `.m4a` with macOS `say`; use validated PCM WAV.
- Do not make local transcription depend exclusively on Native Messaging when the HTTP Engine is already healthy.
- Do not couple a free translation provider to a paid transcription provider.
- Do not mark Engine health green for local no-caption mode when whisper.cpp or its model is missing.
- Do not mark an Engine healthy solely because `/api/health` returns HTTP 200. Require the expected `service` identity and minimum protocol version, and preserve release metadata when copying source into the Application Support runtime.
- Do not update code without bumping the extension version and adding a `CHANGELOG.md` entry.
- Do not cache partial translation/transcription results or reuse AI-translated timelines across target languages, Providers, or models. Provider-neutral reuse is allowed only when YouTube itself supplied the requested target-language track. Keep the popup disable and clear controls wired to real local storage deletion.
- Do not make post-login Engine availability depend on the customer reopening Terminal; keep Native Host registration and the macOS LaunchAgent installation wired together.
- Do not auto-start or restart the Engine for YouTube rate limits, confirmed no-caption responses, unavailable videos, or HTTP timeouts. Automatic recovery is only for a transport-level connection failure and is bounded to one attempt before the normal fallback.
- Do not point a LaunchAgent or Native Messaging manifest at a development checkout under `~/Documents`; macOS TCC can leave background Python blocked while opening the script. Install executable runtime files under Application Support.
- Do not atomically replace the installed runtime without restoring Native Host's Python path, and do not let the installed launcher prefer a system Python over its adjacent private `.venv`.
- Do not pass complete audio tracks through `chrome.runtime` or Native Messaging, and do not let a rendered cue write beyond the next cue's start time.
- Do not represent full-original-audio mixing as background-only mixing; original speech remains until a real separation stage exists.
- Do not encode compressed output before PCM timeline assembly; M4A must be derived from the completed exact-duration WAV so compression cannot alter cue placement.
- Do not play YouTube's original audio underneath a mixed-track preview; the mixed file already contains that audio.
- Do not allow queued, awaiting, or browser-fallback live TTS to start over a complete-track preview.
- Do not treat an `AbortError` from pausing a pending preview `play()` during video buffering as a fatal media error, and do not issue another `play()` while the previous promise is still pending.
- Do not write parallel TTS results in completion order, use shared segment output paths, or use unbounded workers; sort by original timestamps and keep each worker in its own directory.
- Do not make complete-track cancellation wait for every active `say` or ffmpeg process to finish naturally; propagate the cancellation event into child processes.
- Do not ship a Native Host package without binding and validating the exact Web Store extension ID, and do not reuse an Engine ZIP after that ID changes.
- Do not call the current macOS bootstrap signed or notarized, and do not package a development `.venv`, caches, secrets, or an absolute checkout path into release ZIPs.
- Do not expose source-install commands or development diagnostics in the customer install view. Do not publish release metadata whose version, extension ID, Engine filename, or HTTPS links disagree with the generated artifacts.
- Do not restore every AI Provider domain to required `host_permissions`, silently save a denied Provider change, or transmit to a remote Provider without an exact optional-host permission check. YouTube and localhost remain the only required hosts.
- Do not restore `tabCapture` or `offscreen` to required install permissions, and do not enter the tab-audio compatibility fallback until both optional permissions have been granted from the user's no-caption setting action.
- Do not make one-click local mode depend on Ollama, and do not represent untranslated source captions as a successful local translation when Ollama is unavailable.
- Do not stop semantic voice grouping only because a fragment exceeds the minimum duration; sentence boundaries and the bounded maximums decide whether adjacent fragments belong together.

## Remaining Product Gaps

These are not complete and must not be represented as finished:

1. Source separation and final media muxing. The product exports synchronized pure-voice or full-original-audio-mixed M4A/WAV tracks, but it does not separate source speech from background audio or mux a new downloadable video file.
2. Production-quality TTS. macOS `say` and browser speech are functional fallbacks, not a cross-platform natural voice engine.
3. Store-ready desktop packaging. The final Web Store Item ID is known and versioned extension and ID-bound macOS private-beta ZIPs exist, but there is still no signed/notarized macOS app/pkg, reliable Windows executable host, auto-update mechanism, or hosted Engine download page.
4. Browser end-to-end automation. Static and Engine tests exist, but Chrome-based regression coverage for real YouTube navigation, Translator language-pack download, audio playback, and seeking is still missing.
5. Release operations. Source documents and reviewer instructions now exist, but the repository URL, support contact, hosted privacy-policy URL, final Engine URL, final screenshots, and Store item still need publisher-owned values.

## Required Verification Before Each Release

1. Confirm `extension/manifest.json`, popup display, tests, and changelog use the same version.
2. Run JavaScript syntax checks and both Node verification scripts.
3. Run Python compilation and `tools/verify_local_engine.py` with the project `.venv`.
4. Run shell syntax checks for every macOS installer/start script.
5. Run `tools/verify_native_messaging.py` against both the source launcher and the installed Application Support launcher after changing Engine lifecycle code.
6. Check `/api/health` and require `ytDlp: true`; require `whisper: true` when local no-caption transcription is selected.
7. Require `/api/health` over both HTTP and Native Messaging to return the matching `engineVersion` and supported `protocolVersion`. Start an isolated legacy health server with no protocol field and verify `start_engine_macos.sh` replaces it instead of reporting it as already running.
8. Exercise at least one real caption extraction, one real local transcription, and one real local TTS response after changes to those paths.
9. Reload the unpacked extension and refresh the existing YouTube tab before judging content-script behavior.
10. After changing complete-track export, generate a synthetic original/voice pair and verify mixed duration, background attenuation, cue-window voice presence, and download headers without relying on an external YouTube request.
11. For compressed export changes, verify a complete M4A job, AAC duration, smaller output size than its WAV intermediate, `.m4a` filename, and `audio/mp4` download type.
12. For complete-track playback changes, verify `HEAD`, open/closed/suffix byte ranges, `206 Content-Range`, invalid-range `416`, inline preview disposition, and page-side pause/seek/rate guards.
13. Run `tools/full_track_media_harness.html` in Chrome and verify start, pause/resume, seek, playback-rate change, buffering recovery, and end cleanup with both media clocks visible.
14. Run `tools/live_voice_media_harness.html`, click `运行媒体自检`, and require `selfTest.passed: true`. Then load the unpacked extension in Chrome and manually verify one real caption video at 1x and 1.5x because automated in-app-browser tabs can reject media `play()` despite muted test media.
15. Run `tools/voice_picker_harness.html` against a real Engine and require target-language filtering plus preservation of a multi-word voice ID. Generate one real WAV with a discovered voice and verify the returned Engine name and duration.
16. After changing complete-track performance, run `tools/benchmark_dub_track_parallel.py`, require valid equal-duration output from one and three workers, and keep the parallel path only when it produces a meaningful wall-clock improvement.
17. Build release ZIPs with `scripts/build_release_macos.sh`, run `tools/verify_release_packages.py`, require the isolated macOS installer smoke test to pass, and verify both SHA-256 entries from inside `dist/`.
18. Inspect the packaged `release-info.json`: require a customer channel, the exact extension version and ID, the matching Engine ZIP name, and HTTPS-only download/support URLs. Open the packaged install page and confirm customer builds hide all source paths and Terminal commands.
