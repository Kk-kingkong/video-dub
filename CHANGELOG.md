# LocalTube Dub Changelog

## 0.1.95 - 2026-07-14

- Prepared the project for open-source publication under Apache-2.0. Added contribution, security, support, conduct, third-party dependency, issue, and pull-request documentation without changing caption, translation, TTS, or synchronization behavior.
- Replaced the privacy template with a release-facing policy that documents Chrome Sync preferences, local API-key and caption storage, active-video YouTube requests, yt-dlp cookie fallback, optional audio capture, BYOK Provider transfers, Microsoft natural speech, local Engine processing, retention, deletion, and user controls.
- Rewrote the Chrome Web Store listing draft around one implemented purpose and removed the undeveloped managed-service claim. Added accurate Engine requirements, current limitations, listing assets, publisher URLs, and reviewer instructions.
- Expanded permission and release documentation with final Store-ID binding, signed Engine packaging, clean-profile tests, public HTTPS pages, source/archive secret scans, and an unlisted-to-public release sequence.
- Added a deterministic open-source compliance verifier and excluded environments, secrets, models, logs, editor state, and generated release ZIPs from source control.
- Included the Apache-2.0 license and third-party notices in both generated extension and Engine ZIP files, with release verification that rejects packages missing either document.

## 0.1.94 - 2026-07-14

- Fixed repeated YouTube subtitle requests causing `429 Too Many Requests` even while the local Engine remained healthy. Subtitle acquisition now exhausts the target-language cache, completed Provider cache, and reusable source-caption cache before contacting YouTube.
- Added a persistent source-caption cache. Once a public source track is read, later sessions can translate it with the selected Provider without asking YouTube or yt-dlp for the same subtitles again.
- Any readable current-page caption track now bypasses yt-dlp. The page path still prefers YouTube's target-language translation, but it falls back immediately to readable source captions instead of launching another extractor request.
- Limited one page lookup to at most two target-language tracks plus one source track, with only raw, JSON3, and WebVTT formats per track. This replaces the former unbounded track loop and seven-format retry fan-out.
- A YouTube cooldown no longer leaves the original video paused. Playback resumes without dubbing, one automatic retry remains scheduled, and a rate limit is never treated as proof that the video has no captions.

## 0.1.93 - 2026-07-14

- Fixed a perceptual mismatch where natural speech combined several short caption fragments into one fluent clip while the overlay continued showing each fragment separately. The voice could therefore sound one subtitle behind even when the clip's final deadline was correct.
- When dubbing is enabled, every source cue inside a semantic voice segment now presents the exact full text spoken by that clip. Subtitle-only playback still keeps the original per-cue presentation.
- Fit TTS against the semantic caption segment's real start/end window instead of including up to 650 ms of following silence. The silence remains an emergency hard boundary, but it no longer makes normal speech generation slower.
- Key voice-audio cache entries by the real synthesis duration and add deterministic checks for caption/voice text identity and exclusion of silence slack from TTS timing.

## 0.1.92 - 2026-07-14

- Fixed the remaining slight delay before natural-online translated speech becomes audible. Microsoft Edge neural WAV files include transport silence at the beginning, while playback synchronization previously treated the file boundary as the speech boundary.
- Detect two consecutive voiced 10 ms windows and remove only the excess leading silence, retaining a 35 ms pre-roll so soft consonants and natural attacks are not clipped. Short pauses below 40 ms are left untouched.
- Run duration fitting after silence removal, so speed matching is based on spoken content instead of padding. Existing live playback-rate limits and pitch preservation are unchanged.
- Expose `leadingTrimSeconds` in Engine TTS responses for diagnostics and add deterministic tests for trimmed and intentionally preserved audio.

## 0.1.91 - 2026-07-14

- Removed the unfinished `一键本地` and `我们的服务` cards and their dedicated popup panels. The popup now presents a single customer workflow: free Chrome translation or the user's own API key.
- Removed the undeveloped managed-service Provider from both the service worker registry and the YouTube panel fallback list, so it cannot reappear through dynamic Provider discovery.
- Added upgrade migration for previously saved modes. Legacy local-mode settings move to `byok` while retaining Chrome local translation plus native transcription; legacy managed settings move to the free Chrome translator instead of leaving the popup in an unavailable state.
- Changed the remaining workflow card to a full-width compact layout and updated the README, store listing, roadmap, and privacy template so unfinished products are no longer advertised.
- Added deterministic guards for the single customer workflow, removed cards/panels/Provider, and both legacy-setting migrations.

## 0.1.90 - 2026-07-14

- Fixed natural translated speech remaining slightly behind the source after browser audio playback startup. The old plan was anchored before `audio.play()` completed, so startup latency survived as a persistent offset under the intentionally gentle drift correction.
- Re-anchor the live speed plan once playback has actually started. The new plan accounts for real video time already consumed instead of carrying the stale pre-play estimate through the whole phrase.
- Tuned natural-online timing from an 80 ms to a 120 ms early start and from a 60 ms to a 140 ms finish reserve. Deadline-only headroom increases by 0.02x so a measured long clip can honor that reserve after a small startup delay; normal comfort preparation is unchanged and pitch preservation remains enabled.
- Added a deterministic playback startup regression covering a 120 ms scheduling loss. It proves the refreshed plan catches up subtly, finishes inside the phrase window, and does not exceed 1.09x live playback in the representative case.

## 0.1.89 - 2026-07-13

- Fixed translated speech reaching the next source-caption boundary unfinished and then being cut off. The previous natural-online comfort ceiling could predict a late finish but had no bounded way to recover.
- Added a two-level speech-rate budget. Normal TTS preparation keeps the existing gentle rate limits; only a measured clip that would miss its deadline may use a higher deadline catch-up ceiling.
- Deadline catch-up selects only the rate required to finish, anchors that rate at the beginning of the segment, and keeps it stable. It does not seek over words or wait until the end to make a sudden speed change, and pitch preservation remains enabled.
- Added a deterministic regression case for a 3.2-second source segment with a 3.5-second prepared voice clip. The former comfort-only plan reproduces the cut; the new plan uses about 1.115x and completes before the source boundary without late risk.

## 0.1.88 - 2026-07-13

- Changed caption acquisition to finish the fast page-caption attempt before contacting the local Engine. A readable target-language YouTube track now avoids yt-dlp entirely, reducing latency and unnecessary YouTube requests.
- Coalesced concurrent requests for the same video, source language, target language, and Engine endpoint in both the Chrome service worker and the local Engine. Multiple extension events now share one yt-dlp operation instead of multiplying requests.
- Extended successful Engine caption caching from 10 minutes to one hour with a 24-video bound. Reopening or restarting dubbing on a recently resolved video reuses the local result without contacting YouTube again.
- Reduced direct target-track attempts from six to three and narrowed Simplified Chinese matching from broad `zh.*` to `zh-Hans.*` plus explicit aliases. This preserves target-language priority while avoiding duplicate formats and unrelated Chinese variants.
- Preserved Engine `retryAfterSeconds` through the service worker and added a visible countdown with one automatic retry for YouTube HTTP 429 responses. Rate limiting is treated as temporary service pressure, never as proof that a video has no captions and never as a reason to start Whisper automatically.
- Added concurrent Engine and service-worker regression tests, page-before-Engine guards, retry propagation checks, cache policy checks, and release-version assertions.

## 0.1.87 - 2026-07-13

- Fixed YouTube/yt-dlp composite translation tags such as `zh-Hans-en`, `zh-Hant-en`, and `pt-BR-en`. These tracks are now recognized as target-language captions instead of being reduced to the wrong generic language and sent through an unnecessary AI translation request.
- Made existing target-language captions the true first choice. Author-provided Chinese, YouTube-listed translated Chinese, direct `tlang` responses, and downloaded yt-dlp translated subtitles now all bypass DeepSeek and other translation Providers when usable text is already available.
- Added `--write-auto-subs` plus the requested source/target language shortlist to yt-dlp metadata discovery, and preserved `translatedByYouTube` on downloaded composite tracks. This covers videos where translated caption metadata is hidden unless automatic subtitles are explicitly requested.
- Changed cache startup order so a previous Provider translation cannot win before the extension checks for a current YouTube target-language track. YouTube-caption cache remains instant; Provider cache is used only after no target-language track is found.
- Changed the first-run speech default to `Microsoft 自然在线`, with automatic target-language neural voice selection. Users who explicitly select `本地系统（快速）` keep that setting; privacy and installation text now explains the online default and how to switch to fully local speech.
- Added deterministic Engine and extension checks for composite target tags, downloaded translated-caption identity, metadata flags, cache priority, and the new speech default.

## 0.1.86 - 2026-07-12

- Added an explicit `自然在线` speech engine powered by Microsoft Edge neural voices. It needs no API key, remains opt-in, and sends only the subtitle text being spoken; the existing macOS system voice remains the private local default and browser speech remains the final playback fallback.
- Added target-language natural female and male voices for Simplified/Traditional Chinese, English, Japanese, Korean, Spanish, French, German, Italian, Portuguese, Russian, and Arabic. Voice selectors now filter by both target language and selected speech engine.
- Added `edge-tts` to the one-click Engine dependency installer and Engine health/voice discovery. The persistent Engine uses the Python API directly for live clips, avoiding a new Python process per subtitle; a real Chinese request completed synthesis in 1.152 seconds after warmup.
- Natural online mode now builds longer semantic phrases, uses a gentler 1.12x to 1.22x total speed ceiling, explicitly preserves pitch, and removes artificial commas between contiguous CJK caption fragments. These changes reduce prosody resets, metallic time stretching, and stop-start delivery.
- Carried the selected speech engine into live cache keys, warmup, full-track export, Engine job identity, installation documentation, and the privacy-policy template. Added deterministic engine/voice filtering, natural CJK joining, payload, health, and release checks.
- Fixed source/manual upgrades keeping an older Engine alive. The start script now compares the running `engineVersion` with the current bundle and restarts a mismatched LocalTube process instead of accepting protocol compatibility alone.

## 0.1.85 - 2026-07-12

- Fixed the remaining repeated-sentence cause in YouTube rolling captions. Cumulative snapshots such as “需要巨额预算”, “需要巨额预算和多年的”, and “需要巨额预算和多年的培训” are now converted into three novel phrases before translation and TTS instead of being spoken as three complete captions.
- Added global rolling-caption normalization for direct target-language captions and source captions sent to translators. It removes duplicate/contained text, suffix-prefix carry-over, and non-speech annotations while preserving an incremental timeline; a real 747-cue public track dropped 68% duplicated characters.
- Loaded an existing YouTube target-language track as one complete normalized timeline instead of rebuilding it through background batches. Added an overlapping text-fingerprint playback gate in addition to segment-key history, preventing adjacent captions with different IDs from replaying the same sentence.
- Added a per-segment Engine fit limit and made live playback account for the Engine's measured `fitRate`. Prepared compression and live catch-up now share one total comfort ceiling rather than multiplying together; macOS TTS stress verification reduced a previous 2.176x compression to the requested 1.2x.
- Added deterministic rolling-snapshot, timing, annotation, full-target-timeline, text-fingerprint, Engine fit-limit, and release guards.
- Applied the same rolling-caption normalization when loading older cached timelines, so subtitles cached by previous versions cannot bypass the no-repeat fix.

## 0.1.84 - 2026-07-12

- Fixed translated sentences being spoken twice when a later background translation batch arrived. Existing semantic voice segments are now immutable and new batches append only previously uncovered subtitle cues instead of rebuilding an active segment under a different key.
- Added session-wide played-segment tracking. Once a segment starts or is deliberately skipped, the live selector cannot play it again until the user seeks or starts a new session.
- Removed repeated words from cumulative YouTube captions by trimming exact suffix/prefix overlap before TTS. Adjacent short sentences are grouped into longer semantic clips, reducing repeated voice startup pauses and producing more natural pacing.
- Removed estimated pre-acceleration from local TTS requests and gave synthesis the complete available timebox. Live catch-up now tops out at 1.3x for very short clips, 1.25x for medium clips, and 1.2x for longer clips; browser fallback is capped at 1.3x.
- Added regression checks for immutable batch extension, session-wide no-replay protection, rolling-caption overlap removal, short-sentence grouping, natural request rate, and the reduced real-media speed ceiling.

## 0.1.83 - 2026-07-12

- Eliminated a real overlapping-speech race. Delayed browser TTS starts are now cancellable and protected by a per-segment playback generation, so a stopped, replaced, sought, or reshaped subtitle segment cannot begin speaking after the next segment owns playback.
- Removed the 250 ms local-TTS race that switched healthy sessions between system audio and browser speech. Rolling local synthesis still prefetches up to six segments with three workers, while browser speech is now reserved for confirmed local synthesis or playback failures.
- Replaced frame-by-frame catch-up acceleration with one measured playback plan per generated clip plus a maximum 3% drift correction. Comfortable catch-up is capped at 1.55x for short clips, 1.5x for medium clips, and 1.45x for longer clips; nearby silence is borrowed before increasing speed further.
- Invalidated pending playback on seeks, stops, full-transcript replacement, full-track preview, disabled speech, and semantic-segment reshaping. Added a shared page ownership guard so two enabled development/installed copies cannot mount independent dubbing players on one YouTube page.
- Paused both local media and browser speech while YouTube is buffering, then resumed from the same fixed-rate plan when playback continues instead of letting translated speech run ahead of a stalled picture.
- Updated deterministic synchronization and source guards to cover fixed-rate stability, bounded silence borrowing, generation ownership, timer cancellation, confirmed-only fallback, and duplicate widget prevention.

## 0.1.82 - 2026-07-11

- Reduced YouTube instant-translation requests from one synthetic target track per subtitle format to one best source track with a small bounded language-code set. This prevents duplicate `tlang` requests from consuming the caption deadline or triggering avoidable 429 responses.
- Added target-language aliases for YouTube translation URLs. Simplified Chinese now tries `zh`, `zh-Hans`, and `zh-CN`; Traditional Chinese tries `zh-TW` and `zh-Hant`; the fastest working target still wins before any AI Provider is called.
- Applied the same bounded translated-track strategy to the YouTube page path and the yt-dlp Engine path, while continuing to prefer an author-uploaded or automatic target-language track over a synthesized translation URL.

## 0.1.81 - 2026-07-11

- Fixed target-caption priority: a fast source-language Engine result no longer prevents a page-provided target-language track from winning; Engine results marked as YouTube-translated are normalized to the selected target language.
- Added automatic Chrome local-translation fallback when a remote translation Provider rejects its Key, runs out of quota, rate-limits, rejects a model, times out, or otherwise fails.
- Added privacy-safe Provider error classification. Authentication errors no longer expose a masked Key suffix or raw remote response in the YouTube panel.
- The free Chrome language-pack fallback is warmed from the original Start click so an invalid remote Key can recover without a second setup step when the language pair is supported.
- Renamed the Provider check action to “验证翻译 Key” for Key-based services, and a newly entered translation Key is now validated immediately after it is saved.
- Retained direct YouTube target-caption reuse ahead of every translation Provider: author-uploaded Chinese, YouTube Chinese automatic captions, and readable `tlang=zh-Hans`/`zh-Hant` translations can go straight to TTS without DeepSeek.

## 0.1.80 - 2026-07-11

- Fixed the real voice-picker browser harness to query the running Engine on port `8787` instead of the temporary static-file server on `8790`. The previous URL returned the harness HTML as if it were an Engine response, so release verification could not prove real voice discovery even though the extension path itself was correct.
- Added a permanent source assertion for the Engine voice endpoint and reran the browser media synchronizer against the two-boundary algorithm. The live harness passed with natural-end completion at `4.29s`, explicit-seek alignment, and no late-risk result.
- Recorded live release evidence for the current Engine: source-caption extraction, direct `zh-Hans` caption reuse without AI translation, authoritative no-caption classification, and local yt-dlp plus whisper.cpp transcription all completed successfully against public YouTube videos.

## 0.1.79 - 2026-07-11

- Changed live dubbing from a single permissive timebox to a two-boundary synchronizer. Every prepared clip now aims to finish at the source subtitle's natural end; the bounded silence before the next segment is used only when an unusually long clip cannot fit at the maximum acceptable rate.
- Corrected browser speech fallback to calculate its rate from the source subtitle end instead of the extended silence boundary. This removes the built-in tendency to speak each translated line slowly and finish close to the following segment.
- Kept the low-latency architecture intact: no forced alignment, source separation, extra model, or full-video preprocessing was added. Existing local TTS duration fitting and rolling prefetch still do the expensive work ahead of playback, while live rate correction remains bounded.
- Added deterministic natural-end, overflow-silence, impossible-fit, and hard-boundary regression assertions so later synchronization changes cannot silently restore the slow behavior.

## 0.1.78 - 2026-07-11

- Moved `tabCapture` and `offscreen` out of installation-time permissions. Chrome now asks for them only when the user explicitly enables “无字幕时自动转写”, so captioned-video users no longer receive an unrelated recording warning during installation.
- Combined optional recording permissions with the existing exact-origin Provider request in the popup. Denial leaves the previous settings unchanged, while ordinary debounced settings updates never open a delayed permission prompt.
- Enforced the optional permission boundary again in the service worker before creating a tab stream or offscreen recorder. Direct current-player recording remains available first, and the compatibility fallback now fails with a concise recovery instruction instead of invoking an ungranted API.
- Added minimum Chrome 116 metadata, deterministic permission-helper and background-denial tests, Manifest least-privilege guards, and updated Web Store, privacy, roadmap, README, and development-audit documentation.

## 0.1.77 - 2026-07-11

- Reduced installation-time host access to YouTube and the optional localhost Engine. OpenAI, Gemini, Google Cloud Translation, Microsoft Translator, Claude, DeepSeek, OpenRouter, Groq, Deepgram, and custom remote endpoints are no longer required host permissions.
- Added exact-origin runtime permission requests for the selected translation Provider and, only when no-caption transcription is enabled, the selected transcription Provider. Chrome local translation, local Engine mode, YouTube, and localhost require no additional prompt.
- Hardened permission failure handling. Denied access prevents the Provider change from being saved, debounced volume updates never trigger permission prompts, insecure remote HTTP endpoints remain rejected, and the service worker checks the exact host permission again before sending captions or audio.
- Added deterministic origin normalization/deduplication, denial, grant, localhost bypass, Manifest least-privilege, popup wiring, and background enforcement tests plus a complete Chrome Web Store permission-justification document.

## 0.1.76 - 2026-07-11

- Strengthened the no-Engine caption path for Chrome Web Store users. The main-world probe now prioritizes the current `#movie_player` response and current `ytd-watch-flexy` player data before `ytInitialPlayerResponse`, which can remain bound to the previous video after YouTube SPA navigation.
- Added a same-origin `youtubei/v1/player` fallback when the current page exposes its client configuration but no usable tracks. The request contains only a minimal YouTube client context and the current video ID, and every response must match that video before its captions are accepted.
- Kept embedded-script extraction and the parallel yt-dlp Engine path intact. A page-only source track can still start after the existing short Engine-quality window, while a target-language page track wins immediately without translation or a companion install.
- Added shared player-response normalization, stale-versus-current selection tests, minimal Innertube request-construction tests, manifest load-order guards, and real-page evidence that current YouTube pages may hide live player methods while retaining embedded current-video caption data.

## 0.1.75 - 2026-07-11

- Added a Provider-neutral cache identity for target-language subtitle tracks supplied directly by YouTube. Once an existing Chinese, Japanese, or other requested-language track is fully cached, changing between Chrome local translation, DeepSeek, or another Provider no longer repeats yt-dlp extraction for text that was never AI-translated.
- Made target-language YouTube cache entries the first lookup candidate, followed by the selected Provider/model cache for genuinely translated timelines. This preserves strict isolation for AI output while accelerating the free direct-caption path.
- Reset cache provenance on every stopped session and restore it from the matched cache entry, preventing a previous video's YouTube-caption identity from leaking into a later translated timeline.
- Added deterministic lookup-order, Provider-isolation, direct-caption deduplication, source guards, privacy documentation, and development-audit coverage.

## 0.1.74 - 2026-07-11

- Connected the existing but previously unused caption-Engine auto-start routine to the real subtitle request path. A transport-level disconnect now triggers one bounded Native start attempt and retries the same HTTP caption request before falling back to direct Native captions.
- Limited automatic recovery to 4.5 seconds and one attempt. YouTube 429 responses, confirmed no-caption videos, unavailable/access-restricted videos, ordinary HTTP errors, and request timeouts never trigger a restart loop or consume extra caption attempts.
- Replaced raw Native Host and HTTP transport details in the YouTube panel with a concise recovery message. Technical errors remain available in extension/background diagnostics rather than occupying the customer-facing panel.
- Added deterministic recovery-decision tests and permanent source guards so the auto-start function cannot silently become disconnected from caption resolution again.

## 0.1.73 - 2026-07-11

- Hid the macOS system-voice cold start behind caption extraction and translation. A short silent warmup runs only on a cache miss, is reused for five minutes per target language and voice, and never blocks or disables the real playback fallback when it fails.
- Expanded live TTS lookahead from 10 to 18 seconds, from four to six semantic segments, and from two to three bounded local workers. This matches the already verified three-worker Engine capacity and gives dense subtitle timelines more room to finish before playback.
- Reduced the uncached local-audio wait from 650 ms to 250 ms. If a clip still is not ready near its subtitle boundary, browser speech starts on time while the local result continues into the in-memory cache for later playback.
- Cancelled queued TTS work whose semantic segment disappeared after a later translation batch reshaped the timeline, then immediately scheduled the refreshed segment window. Added permanent timing assertions and a repeatable six-segment, three-worker live TTS benchmark.

## 0.1.72 - 2026-07-11

- Added a privacy-bounded local cache for complete translated subtitle timelines. Reopening the same YouTube video with the same target language and translation Provider/model now skips repeated yt-dlp extraction and translation and starts from the cached timeline.
- Limited the cache to local Chrome extension storage, 7-day expiry, 12 videos, and approximately 4 MB measured as UTF-8 bytes. Audio, video, API keys, and incomplete rolling-transcription sessions are never cached.
- Added a default-on “缓存翻译字幕” control and a real “清除字幕缓存” action in the popup. Cache lookup, save, pruning, isolation, expiry, capacity, disable, and deletion behavior are covered by deterministic tests.
- Preserved the existing first-play workflow: new videos still prioritize target-language YouTube subtitles, then source subtitles plus the selected translator, while only fully covered timelines become reusable.

## 0.1.71 - 2026-07-11

- Added Engine protocol version 2 and exact Engine release identity to both HTTP and Native Messaging health payloads. Extension health now distinguishes a compatible Engine from any unrelated or outdated process that happens to return HTTP 200 on port 8787.
- Added shared compatibility assessment with three explicit states: matching release, different release but compatible protocol, and update required because identity or protocol is missing/old. Popup and YouTube indicators now render those states instead of showing every reachable Engine as green.
- Updated start and restart guidance to state that restarting does not replace old files. The install page directs users with an outdated runtime to rerun the matching Engine installer rather than repeatedly pressing restart.
- Preserved `release.json` when source code is atomically copied into the Application Support runtime. Development installs generate equivalent release metadata from the extension manifest, preventing installed Engine identity from disappearing after an update.
- Hardened `start_engine_macos.sh`, LaunchAgent installation, and the new Native Host so health requires the current protocol. A real isolated outdated HTTP Engine with no protocol field was detected, terminated, and replaced by the current Engine instead of being reported as already running.
- Added compatibility, health-version, Native Messaging, runtime-copy, package metadata, and legacy replacement regression checks. Engine release ZIP verification now rejects missing protocol metadata.

## 0.1.70 - 2026-07-11

- Added dynamic system-voice discovery through both `GET /api/voices` and Native Messaging. The popup and YouTube panel now use the voices actually installed on the customer's Mac instead of presenting a fixed list that may not exist on that system.
- Added a shared voice-selection module that merges Engine and browser voices, removes duplicates, filters by the current target language, keeps local voices first, and preserves an older saved selection visibly until the user changes it.
- Fixed macOS `say -v ?` parsing for names containing spaces or localized parentheses. Names such as `Bad News` and `Eddy (中文（中国大陆）)` are kept intact instead of being truncated to their first word.
- Hardened automatic voice fallback. An unavailable selected voice now falls back to an installed preferred voice, then an installed same-language voice, rather than sending an invalid name to `say` and losing local playback.
- Reset voice selection to automatic matching when the target language changes, preventing an English voice from remaining selected after switching to Chinese or Japanese.
- Added parser, selection, HTTP, Native Messaging, and browser harness coverage. Real verification found 175 installed voices (19 Chinese, 43 English, and 9 Japanese), preserved a multi-word voice ID, and generated a valid 2.48-second WAV with `Eddy (中文（中国大陆）)`.

## 0.1.69 - 2026-07-11

- Added a shared live voice timebox synchronizer for per-segment playback. The same calculation now owns late-start catch-up, current video playback rate, pause decisions, explicit-seek alignment, and the expected clip finish time instead of leaving those rules embedded in the page loop.
- Reserved 60 ms at the end of each semantic segment and raised bounded catch-up limits to 2.2x for short clips, 2.05x for medium clips, and 1.9x for longer clips. A delayed translation clip now aims to finish just before the source segment ends instead of being cut off by the next segment.
- Preserved every translated word during ordinary TTS delay. Proportional audio seeking remains limited to explicit user video seeks; clips that finish early wait in silence, following the timing strategy used by established open-source subtitle-to-speech tools without adding a heavy alignment runtime.
- Added deterministic late-start, 1.5x playback, pause, end, and seek tests plus a real HTMLMediaElement self-test page. The browser self-test measured a 4.4-second clip started one second late at 1.497x with an expected 4.940-second finish, and the 1.5x-video case at 2.213x with the same expected finish.
- Applied the synchronizer's pause decision during active video seeking, preventing a stale translated clip from continuing briefly while the YouTube playhead is being dragged.
- Recorded the automated browser autoplay limitation honestly: the in-app test browser rejects continuous media `play()` even for muted generated WAV files, so a loaded-extension Chrome playback check remains required before public release.

## 0.1.68 - 2026-07-11

- Added a real no-caption end-to-end verification using a public video with speech but no subtitle tracks. The Engine confirmed `NO_PUBLIC_CAPTIONS`, downloaded only the first 12 seconds of audio, and local whisper.cpp returned two timestamped English cues in 8.211 seconds without any paid API.
- Added `--ignore-no-formats-error` to yt-dlp caption metadata and subtitle commands so caption inspection is no longer blocked by unrelated media-format selection errors.
- Added explicit `VIDEO_UNAVAILABLE` handling across Engine, background router, and YouTube UI. Removed, private, members-only, age-restricted, and placeholder videos are no longer misreported as valid no-caption videos or sent into transcription.
- Skipped subtitle-file download when successful public and cookie-aware metadata contain no caption candidates. Live no-caption confirmation on `Iw44FF2bG9s` improved from 14.783 seconds to 6.909 seconds.
- Added one-minute failure backoff for unavailable videos and deterministic regression tests for availability metadata, HTTP status mapping, format-independent caption inspection, and no-candidate download skipping.

## 0.1.67 - 2026-07-11

- Fixed a real YouTube caption timeout reproduced against `jNQXAC9IVRw`. A rate-limited target-language translation track previously consumed the complete direct-fetch budget across multiple formats, so a healthy English source track was never attempted.
- Changed yt-dlp direct caption reads to round-robin across candidate tracks. Each translated and source track gets its best format attempted before any one track consumes additional fallback formats.
- Made subtitle-file download timeouts return to the bounded fallback flow instead of escaping as a raw `subprocess.TimeoutExpired` failure near the 22-second deadline.
- Added deterministic regression coverage for translated-track failure followed by immediate source-track success and for bounded subtitle-download timeout handling.
- Verified the fix with live YouTube requests: the previously failing video changed from `ENGINE_TIMEOUT` after 22.012 seconds to six usable source cues in 5.856 seconds; a target-Chinese video returned 60 translated cues in 5.442 seconds.

## 0.1.66 - 2026-07-11

- Made one-click local mode usable without a separate Ollama installation. It now combines Chrome on-device translation with local yt-dlp caption extraction, system TTS, and optional whisper.cpp transcription; Ollama remains available as an advanced provider.
- Removed the local Engine passthrough failure mode. When Ollama is selected but unavailable, translation now fails explicitly instead of returning original-language captions as if they were translated.
- Reworked semantic voice segments so adjacent subtitle fragments keep merging until punctuation or bounded gap, duration, cue-count, and character limits require a break. This reduces short TTS jobs and abrupt stop-start playback.
- Added a fast page-caption fallback: when the page already yielded usable captions, the extension waits only two additional seconds for a better Engine result instead of blocking the usable path for the full Engine deadline.
- Added deterministic regression tests for local-mode provider selection, Ollama failure handling, phrase grouping, timebox slack, and the shorter caption fallback.
- Kept all three mode-card descriptions fully visible in the compact popup height after the new local-mode wording.

## 0.1.65 - 2026-07-10

- Added build-time release metadata for the customer install view. Every extension ZIP now records its exact release channel, version, extension ID, matching macOS Engine filename, optional download/support links, and truthful signing/notarization state.
- Split the install guide into customer and developer views. Customer packages show the matching double-click Engine installer and recovery actions while hiding source checkout paths, Terminal commands, Python/port/cookie details, Native Host registration commands, and developer diagnostics.
- Added optional HTTPS Engine-download and support-page injection to the release builder. Unsafe non-HTTPS links stop the build, while an offline private beta clearly tells testers to obtain both ZIPs from the same release.
- Extended package verification to require the install-page assets, release-channel visibility rules, customer/developer markers, normalized release metadata, exact artifact identity, and HTTPS-only configured links.
- Documented the hosted and offline private-beta build flows and added permanent regression rules so future releases cannot silently expose developer setup instructions to customers.

## 0.1.64 - 2026-07-10

- Added a repeatable private-beta release builder. One command now creates a Chrome Web Store ZIP with `manifest.json` at its root, an ID-bound macOS Engine ZIP, and a SHA-256 checksum list.
- Added three customer-facing double-click commands to the macOS bundle: install the main Engine, optionally install no-caption whisper.cpp, and uninstall Engine/Native Host/login auto-start. The main installer prepares dependencies before registration and does not report success when Engine health fails.
- Bound every Engine bundle to a validated 32-character Chrome extension ID and wrote that ID into Native Messaging `allowed_origins`. Invalid IDs are rejected before any installation change.
- Added a complete Native Host uninstaller with manifest identity checks, runtime removal, optional cache/log purge, and a safe dry-run. Local Whisper models are intentionally retained for faster reinstall.
- Added package verification for unsafe paths, leaked development environments, API-key-like strings, missing Manifest references, unresolved templates, release metadata, extension-ID wiring, and unsigned/unnotarized truthfulness.
- Added an isolated macOS installer smoke test that unpacks the real ZIP, checks executable permissions, generates temporary LaunchAgent and Native Host manifests, validates absolute launcher paths and allowed origins, and runs uninstall dry-run without changing Chrome or the installed Engine.
- Added private-beta customer instructions and a release-process document. The extension install page no longer claims the installer is merely future work and clearly distinguishes the current unsigned beta bundle from the still-required signed/notarized public installer.

## 0.1.63 - 2026-07-10

- Accelerated complete-track generation with a bounded three-worker TTS pool. Independent `say` and ffmpeg segment jobs run concurrently in separate directories, then results are sorted back onto the original timeline before WAV assembly.
- Reused the live playback semantic segments for complete-track input. Fragmented nearby captions are synthesized as one spoken phrase with the same start, natural end, silence slack, and next-segment hard boundary instead of launching a process for every raw caption cue.
- Made active `say` and duration-fitting ffmpeg processes cancellable. Cancelling a render now terminates all running workers promptly and prevents pending workers or partial output from surviving the job.
- Added worker count to job metadata and page progress, so the panel reports when semantic voice segments are being generated with parallel workers.
- Reduced cancellable child-process polling from 200 ms to 50 ms while keeping the latency-free `subprocess.run` path for normal live TTS calls that have no cancellation token.
- Added parallel overlap, cancellation, timeline-duration, semantic-segment fallback, and output-order regression tests plus a repeatable macOS benchmark tool. Nine real system-TTS segments improved from 5.689 seconds with one worker to 2.603 seconds with three workers, a 2.19x speedup, with identical 12-second WAV duration and byte size.

## 0.1.62 - 2026-07-10

- Fixed a complete-track startup race found with real Chrome media elements. When YouTube emits `waiting` while starting, pausing the dub track can intentionally reject its first `play()` with `AbortError`; this is now treated as a recoverable buffer transition and playback retries after the video resumes.
- Deduplicated pending `audio.play()` requests so the animation loop cannot create dozens of overlapping playback promises while metadata or a byte range is still loading.
- Added preview operation IDs. Quickly stopping a track while its first play request is pending no longer reports a stale false failure or lets an old promise mutate the next preview session.
- Added direct handling for video `waiting`, `playing`, `pause`, `seeked`, `ended`, and `ratechange` events. The dub track now pauses during buffering and seeking, resumes after the video, follows rate changes immediately, and exits preview cleanly when the video ends.
- Moved media-side mute, volume, drift, seek, pause, play, and stop decisions into a deterministic helper that is covered with fake media-element tests.
- Added a real-browser media harness using the same helper. Chrome verification covered start, pause/resume, a four-second seek, 1.5x playback, and end-of-track cleanup; measured drift stayed between 8 ms and 57 ms in those checks.

## 0.1.61 - 2026-07-10

- Added in-page playback for completed pure-voice and mixed M4A/WAV tracks. The complete track follows YouTube play, pause, playback speed, and progress-bar seeking instead of requiring a separate media player.
- Added a deterministic full-track synchronizer: drift up to 180 ms is corrected with a bounded 3% speed adjustment, while larger drift and explicit seeks realign the audio clock directly to the video timeline.
- Mixed-track preview now mutes the YouTube element so the original soundtrack cannot play twice. Pure-voice preview keeps the visible original mute and volume controls active.
- Isolated complete-track preview from live per-cue TTS. Queued or awaiting voice clips and browser-speech fallbacks cannot start over the full track, and stopping preview deliberately resets live-cue state before resuming.
- Added HTTP `HEAD` and single-byte-range support for rendered tracks, including `206 Content-Range`, suffix/open-ended ranges, `416` handling, inline preview disposition, CORS headers, and bounded streaming. Long M4A files can load metadata and seek without reading the whole file first.
- Added helper, parser, static wiring, and installed-runtime regression checks for drift correction, preview guards, media response headers, and byte-range edge cases.

## 0.1.60 - 2026-07-10

- Added complete-track output format selection: `M4A 小文件` is the new default for practical long-video downloads, while `WAV 无损` remains available for editing and lossless workflows.
- Kept timing and mixing on the exact PCM WAV timeline, then added a separate cancellable ffmpeg AAC encoding stage. Compression cannot move cue boundaries or change the already assembled voice timing.
- Added 96 kbps AAC/M4A output with fast-start metadata, format-aware filenames, cache keys, cleanup, download MIME types, job metadata, and page progress for the encoding stage.
- Added ffprobe duration verification when available, with a bounded tolerance for AAC container delay. The Engine still works when ffprobe is unavailable because ffmpeg produces the file from the exact-duration WAV intermediate.
- Changing the output format invalidates a stale render. The two compact selectors now independently control pure/mixed content and M4A/WAV delivery without adding another setup screen.
- Added real local encoding tests, compression-size checks, MIME checks, format validation, cache-key separation, and a complete M4A job test through synthesis, timeline assembly, encoding, and job completion.

## 0.1.59 - 2026-07-10

- Added an export-mode selector for `纯配音 WAV` and `配音 + 原声混合`. Pure voice export remains the default and does not download the source audio.
- Mixed export reuses the audio-only yt-dlp path, applies the current original-volume setting, and combines the source audio with the cue-aligned voice track through ffmpeg. It never downloads or remuxes the video stream.
- Mixed output trims both inputs to the video timeline, resets their timestamps, preserves exact duration, converts to mono 22.05 kHz PCM WAV, and uses a latency-compensated limiter to avoid clipping without shifting the translated voice.
- Added cancellable `downloading-original` and `mixing` job stages, mode-aware filenames and progress labels, cache keys that include mix parameters, and private handling for the source video URL.
- Changing the export mode, voice, or mixed-track original volume now invalidates stale output so a downloaded track always matches the visible controls.
- Added deterministic and real local ffmpeg tests for command construction, source-volume attenuation, voice presence inside cue windows, duration alignment, mixed-job completion, and source-URL privacy.
- Fixed an Engine-update regression where atomically replacing the Application Support runtime removed Native Host's recorded Python path. The launcher now prefers its adjacent private `.venv`, includes that environment's binaries in `PATH`, and every auto-start installation recreates the path record, preventing false `yt-dlp`-missing reports after updates or reboot.

## 0.1.58 - 2026-07-10

- Added complete translated voice-track rendering. After a full caption timeline is ready, the YouTube panel can start a cancellable Engine job that synthesizes every translated cue and produces one downloadable WAV track.
- Refactored live TTS and batch rendering to share the same macOS `say`, PCM validation, adaptive request rate, and ffmpeg `atempo` fitting path. Batch rendering allows up to 4.5x pitch-preserving fitting for extreme cue lengths.
- Added a streaming PCM timeline writer: each voice clip starts at its cue timestamp, silence fills gaps, overlapping source cues are bounded by the next cue, and a clip can never spill into the following segment. The writer does not hold the full two-hour track in memory.
- Added start/status/cancel/download APIs with one-heavy-job exclusion, random job IDs, progress by rendered cue count, direct localhost attachment download, and automatic cache cleanup after one hour. Large WAV data never passes through Chrome or Native Messaging, and no `downloads` permission is required.
- The page uses a two-click-safe workflow: generate first, then the button becomes “下载配音音轨” so the final localhost download has a fresh user gesture. Changing the voice or stopping dubbing invalidates/cancels stale renders.
- Added deterministic tests for cue normalization, adaptive rates, silence placement, millisecond-aligned samples, hard segment boundaries, private job fields, task completion, and WAV duration.

## 0.1.57 - 2026-07-10

- Added one-shot full-video transcription for local no-caption mode. The Engine downloads only a low-bitrate audio stream, runs local whisper.cpp once over the complete file, deletes temporary audio, and returns a complete timestamped cue timeline.
- Full transcription runs as a cancellable background job with start/status/cancel HTTP APIs, stage progress, one-heavy-job concurrency, one-hour result retention, and a configurable two-hour video limit. Large audio never passes through Chrome or Native Messaging.
- The YouTube panel now offers “准备完整字幕” only during local rolling no-caption sessions. It shows progress, can cancel, pauses at the prepared boundary when necessary, replaces rolling cues atomically, translates the full timeline, and resumes playback.
- Completed full no-caption timelines now become `complete` SRT/WebVTT exports. Failed final translation keeps the source timeline retryable instead of discarding the transcription result.
- Added regression coverage for the audio-only yt-dlp command, URL/duration validation, heavy-job exclusion, private/public job fields, completion state, and timestamped cue output.

## 0.1.56 - 2026-07-10

- Added subtitle export to the YouTube panel. Users can download the translated timeline as UTF-8 SRT or WebVTT without granting Chrome's broad downloads permission.
- Captioned videos label the file `complete` only after every source cue has a translated counterpart. Rolling no-caption sessions export the currently prepared range as `partial` instead of representing it as a complete transcript.
- Export normalization sorts cues, removes empty content, prefers translated text, repairs invalid cue endings, preserves multiline subtitles, and uses safe video/language filenames. SRT includes a UTF-8 BOM for better compatibility with desktop players.
- Changing target language or translation provider during an active session now cancels and clears the old pipeline before restart, preventing mixed-language timelines and exports.
- Added deterministic SRT/WebVTT serialization tests covering ordering, timestamp rounding, translated-text precedence, line endings, and empty timelines.

## 0.1.55 - 2026-07-10

- Added a macOS user LaunchAgent that starts LocalTube Dub Engine automatically at login and restarts it after an unexpected exit. Installation creates a self-contained runtime under `~/Library/Application Support/LocalTube Dub/engine-runtime`, uses a stable PATH, and writes persistent logs under `~/Library/Logs/LocalTube Dub`.
- Native Host and Engine no longer execute from a development checkout under `~/Documents`. macOS can block background LaunchAgents while they open privacy-protected Documents files, leaving a Python process alive but never opening port 8787; both entry points now run from Application Support instead.
- Native Host registration now installs Engine login auto-start at the same time. The install guide also includes a one-click “修复开机自启” action and a copyable manual command for repairing the service later.
- The auto-start installer only terminates a process after confirming that port 8787 belongs to `local_dub_server.py`; it refuses to replace unrelated software using that port.
- Prevented a LaunchAgent/Native Host restart race: when launchd has already restored Engine, Native Host reuses the healthy instance instead of spawning a second server on port 8787.
- Added a matching uninstall script, dry-run plist generation, and release checks for the full auto-start wiring.

## 0.1.54 - 2026-07-10

- Wired each voice segment's original subtitle duration through content, background, HTTP, and Native TTS payloads. The fitting target no longer includes optional silence after the cue.
- Local macOS TTS now measures the generated WAV instead of relying only on a character-count estimate. When speech is too long, ffmpeg `atempo` compresses it toward the subtitle duration while preserving pitch.
- Added bounded multi-stage `atempo` filters for rates above 2x and capped Engine fitting at 3x. Browser playback-rate correction remains available for small startup drift instead of carrying the full timing mismatch.
- TTS responses now expose actual fitted duration and fit rate, with regression tests for protocol propagation, WAV duration validation, and filter construction.

## 0.1.53 - 2026-07-10

- Added local YouTube audio-window transcription at `/api/transcribe-video`. The Engine validates YouTube-only URLs, asks yt-dlp for only the requested time range, and sends that audio window to local whisper.cpp.
- Local no-caption mode now tries a 30-second Engine window before playing/recording the current video. Direct player and tab recording remain as compatibility fallbacks.
- Added rolling ahead-of-playback transcription: while a no-caption video plays, the extension starts the next 45-second Engine window with an 18-second lead, merges overlap cues, translates them, and refreshes voice prefetch continuously.
- Each newly translated rolling window now prewarms its nearest voice segment before a boundary buffer is released, reducing first-word delay after the video resumes.
- Added boundary buffering so playback briefly pauses only when the next translated window is still being prepared, then resumes automatically. Failed windows release the buffer and retry after a cooldown instead of leaving the video stuck.
- Silent/music-only windows now advance transcription coverage without being reported as Engine failures, allowing rolling transcription to continue until speech returns.
- Added HTTP-first and Native Messaging fallback routes for video-window transcription plus behavioral tests for command construction, URL restrictions, timestamp offsets, silence handling, and overlap deduplication.
- Prevented duplicate 90-second transcription waits: Native fallback now runs only when HTTP is unreachable or the endpoint is missing, not after the Engine already returned a processing error or timeout.
- A current-video page response with a matching video ID and an empty caption track list can now confirm no captions after the parallel Engine check. Temporary caption Engine errors no longer block the transcription fallback when the page itself has authoritative no-caption evidence.
- Rolling video windows now carry cancellable request IDs through the existing transcription registry. Stop, seek, timeout, or a newer session aborts the waiting HTTP/Native route so stale window results cannot mutate the current timeline.
- Fixed the in-page status layout that squeezed long Chinese progress/errors into a narrow vertical strip beside the two action buttons. Status text now occupies a readable full-width row below them.

## 0.1.52 - 2026-07-10

- Fixed the free hybrid path so Chrome local translation can now be combined with local whisper.cpp transcription. The popup previously hid `本地 Engine` from the BYOK/free transcription selector and silently changed it back to Groq.
- Made local Engine transcription the default for new installs, while keeping Groq, Deepgram, and OpenAI available for users who prefer their own transcription API.
- Local transcription now prefers the already-running HTTP Engine at `/api/transcribe` and falls back to Native Messaging only when needed. This removes the false failure where Engine health was green but transcription still failed because the Native Host was unavailable.
- Engine status now verifies local Whisper when no-caption local transcription is enabled instead of showing a misleading green state based only on yt-dlp.
- The one-click local transcription installer now starts the Engine when it was offline, or restarts it when already running, so installation finishes in a directly usable state.
- Fixed extension enable/disable lifecycle handling: turning the extension off now stops dubbing and removes its YouTube UI immediately, while turning it back on remounts the panel without requiring a page refresh.
- Fixed a voice-clipping synchronization bug: hiding the translated subtitle during a short cue gap no longer stops active local or browser speech before its segment timebox ends.
- Separated normal TTS generation delay from explicit video seeking: a late voice clip now starts from the beginning and speeds up to fit, while proportional audio seeking is reserved for a real progress-bar jump so translated words are not silently skipped.
- Fixed a TTS queue lifecycle race that could leave discarded prefetch promises pending forever or reset concurrency while old work was still active. Stop/restart now explicitly cancels queued voice tasks and lets active generation finish cleanly.
- Added translation count recovery for API providers and local Ollama. A malformed batch with missing or empty items is automatically retried as smaller halves instead of silently substituting original text or failing the entire remaining video; real network/quota errors are still returned immediately.
- Added `docs/development-audit.md` to preserve the reviewed architecture, verified workflows, historical regression rules, release checks, and known unfinished product gaps.
- Added regression checks that keep translation and transcription providers independent and ensure the HTTP-to-Native transcription fallback remains wired.

## 0.1.51 - 2026-07-10

- Added a free local no-caption transcription path with whisper.cpp instead of requiring a Groq, Deepgram, or OpenAI transcription key.
- Added a fixed macOS installer for Homebrew `whisper-cpp`, `ffmpeg`, and the multilingual `base` model (about 142 MB) stored under the user's Application Support folder.
- Added Native Host `install-whisper` support so the install page can start the fixed installer in the background with one click and poll Engine health until transcription is ready.
- The local transcription installer now restarts a running Engine after installation so the new whisper.cpp adapter becomes visible without a manual restart.
- Added WebM/MP4 audio conversion to mono 16 kHz PCM WAV before whisper.cpp inference.
- Added whisper.cpp JSON and timestamp normalization so its segments feed the existing subtitle translation and dubbing timeline.
- Kept the existing OpenAI Whisper CLI and custom command support as fallbacks.
- Moved “无字幕时自动转写” into the always-visible quick settings so local-mode users can explicitly enable recording and whisper.cpp transcription; previously the consent toggle was hidden inside the BYOK-only panel.

## 0.1.50 - 2026-07-10

- Added `Chrome 本地翻译（免费）` using Chrome's built-in desktop Translator API. Subtitle text can now be translated by Chrome's on-device language packs without an API key or Ollama.
- Made the free Chrome translator the default for new installs while retaining DeepSeek, Microsoft, Google Cloud, OpenAI, Gemini, Claude, OpenRouter, custom endpoints, and local Ollama as selectable alternatives.
- Added first-click language-pack warmup and download progress in the YouTube panel so Chrome can start a required model download while the start-button user activation is still valid.
- Added optional built-in language detection when a subtitle source language is not known.
- Kept the fast path unchanged: existing target-language YouTube captions still bypass all translation providers and go directly to dubbing.
- Added local Translator errors that distinguish unsupported Chrome versions, unsupported language pairs, and a language pack that needs another user click.

## 0.1.49 - 2026-07-10

- Added a real end-to-end time budget to the yt-dlp caption Engine, so direct caption URL attempts, metadata lookup, cookie retry, and subtitle-file fallback share one bounded deadline instead of each consuming a full timeout.
- Removed the expensive `all` subtitle download fallback. The Engine now downloads only the target language, source language, English, and a small set of languages found in yt-dlp metadata.
- Limited repeated caption URL format attempts and reserved time for yt-dlp's subtitle-file fallback, improving the chance of a useful result within the extension's 30-second wait window.
- Added TTML `begin` / `end` / `dur` parsing to the Engine so downloaded TTML captions keep their real timeline instead of collapsing near zero.
- Cached Engine dependency health briefly and reduced the Ollama probe timeout so BYOK caption checks remain responsive when Ollama is not running.
- Fixed browser TTS synchronization: browser speech now pauses and resumes with YouTube, stops at the subtitle timebox, and does not let the next segment cancel the current one before its allotted window ends.
- Added late-start compensation for both local audio and browser TTS. Local audio seeks into a delayed clip and browser speech raises its rate from the remaining subtitle time instead of the original full window.
- Fixed macOS local TTS output: the Engine now asks `say` for browser-compatible PCM WAV and validates that the file contains real audio frames. Header-only or invalid files now trigger browser speech fallback instead of being treated as successful silent dubbing.
- Tightened target-caption matching so Simplified Chinese, Traditional Chinese, and Brazilian Portuguese are not treated as interchangeable merely because they share the same base language code.
- Fixed the actual post-reboot yt-dlp regression found during runtime verification: Apple's Python 3.9 could only install an obsolete yt-dlp release, which YouTube rejected with `The page needs to be reloaded`. The macOS dependency script now requires Python 3.10+, installs current Homebrew Python when needed, creates a project `.venv`, and makes Terminal plus Native Host use that same interpreter.

## 0.1.48 - 2026-07-09

- Changed voice preloading to a low-latency rolling cache: prioritize the current segment first, then cache only the next few nearby segments instead of doing a large prefetch.
- Added voice timeboxes that can use a small silence gap before the next subtitle, so dubbed audio can finish naturally without overlapping the next line.
- Updated playback sync to align audio against each segment's timebox and adjust playback rate from real audio duration.
- Updated AI translation prompts to request shorter, spoken dubbing-friendly translations when subtitle duration is known.
- Reduced first-voice wait time so starting playback is not blocked by a long prewarm.
- Added a short live fallback wait: if local audio is not ready near the segment start, browser speech starts the line instead of letting the dub drift late.

## 0.1.47 - 2026-07-09

- Added Engine self-recovery: when the HTTP Engine is offline but Native Host is available, the extension now tries to auto-start the HTTP Engine before showing an error.
- Hardened one-click start/restart: if Chrome reports `Native host has exited`, the extension re-checks HTTP health because the Engine may have started successfully before the Native Host process closed.
- Added a macOS Native Host launcher that restores a stable PATH for Chrome after reboot, records the terminal `python3` path during install, then starts `native_host.py` with the same Python.
- Added Native Host logs and Engine launch logs to make repeated startup failures diagnosable.
- Added Native Host install and diagnostic instructions to the install page.
- Started this changelog so future version bumps record what changed and why.

## Earlier Development Notes

- 0.1.46 focused on voice timing safeguards so late segments are skipped less aggressively.
- 0.1.41-0.1.45 improved segment-based dubbing sync, voice prewarm, and local TTS fallback behavior.
- 0.1.36-0.1.40 improved target-language subtitle preference and yt-dlp Engine subtitle extraction.
- 0.1.28-0.1.35 added Engine start/restart controls, Engine status UI, and local subtitle/TTS flows.
