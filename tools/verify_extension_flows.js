const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const helpers = require(path.join(root, "extension", "content_helpers.js"));
const backgroundHelpers = require(path.join(root, "extension", "background_helpers.js"));
const installHelpers = require(path.join(root, "extension", "install_helpers.js"));
const pageProbeHelpers = require(path.join(root, "extension", "page_probe_helpers.js"));
const permissionHelpers = require(path.join(root, "extension", "permission_helpers.js"));
const voiceHelpers = require(path.join(root, "extension", "voice_helpers.js"));

function testOptionalHostPermissions() {
  assert.equal(permissionHelpers.optionalOriginForEndpoint("https://api.deepseek.com/chat/completions"), "https://api.deepseek.com/*");
  assert.equal(permissionHelpers.optionalOriginForEndpoint("http://127.0.0.1:8787/api/dub"), "");
  assert.equal(permissionHelpers.optionalOriginForEndpoint("https://www.youtube.com/youtubei/v1/player"), "");
  assert.deepEqual(
    permissionHelpers.collectOptionalOrigins([
      "https://api.openai.com/v1/chat/completions",
      "https://api.openai.com/v1/audio/transcriptions",
      "https://api.groq.com/openai/v1/audio/transcriptions"
    ]),
    ["https://api.openai.com/*", "https://api.groq.com/*"]
  );
  assert.throws(
    () => permissionHelpers.optionalOriginForEndpoint("http://remote.example.com/v1"),
    /必须使用 https/
  );
  assert.deepEqual(permissionHelpers.optionalCapturePermissions(true), ["tabCapture", "offscreen"]);
  assert.deepEqual(permissionHelpers.optionalCapturePermissions(false), []);
}

function testPageProbePlayerResponseSelection() {
  const track = (videoId, languageCode) => ({
    videoDetails: { videoId },
    captions: {
      playerCaptionsTracklistRenderer: {
        captionTracks: [
          {
            baseUrl: `https://www.youtube.com/api/timedtext?v=${videoId}&lang=${languageCode}`,
            languageCode,
            kind: "",
            name: { simpleText: languageCode },
            isTranslatable: true
          }
        ]
      }
    }
  });
  const selected = pageProbeHelpers.selectCurrentPlayerResponse(
    [JSON.stringify(track("old-video", "en")), track("current-video", "ja")],
    "current-video"
  );
  assert.equal(selected.videoDetails.videoId, "current-video");
  assert.equal(selected.captions.playerCaptionsTracklistRenderer.captionTracks[0].languageCode, "ja");
  const currentWithoutCaptions = pageProbeHelpers.selectCurrentPlayerResponse(
    [track("old-video", "en"), { videoDetails: { videoId: "current-video" } }],
    "current-video"
  );
  assert.equal(currentWithoutCaptions.videoDetails.videoId, "current-video");
  assert.equal(currentWithoutCaptions.captions.playerCaptionsTracklistRenderer.captionTracks.length, 0);

  const playerRequest = helpers.makeInnertubePlayerRequest(
    {
      apiKey: "public-key/value",
      clientNameId: 1,
      clientVersion: "2.20260711.00.00",
      context: {
        client: {
          clientName: "WEB",
          clientVersion: "2.20260711.00.00",
          hl: "zh-CN",
          gl: "TW",
          visitorData: "visitor"
        },
        unrelated: { shouldNotCrossWorlds: true }
      }
    },
    "current-video"
  );
  assert.match(playerRequest.url, /youtubei\/v1\/player\?key=public-key%2Fvalue&prettyPrint=false/);
  assert.equal(playerRequest.headers["x-youtube-client-name"], "1");
  const requestBody = JSON.parse(playerRequest.body);
  assert.equal(requestBody.videoId, "current-video");
  assert.equal(requestBody.context.client.visitorData, "visitor");
  assert.equal(Object.hasOwn(requestBody.context, "unrelated"), false);
  assert.equal(helpers.makeInnertubePlayerRequest({ apiKey: "missing-version" }, "current-video"), null);
}

function testVoiceOptions() {
  const merged = voiceHelpers.mergeVoiceOptions(
    [
      { id: "Bad News", name: "Bad News", language: "en_US", localService: true },
      { id: "Meijia", name: "Meijia", language: "zh_TW", localService: true },
      { id: "Tingting", name: "Tingting", language: "zh_CN", localService: true }
    ],
    [
      { name: "Bad News", lang: "en-US", localService: false },
      { name: "Browser Chinese", lang: "zh-CN", localService: false }
    ]
  );
  assert.equal(merged.length, 4);
  assert.equal(merged[0].id, "Bad News");
  assert.equal(merged[0].language, "en-US");
  const chinese = voiceHelpers.selectVoiceOptions(merged, "zh-CN", "auto");
  assert.deepEqual(chinese.map((voice) => voice.id).sort(), ["Browser Chinese", "Meijia", "Tingting"].sort());
  assert.equal(chinese[0].localService, true);
  const preserved = voiceHelpers.selectVoiceOptions(merged, "zh-CN", "Samantha");
  assert.equal(preserved[0].id, "Samantha");
  assert.match(preserved[0].name, /当前设置/);
  const fallback = voiceHelpers.selectVoiceOptions([], "zh-CN", "auto", [
    { id: "Tingting", name: "中文女声 Tingting" },
    { id: "Samantha", name: "英文女声 Samantha" }
  ]);
  assert.equal(fallback.length, 2);

  const natural = voiceHelpers.selectVoiceOptions(
    voiceHelpers.mergeVoiceOptions(merged, [
      {
        id: "zh-CN-XiaoxiaoNeural",
        name: "晓晓（自然女声）",
        language: "zh-CN",
        provider: "edge",
        localService: false
      }
    ]),
    "zh-CN",
    "auto",
    [],
    { provider: "edge" }
  );
  assert.deepEqual(natural.map((voice) => voice.id), ["zh-CN-XiaoxiaoNeural"]);
  assert.equal(natural[0].provider, "edge");
}

function testEngineCompatibility() {
  assert.deepEqual(
    backgroundHelpers.assessEngineCompatibility(
      { service: "localtube-dub", engineVersion: "0.1.82", protocolVersion: 2 },
      2,
      "0.1.82"
    ),
    {
      compatible: true,
      upgradeRequired: false,
      versionMismatch: false,
      engineVersion: "0.1.82",
      protocolVersion: 2,
      expectedVersion: "0.1.82",
      requiredProtocol: 2,
      serviceMatches: true
    }
  );
  assert.equal(
    backgroundHelpers.assessEngineCompatibility({ service: "localtube-dub" }, 2, "0.1.82").upgradeRequired,
    true
  );
  assert.equal(
    backgroundHelpers.assessEngineCompatibility(
      { service: "localtube-dub", engineVersion: "0.1.71", protocolVersion: 2 },
      2,
      "0.1.82"
    ).versionMismatch,
    true
  );
  assert.equal(
    backgroundHelpers.assessEngineCompatibility(
      { service: "other", engineVersion: "0.1.82", protocolVersion: 9 },
      2,
      "0.1.82"
    ).compatible,
    false
  );
}

function testProviderFailureClassification() {
  assert.equal(
    backgroundHelpers.classifyProviderFailure(401, "Authentication Fails, Your api key: ****79ce is invalid"),
    "PROVIDER_AUTH_FAILED"
  );
  assert.equal(backgroundHelpers.classifyProviderFailure(402, "Insufficient balance"), "PROVIDER_QUOTA_EXCEEDED");
  assert.equal(backgroundHelpers.classifyProviderFailure(429, "Too Many Requests"), "PROVIDER_RATE_LIMITED");
  assert.equal(backgroundHelpers.classifyProviderFailure(404, "model does not exist"), "PROVIDER_MODEL_INVALID");
  assert.equal(backgroundHelpers.classifyProviderFailure(403, "Forbidden"), "PROVIDER_PERMISSION_DENIED");
  assert.equal(backgroundHelpers.classifyProviderFailure(0, "request timed out"), "PROVIDER_TIMEOUT");
  const authMessage = backgroundHelpers.providerFailureMessage("DeepSeek", "PROVIDER_AUTH_FAILED", 401);
  assert.equal(authMessage, "DeepSeek API Key 无效、已失效或不属于该服务。");
  assert.doesNotMatch(authMessage, /79ce|\*\*\*\*/);
}

function testCaptionEngineAutoStartDecision() {
  assert.equal(
    backgroundHelpers.shouldAutoStartCaptionEngine({
      status: 0,
      code: "CAPTION_ENGINE_UNAVAILABLE",
      error: "HTTP Engine: Failed to fetch"
    }),
    true
  );
  assert.equal(
    backgroundHelpers.shouldAutoStartCaptionEngine({ status: 0, error: "connect ECONNREFUSED 127.0.0.1:8787" }),
    true
  );
  assert.equal(
    backgroundHelpers.shouldAutoStartCaptionEngine({ status: 429, code: "YOUTUBE_RATE_LIMITED", error: "HTTP 429" }),
    false
  );
  assert.equal(
    backgroundHelpers.shouldAutoStartCaptionEngine({ status: 404, code: "NO_PUBLIC_CAPTIONS", error: "HTTP 404" }),
    false
  );
  assert.equal(
    backgroundHelpers.shouldAutoStartCaptionEngine({ status: 504, code: "ENGINE_TIMEOUT", error: "HTTP 504" }),
    false
  );
  assert.equal(
    backgroundHelpers.shouldAutoStartCaptionEngine({ status: 0, code: "ENGINE_TIMEOUT", error: "request timed out" }),
    false
  );
}

function testTimelineCache() {
  const now = 2_000_000;
  const request = { videoId: "Video A", targetLanguage: "zh-CN", provider: "chrome-translator", model: "default" };
  const first = backgroundHelpers.upsertTimelineCache(
    null,
    request,
    {
      sourceLanguage: "en",
      cues: [
        { id: "1", start: 0, end: 1.2, text: "Hello", translatedText: "你好" },
        { id: "2", start: 1.3, end: 2.4, text: "World", translatedText: "世界" }
      ]
    },
    { now, ttlMs: 60000, maxEntries: 2 }
  );
  assert.equal(first.entries.length, 1);
  assert.equal(first.entries[0].cues.length, 2);
  assert.equal(backgroundHelpers.findTimelineCache(first, request, { now: now + 1000, ttlMs: 60000 }).entry.sourceLanguage, "en");
  assert.equal(
    backgroundHelpers.findTimelineCache(first, { ...request, targetLanguage: "ja-JP" }, { now: now + 1000 }).entry,
    null
  );
  assert.equal(
    backgroundHelpers.findTimelineCache(first, { ...request, provider: "deepseek" }, { now: now + 1000 }).entry,
    null
  );
  assert.equal(
    backgroundHelpers.findTimelineCache(first, { ...request, model: "another-model" }, { now: now + 1000 }).entry,
    null
  );
  assert.equal(backgroundHelpers.findTimelineCache(first, request, { now: now + 60001, ttlMs: 60000 }).entry, null);

  const lookupRequests = helpers.makeTimelineCacheLookupRequests(request);
  assert.deepEqual(lookupRequests, [
    { ...request, provider: "youtube-captions", model: "" },
    request
  ]);
  assert.deepEqual(
    helpers.makeTimelineCacheLookupRequests({ ...request, provider: "youtube-captions", model: "ignored" }),
    [{ ...request, provider: "youtube-captions", model: "" }]
  );
  const youtubeCache = backgroundHelpers.upsertTimelineCache(
    null,
    lookupRequests[0],
    {
      sourceLanguage: "zh-CN",
      cues: [{ id: "yt", start: 0, end: 1.2, text: "YouTube 中文", translatedText: "YouTube 中文" }]
    },
    { now }
  );
  const crossProviderHit = helpers
    .makeTimelineCacheLookupRequests({ ...request, provider: "deepseek", model: "deepseek-chat" })
    .map((candidate) => backgroundHelpers.findTimelineCache(youtubeCache, candidate, { now }).entry)
    .find(Boolean);
  assert.equal(crossProviderHit.provider, "youtube-captions");

  let limited = first;
  for (let index = 0; index < 3; index += 1) {
    limited = backgroundHelpers.upsertTimelineCache(
      limited,
      { ...request, videoId: `video-${index}` },
      { cues: [{ start: 0, end: 1, text: `source-${index}`, translatedText: `target-${index}` }] },
      { now: now + index + 1, ttlMs: 60000, maxEntries: 2 }
    );
  }
  assert.equal(limited.entries.length, 2);
  assert.equal(limited.entries[0].videoId, "video-2");
  const invalid = backgroundHelpers.upsertTimelineCache(
    null,
    request,
    { cues: [{ start: 0, end: 1, text: "source", translatedText: "" }] },
    { now }
  );
  assert.equal(invalid.entries.length, 0);
  const oversized = backgroundHelpers.upsertTimelineCache(
    null,
    request,
    { cues: [{ start: 0, end: 1, text: "源".repeat(500), translatedText: "译".repeat(500) }] },
    { now, maxBytes: 1024 }
  );
  assert.equal(oversized.entries.length, 0, "UTF-8 cache limit must count multibyte text bytes");
}

function testCaptionTrackPicking() {
  const tracks = [
    { languageCode: "en", kind: "asr", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=en&kind=asr" },
    { languageCode: "ja", kind: "", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=ja" },
    { languageCode: "en-GB", kind: "", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=en-GB" }
  ];

  assert.equal(helpers.pickCaptionTrack(tracks, "auto"), tracks[2]);
  assert.equal(helpers.pickCaptionTrack(tracks, "ja-JP"), tracks[1]);
  const asrOnly = [{ languageCode: "es", kind: "asr" }];
  assert.equal(helpers.pickCaptionTrack(asrOnly), asrOnly[0]);

  const chineseTracks = [
    { languageCode: "zh-TW", kind: "", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=zh-TW" },
    { languageCode: "zh-Hans", kind: "", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=zh-Hans" }
  ];
  assert.equal(helpers.pickCaptionTrack(chineseTracks, "zh-CN"), chineseTracks[1]);
  assert.equal(helpers.pickCaptionTrack(chineseTracks, "zh-TW"), chineseTracks[0]);
  assert.equal(helpers.normalizeCaptionLanguage("zh-Hans-en"), "zh-hans");
  assert.equal(helpers.normalizeCaptionLanguage("zh-Hant-en"), "zh-hant");
  assert.equal(helpers.normalizeCaptionLanguage("pt-BR-en"), "pt-br");
}

function testCaptionRequestBudget() {
  const rankedTracks = [
    { id: "target-manual", languageCode: "zh-Hans", kind: "", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=zh-Hans" },
    { id: "target-translated", languageCode: "zh-CN", kind: "asr", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=en&tlang=zh" },
    { id: "target-alias", languageCode: "zh-CN", kind: "asr", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=en&tlang=zh-Hans" },
    { id: "source-manual", languageCode: "en", kind: "", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=en" },
    { id: "source-asr", languageCode: "en", kind: "asr", baseUrl: "https://www.youtube.com/api/timedtext?v=v1&lang=en&kind=asr" }
  ];
  assert.deepEqual(
    helpers.limitCaptionTrackAttempts(rankedTracks, "zh-CN").map((track) => track.id),
    ["target-manual", "target-translated", "source-manual"],
    "page caption lookup must bound target aliases and still reserve one source-language attempt"
  );

  const candidates = helpers.makeCaptionFetchCandidates(rankedTracks[0].baseUrl);
  assert.equal(candidates.length, 3);
  assert.equal(candidates[0], rankedTracks[0].baseUrl);
  assert.equal(new URL(candidates[1]).searchParams.get("fmt"), "json3");
  assert.equal(new URL(candidates[2]).searchParams.get("fmt"), "vtt");
  assert.equal(new Set(candidates).size, candidates.length);
}

function testVideoResponseMatching() {
  assert.equal(helpers.responseMatchesVideo({ videoDetails: { videoId: "abc123" } }, "abc123"), true);
  assert.equal(
    helpers.responseMatchesVideo(
      {
        captions: {
          playerCaptionsTracklistRenderer: {
            captionTracks: [{ baseUrl: "https://www.youtube.com/api/timedtext?v=abc123&lang=en" }]
          }
        }
      },
      "abc123"
    ),
    true
  );
  assert.equal(helpers.responseMatchesVideo({ videoDetails: { videoId: "old-video" } }, "abc123"), false);
}

function testCaptionPayloadParsing() {
  assert.deepEqual(helpers.parseCaptionPayload("").map((cue) => cue.text), []);

  const json3 = JSON.stringify({
    events: [
      { tStartMs: 1000, dDurationMs: 1500, segs: [{ utf8: "Hello" }, { utf8: " world" }] },
      { tStartMs: 2600, dDurationMs: 1200, segs: [{ utf8: "\n" }] }
    ]
  });
  const jsonCues = helpers.parseCaptionPayload(json3);
  assert.equal(jsonCues.length, 1);
  assert.equal(jsonCues[0].start, 1);
  assert.equal(jsonCues[0].end, 2.5);
  assert.equal(jsonCues[0].text, "Hello world");

  const protectedJsonCues = helpers.parseCaptionPayload(`)]}'\n${json3}`);
  assert.equal(protectedJsonCues.length, 1);
  assert.equal(protectedJsonCues[0].text, "Hello world");

  const legacyXml = '<transcript><text start="1.2" dur="2">Hello &amp; XML &#x1F44B; It&amp;#39;s OK</text></transcript>';
  const legacyCues = helpers.parseCaptionPayload(legacyXml);
  assert.equal(legacyCues.length, 1);
  assert.equal(legacyCues[0].text, "Hello & XML 👋 It's OK");

  const srv3 = '<timedtext><body><p t="3200" d="1800"><s>SRV</s><s> three</s></p></body></timedtext>';
  const srvCues = helpers.parseCaptionPayload(srv3);
  assert.equal(srvCues.length, 1);
  assert.equal(srvCues[0].start, 3.2);
  assert.equal(srvCues[0].text, "SRV three");

  const ttml = [
    '<tt><body><div><p begin="00:00:07.500" end="00:00:09.000">',
    '<span>TTML</span> caption',
    "</p></div></body></tt>"
  ].join("");
  const ttmlCues = helpers.parseCaptionPayload(ttml);
  assert.equal(ttmlCues.length, 1);
  assert.equal(ttmlCues[0].start, 7.5);
  assert.equal(ttmlCues[0].end, 9);
  assert.equal(ttmlCues[0].text, "TTML caption");

  const vtt = ["WEBVTT", "", "00:00:04.000 --> 00:00:06.000", "<v Roger>Hello VTT</v>"].join("\n");
  const vttCues = helpers.parseCaptionPayload(vtt);
  assert.equal(vttCues.length, 1);
  assert.equal(vttCues[0].start, 4);
  assert.equal(vttCues[0].text, "Hello VTT");

}

function testBalancedJsonExtraction() {
  const script = 'window.ytInitialPlayerResponse = {"videoDetails":{"videoId":"abc123"},"text":"brace } inside"}; other();';
  const start = script.indexOf("{");
  const extracted = helpers.extractBalancedJson(script, start);
  assert.equal(JSON.parse(extracted).videoDetails.videoId, "abc123");
}

function testPlaybackTranslationBatches() {
  const cues = Array.from({ length: 10 }, (_, index) => ({
    id: String(index),
    start: index * 2,
    end: index * 2 + 1.5,
    text: `cue ${index}`
  }));
  const batches = helpers.makePlaybackTranslationBatches(cues, 9, { firstBatchSize: 3, batchSize: 4 });

  assert.deepEqual(
    batches.map((batch) => batch.map((cue) => cue.id)),
    [["4", "5", "6"], ["7", "8", "9"], ["0", "1", "2", "3"]]
  );
}

function testSemanticVoiceSegments() {
  const fragments = [
    { id: "1", start: 0, end: 1.1, translatedText: "这是一个" },
    { id: "2", start: 1.16, end: 2.2, translatedText: "完整句子。" },
    { id: "3", start: 3.1, end: 4.2, translatedText: "下一句。" }
  ];
  const segments = helpers.buildSemanticVoiceSegments(fragments, { language: "zh-CN" });
  assert.equal(segments.length, 2);
  assert.equal(segments[0].text, "这是一个完整句子。");
  assert.equal(segments[0].start, 0);
  assert.equal(segments[0].end, 2.2);
  assert.equal(segments[0].endCueIndex, 1);
  assert.equal(segments[0].timeboxEnd, 2.85);
  assert.equal(segments[1].startCueIndex, 2);

  const longGap = helpers.buildSemanticVoiceSegments(
    [
      { id: "a", start: 0, end: 0.8, text: "first" },
      { id: "b", start: 1.3, end: 2.1, text: "second" }
    ],
    { language: "en-US" }
  );
  assert.equal(longGap.length, 2);

  const rollingCaptions = helpers.buildSemanticVoiceSegments(
    [
      { id: "r1", start: 0, end: 0.9, translatedText: "今天我们" },
      { id: "r2", start: 0.92, end: 1.8, translatedText: "我们一起学习。" }
    ],
    { language: "zh-CN", minDuration: 1.6 }
  );
  assert.equal(rollingCaptions.length, 1);
  assert.equal(rollingCaptions[0].text, "今天我们一起学习。");

  const shortSentences = helpers.buildSemanticVoiceSegments(
    [
      { id: "s1", start: 0, end: 0.8, translatedText: "第一句。" },
      { id: "s2", start: 0.82, end: 1.7, translatedText: "第二句。" }
    ],
    { language: "zh-CN", minDuration: 1.6 }
  );
  assert.equal(shortSentences.length, 1, "short adjacent sentences should share one TTS clip to avoid repeated startup pauses");

  const initialStableSegments = helpers.buildSemanticVoiceSegments(fragments.slice(0, 2), { language: "zh-CN" });
  const extendedStableSegments = helpers.extendSemanticVoiceSegments(initialStableSegments, fragments, { language: "zh-CN" });
  assert.equal(extendedStableSegments[0], initialStableSegments[0], "an existing playback segment must remain immutable");
  assert.equal(extendedStableSegments.length, 2);
  assert.equal(extendedStableSegments[0].key, initialStableSegments[0].key);

  assert.equal(helpers.captionEngineWaitTimeout({ status: "captions", cues: fragments }, 2000, 23000), 2000);
  assert.equal(helpers.captionEngineWaitTimeout({ status: "unknown", cues: [] }, 2000, 23000), 23000);
}

function testCueLockedVoicePresentation() {
  const cues = [
    { id: "1", start: 0, end: 1.1, translatedText: "这是一个" },
    { id: "2", start: 1.16, end: 2.2, translatedText: "完整句子。" },
    { id: "3", start: 3.1, end: 4.2, translatedText: "下一句。" }
  ];
  const segments = helpers.buildSemanticVoiceSegments(cues, { language: "zh-CN" });
  assert.equal(
    helpers.resolveVoiceCaptionText(cues[0], segments, true),
    "这是一个完整句子。",
    "the visible caption must show the exact text spoken by the active semantic voice clip"
  );
  assert.equal(helpers.resolveVoiceCaptionText(cues[1], segments, true), "这是一个完整句子。");
  assert.equal(
    helpers.resolveVoiceCaptionText(cues[0], segments, false),
    "这是一个",
    "subtitle-only playback must retain the original cue presentation"
  );
  assert.equal(helpers.computeVoiceSynthesisDuration(segments[0]), 2.2);
  assert.ok(
    helpers.computeVoiceSynthesisDuration(segments[0]) < segments[0].timeboxDuration,
    "speech fitting must use the visible subtitle window instead of borrowing the following silence"
  );
}

function testRollingCaptionNormalization() {
  const rolling = [
    { id: "0", start: 1.95, end: 2.75, text: "动画制作曾经是工作室的专属领域，" },
    { id: "1", start: 1.96, end: 3.03, text: "动画制作曾经是工作室的专属领域， [音乐]" },
    { id: "2", start: 3.03, end: 3.83, text: "[音乐]" },
    { id: "3", start: 3.04, end: 4.91, text: "[音乐] 需要巨额预算和多年的" },
    { id: "4", start: 4.91, end: 5.71, text: "需要巨额预算和多年的" },
    { id: "5", start: 4.92, end: 6.19, text: "需要巨额预算和多年的 培训。" },
    { id: "6", start: 6.19, end: 6.99, text: "培训。" },
    { id: "7", start: 6.2, end: 8.55, text: "培训。 现在，只需要几个小时和" }
  ];
  const normalized = helpers.normalizeRollingCaptionCues(rolling);
  assert.deepEqual(normalized.map((cue) => cue.text), [
    "动画制作曾经是工作室的专属领域，",
    "需要巨额预算和多年的",
    "培训。",
    "现在，只需要几个小时和"
  ]);
  assert.ok(normalized[2].start >= normalized[1].end, "new suffix timing should begin after the previous novel phrase");
  assert.equal(new Set(normalized.map((cue) => cue.text)).size, normalized.length);

  const naturalChinesePhrase = helpers.buildSemanticVoiceSegments(
    [
      { id: "n1", start: 0, end: 1, translatedText: "这是一段连续的" },
      { id: "n2", start: 1.02, end: 2.2, translatedText: "中文配音。" }
    ],
    { language: "zh-CN", minDuration: 1.6 }
  );
  assert.equal(naturalChinesePhrase[0].text, "这是一段连续的中文配音。", "contiguous CJK fragments must not gain an artificial comma");

  const cachedTranslated = helpers.normalizeRollingCaptionCues([
    { id: "c1", start: 0, end: 1, text: "Animation used to be", translatedText: "动画制作曾经" },
    { id: "c2", start: 0.8, end: 2, text: "Animation used to be exclusive", translatedText: "动画制作曾经是工作室的专属领域" },
    { id: "c3", start: 1.8, end: 3, text: "exclusive to studios", translatedText: "是工作室的专属领域" }
  ]);
  assert.deepEqual(cachedTranslated.map((cue) => cue.translatedText), [
    "动画制作曾经",
    "是工作室的专属领域"
  ]);
  assert.equal(cachedTranslated[0].text, "Animation used to be", "cache normalization must preserve source text");
}

async function testBackgroundModeNormalization() {
  const localData = {};
  const nativeMessages = [];
  const permissionChecks = [];
  let hostPermissionGranted = true;
  const context = {
    AbortController,
    URL,
    console,
    fetch,
    setTimeout,
    clearTimeout,
    importScripts() {},
    LocalTubeDubBackgroundHelpers: backgroundHelpers,
    LocalTubeDubPermissionHelpers: permissionHelpers,
    chrome: {
      runtime: {
        getManifest: () => JSON.parse(fs.readFileSync(path.join(root, "extension", "manifest.json"), "utf8")),
        onInstalled: { addListener() {} },
        onMessage: { addListener() {} },
        sendNativeMessage(_host, message, callback) {
          nativeMessages.push(message);
          callback({ ok: true, service: "localtube-dub", engineVersion: "0.1.82", protocolVersion: 2 });
        }
      },
      storage: {
        sync: { get: async () => ({}), set: async () => {} },
        local: {
          get: async (key) => {
            if (typeof key === "string") {
              return { [key]: localData[key] };
            }
            return { ...localData };
          },
          set: async (values) => Object.assign(localData, values),
          remove(key, callback) {
            delete localData[key];
            callback?.();
          }
        }
      },
      permissions: {
        contains(details, callback) {
          permissionChecks.push(details);
          callback(hostPermissionGranted);
        }
      },
      tabs: { create() {} }
    }
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(root, "extension", "background.js"), "utf8"), context);
  const local = vm.runInContext(
    'sanitizeSettings({ setupMode: "local", provider: "native", transcriptionProvider: "groq" })',
    context
  );
  assert.equal(local.setupMode, "byok");
  assert.equal(local.provider, "chrome-translator");
  assert.equal(local.transcriptionProvider, "native");
  const managed = vm.runInContext(
    'sanitizeSettings({ setupMode: "managed", provider: "managed", transcriptionProvider: "native" })',
    context
  );
  assert.equal(managed.setupMode, "byok");
  assert.equal(managed.provider, "chrome-translator");
  const advancedOllama = vm.runInContext(
    'sanitizeSettings({ setupMode: "byok", provider: "native", transcriptionProvider: "native" })',
    context
  );
  assert.equal(advancedOllama.setupMode, "byok");
  assert.equal(advancedOllama.provider, "native");
  assert.equal(vm.runInContext("sanitizeSettings({}).ttsEngine", context), "edge");
  assert.equal(vm.runInContext('sanitizeSettings({ ttsEngine: "system" }).ttsEngine', context), "system");
  const saved = await vm.runInContext(
    `saveCachedTranslationTimeline({
      videoId: "cache-video",
      targetLanguage: "zh-CN",
      provider: "chrome-translator",
      model: "default",
      sourceLanguage: "en",
      cues: [{ start: 0, end: 1, text: "hello", translatedText: "你好" }]
    })`,
    context
  );
  assert.equal(saved.payload.saved, true);
  const hit = await vm.runInContext(
    `getCachedTranslationTimeline({
      videoId: "cache-video",
      targetLanguage: "zh-CN",
      provider: "chrome-translator",
      model: "default"
    })`,
    context
  );
  assert.equal(hit.payload.hit, true);
  await vm.runInContext("clearTranslationTimelineCache()", context);
  assert.equal(Object.hasOwn(localData, "translationTimelineCacheV1"), false);

  let captionHttpCalls = 0;
  context.fetch = async (url) => {
    if (String(url).endsWith("/api/health")) {
      return new Response(
        JSON.stringify({
          ok: true,
          service: "localtube-dub",
          engineVersion: "0.1.82",
          protocolVersion: 2,
          ytDlp: true,
          whisper: true,
          tts: true
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    }
    if (String(url).endsWith("/api/captions")) {
      captionHttpCalls += 1;
      if (captionHttpCalls === 1) {
        throw new TypeError("Failed to fetch");
      }
      return new Response(
        JSON.stringify({
          ok: true,
          sourceLanguage: "en",
          cues: [{ id: "recovered", start: 0, end: 1.5, text: "Recovered captions" }]
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    }
    throw new Error(`Unexpected test URL: ${url}`);
  };
  const recoveredCaptions = await vm.runInContext(
    `resolveCaptionsWithEngine({
      videoId: "recovery-video",
      videoUrl: "https://www.youtube.com/watch?v=recovery-video",
      targetLanguage: "zh-CN"
    })`,
    context
  );
  assert.equal(recoveredCaptions.ok, true);
  assert.equal(recoveredCaptions.payload.cues[0].text, "Recovered captions");
  assert.equal(captionHttpCalls, 2);
  assert.deepEqual(nativeMessages.map((message) => message.type), ["start-http"]);

  captionHttpCalls = 0;
  context.fetch = async (url) => {
    if (String(url).endsWith("/api/captions")) {
      captionHttpCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 30));
      return new Response(
        JSON.stringify({
          ok: true,
          sourceLanguage: "en",
          cues: [{ id: "shared", start: 0, end: 1.5, text: "Shared captions" }]
        }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    }
    throw new Error(`Unexpected test URL: ${url}`);
  };
  const sharedCaptions = await Promise.all([
    vm.runInContext(
      `resolveCaptionsWithEngine({
        videoId: "shared-video",
        videoUrl: "https://www.youtube.com/watch?v=shared-video",
        targetLanguage: "zh-CN"
      })`,
      context
    ),
    vm.runInContext(
      `resolveCaptionsWithEngine({
        videoId: "shared-video",
        videoUrl: "https://www.youtube.com/watch?v=shared-video",
        targetLanguage: "zh-CN"
      })`,
      context
    )
  ]);
  assert.equal(captionHttpCalls, 1, "same-video caption requests should share one Engine call");
  assert.equal(sharedCaptions[0].payload.cues[0].text, "Shared captions");
  assert.equal(sharedCaptions[1].payload.cues[0].text, "Shared captions");

  context.fetch = async (url) => {
    if (String(url).endsWith("/api/captions")) {
      return new Response(
        JSON.stringify({
          ok: false,
          code: "YOUTUBE_RATE_LIMITED",
          error: "HTTP 429",
          retryAfterSeconds: 137
        }),
        { status: 429, headers: { "content-type": "application/json" } }
      );
    }
    throw new Error(`Unexpected test URL: ${url}`);
  };
  const limitedCaptions = await vm.runInContext(
    `resolveCaptionsWithEngine({
      videoId: "limited-video",
      videoUrl: "https://www.youtube.com/watch?v=limited-video",
      targetLanguage: "zh-CN"
    })`,
    context
  );
  assert.equal(limitedCaptions.ok, false);
  assert.equal(limitedCaptions.code, "YOUTUBE_RATE_LIMITED");
  assert.equal(limitedCaptions.retryAfterSeconds, 137);

  hostPermissionGranted = false;
  await assert.rejects(
    vm.runInContext('assertOptionalHostPermission("https://api.deepseek.com/chat/completions")', context),
    /重新选择当前服务并授权访问 api\.deepseek\.com/
  );
  assert.equal(permissionChecks.at(-1).origins[0], "https://api.deepseek.com/*");
  hostPermissionGranted = true;
  await vm.runInContext('assertOptionalHostPermission("https://api.deepseek.com/chat/completions")', context);
  const checksBeforeLocal = permissionChecks.length;
  await vm.runInContext('assertOptionalHostPermission("http://127.0.0.1:8787/api/dub")', context);
  assert.equal(permissionChecks.length, checksBeforeLocal);
  hostPermissionGranted = false;
  await assert.rejects(
    vm.runInContext('assertOptionalApiPermissions(["tabCapture", "offscreen"])', context),
    /开启“无字幕时自动转写”/
  );
  assert.equal(permissionChecks.at(-1).permissions.join(","), "tabCapture,offscreen");
  hostPermissionGranted = true;
}

function testCueTranslationTracker() {
  const translated = new Set();
  const tracker = helpers.createCueTranslationTracker((cue) => translated.has(helpers.cueKey(cue)));
  const cues = [
    { id: "a", start: 0, end: 1, text: "hello" },
    { id: "b", start: 1, end: 2, text: "world" }
  ];

  translated.add(helpers.cueKey(cues[1]));
  assert.deepEqual(tracker.reserve(cues), [cues[0]]);
  assert.equal(tracker.isPending(cues[0]), true);
  assert.deepEqual(tracker.reserve(cues), []);
  tracker.release([cues[0]]);
  assert.equal(tracker.isPending(cues[0]), false);
  assert.deepEqual(tracker.reserve([cues[0]]), [cues[0]]);
  tracker.clear();
  assert.equal(tracker.size(), 0);
}

function testRollingTranscriptionCueMerge() {
  const existing = [
    { id: "old-1", start: 26, end: 29, text: "keep this" },
    { id: "old-2", start: 29, end: 30.4, text: "boundary phrase" }
  ];
  const incoming = [
    { id: "new-0", start: 28.9, end: 30.5, text: "Boundary phrase!" },
    { id: "new-1", start: 30.2, end: 33, text: "next phrase" },
    { id: "new-2", start: 34, end: 36, text: "another phrase" }
  ];
  const selected = helpers.selectNewRollingCues(existing, incoming, 30, 1.2);
  assert.deepEqual(selected.map((cue) => cue.text), ["next phrase", "another phrase"]);
  assert.equal(selected[0].start, 30.2);
  const merged = helpers.mergeCueTimeline(existing, selected);
  assert.deepEqual(merged.map((cue) => cue.text), ["keep this", "boundary phrase", "next phrase", "another phrase"]);
}

function testSubtitleExportSerialization() {
  const cues = [
    { start: 62.3456, end: 64.1, text: "source", translatedText: "第二条\r\n两行" },
    { start: -1, end: 1.25, text: "第一条" },
    { start: "bad", end: "bad", text: "时间修复" },
    { start: 70, end: 71, text: "   " }
  ];
  assert.deepEqual(helpers.normalizeExportCues(cues), [
    { start: 0, end: 1.25, text: "第一条" },
    { start: 0, end: 2, text: "时间修复" },
    { start: 62.3456, end: 64.1, text: "第二条\n两行" }
  ]);
  assert.equal(
    helpers.serializeSubtitleCues(cues, "srt"),
    "1\n00:00:00,000 --> 00:00:01,250\n第一条\n\n2\n00:00:00,000 --> 00:00:02,000\n时间修复\n\n3\n00:01:02,346 --> 00:01:04,100\n第二条\n两行\n"
  );
  assert.equal(
    helpers.serializeSubtitleCues(cues, "vtt"),
    "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.250\n第一条\n\n2\n00:00:00.000 --> 00:00:02.000\n时间修复\n\n3\n00:01:02.346 --> 00:01:04.100\n第二条\n两行\n"
  );
  assert.equal(helpers.serializeSubtitleCues([], "srt"), "");
}

function testDubTrackRenderCues() {
  const segments = [
    { start: 0, end: 1, timeboxEnd: 1.4, text: "第一段" },
    { start: 1.5, end: 2.6, timeboxEnd: 2.6, text: "第二段" }
  ];
  assert.deepEqual(helpers.makeDubTrackRenderCues(segments, []), [
    { start: 0, end: 1.4, text: "第一段" },
    { start: 1.5, end: 2.6, text: "第二段" }
  ]);
  assert.deepEqual(
    helpers.makeDubTrackRenderCues([], [{ start: 2, end: 3, translatedText: "回退字幕" }]),
    [{ start: 2, end: 3, text: "回退字幕" }]
  );
}

function testAudioMixState() {
  assert.deepEqual(
    helpers.computeAudioMixState(
      { voiceEnabled: true, muteOriginal: true, originalVolume: 0.4 },
      { mutedByLocalTube: true, running: true, activeCueIndex: 3, spokenCueIndex: 2 }
    ),
    {
      shouldApply: true,
      shouldCancelSpeech: false,
      muted: true,
      volume: 0.4,
      shouldSpeakCurrentCue: true
    }
  );

  assert.deepEqual(
    helpers.computeAudioMixState(
      { voiceEnabled: false, muteOriginal: false, originalVolume: 3 },
      { mutedByLocalTube: true, running: true, activeCueIndex: 3, spokenCueIndex: 2 }
    ),
    {
      shouldApply: true,
      shouldCancelSpeech: true,
      muted: false,
      volume: 1,
      shouldSpeakCurrentCue: false
    }
  );

  assert.equal(
    helpers.computeAudioMixState(
      { voiceEnabled: true, muteOriginal: false, originalVolume: -1 },
      { mutedByLocalTube: false, running: true, activeCueIndex: 3, spokenCueIndex: 2 }
    ).shouldApply,
    false
  );
}

function testFullTrackSync() {
  assert.deepEqual(helpers.computeFullTrackSync(12, 12, 1), {
    drift: 0,
    seekTo: null,
    playbackRate: 1
  });
  assert.ok(helpers.computeFullTrackSync(12, 12.1, 1).playbackRate < 1);
  assert.ok(helpers.computeFullTrackSync(12, 11.9, 1).playbackRate > 1);
  assert.deepEqual(helpers.computeFullTrackSync(12, 12.5, 1), {
    drift: 0.5,
    seekTo: 12,
    playbackRate: 1
  });
  assert.equal(helpers.computeFullTrackSync(12, 12, 1.5).playbackRate, 1.5);
}

function testFullTrackMediaElements() {
  const makeMedia = (overrides = {}) => ({
    currentTime: 10,
    duration: 30,
    playbackRate: 1,
    paused: false,
    seeking: false,
    ended: false,
    readyState: 4,
    muted: false,
    volume: 1,
    pauseCalls: 0,
    pause() {
      this.paused = true;
      this.pauseCalls += 1;
    },
    ...overrides
  });

  const video = makeMedia({ currentTime: 10, playbackRate: 1.25 });
  const audio = makeMedia({ currentTime: 9.95, paused: true });
  const playing = helpers.syncFullTrackMediaElements(video, audio, {
    mixOriginal: true,
    originalVolume: 0.2
  });
  assert.equal(playing.action, "play");
  assert.equal(video.muted, true);
  assert.equal(video.volume, 0.2);
  assert.ok(audio.playbackRate > 1.25);

  video.paused = true;
  audio.paused = false;
  const paused = helpers.syncFullTrackMediaElements(video, audio, {});
  assert.equal(paused.action, "pause");
  assert.equal(audio.pauseCalls, 1);

  video.paused = false;
  video.seeking = true;
  audio.paused = false;
  const seeking = helpers.syncFullTrackMediaElements(video, audio, { forceSeek: true });
  assert.equal(seeking.action, "pause");
  assert.equal(audio.currentTime, video.currentTime);

  video.seeking = false;
  video.ended = true;
  audio.paused = false;
  assert.equal(helpers.syncFullTrackMediaElements(video, audio, {}).action, "stop");

  video.ended = false;
  audio.paused = false;
  assert.equal(helpers.syncFullTrackMediaElements(video, audio, { buffering: true }).action, "pause");

  audio.ended = true;
  assert.equal(helpers.syncFullTrackMediaElements(video, audio, {}).action, "stop");
}

function testLiveVoiceSync() {
  const segment = { start: 10, end: 13.4, timeboxEnd: 14 };
  const onTime = helpers.computeLiveVoiceSync(10, 1, 0, 3.9, segment, {});
  assert.equal(onTime.action, "none");
  assert.ok(onTime.playbackRate > 1);
  assert.ok(onTime.expectedEnd <= 13.4);
  assert.equal(onTime.targetEnd, 13.4);
  assert.equal(onTime.hardEnd, 14);

  const late = helpers.computeLiveVoiceSync(11, 1, 0, 3.9, segment, { audioPaused: true });
  assert.equal(late.action, "play");
  assert.ok(late.playbackRate > onTime.playbackRate);
  assert.ok(late.expectedEnd > 13.4, "a late clip may borrow the reserved silence instead of jumping to an uncomfortable rate");
  assert.ok(late.expectedEnd <= 14);

  const fastVideo = helpers.computeLiveVoiceSync(11, 1.5, 0.8, 3.9, segment, {});
  assert.ok(fastVideo.playbackRate >= 1.5);
  assert.ok(fastVideo.expectedEnd <= 13.4);

  const sought = helpers.computeLiveVoiceSync(12.5, 1, 0.1, 3.9, segment, { explicitSeek: true });
  assert.ok(sought.seekTo > 2);
  assert.ok(sought.expectedEnd <= 14);

  const normalDrift = helpers.computeLiveVoiceSync(12.5, 1, 0.1, 3.9, segment, { explicitSeek: false });
  assert.equal(normalDrift.seekTo, null, "normal TTS latency must not skip translated words");
  const stablePlan = helpers.computeLiveVoiceSync(11, 1, 1.15, 3.9, segment, {
    plannedRate: onTime.plannedRate,
    anchorVideoTime: 10,
    anchorAudioTime: 0
  });
  assert.ok(stablePlan.playbackRate <= onTime.plannedRate * 1.03 + 0.001);
  assert.ok(stablePlan.playbackRate >= onTime.plannedRate * 0.97 - 0.001);
  const borrowedSilence = helpers.computeLiveVoiceSync(10, 1, 0, 5.2, segment, { maxRateMultiplier: 1.45 });
  assert.ok(borrowedSilence.expectedEnd > 13.4, "an unusually long clip may borrow silence after the natural end");
  assert.ok(borrowedSilence.expectedEnd <= 14, "the borrowed clip must still finish before the hard boundary");
  assert.equal(borrowedSilence.lateRisk, false);
  const impossible = helpers.computeLiveVoiceSync(10, 1, 0, 6.5, segment, { maxRateMultiplier: 1.45 });
  assert.equal(impossible.lateRisk, true, "lateRisk is reserved for clips that cannot fit even the hard boundary");
  assert.equal(helpers.computeLiveVoiceSync(14.05, 1, 3.8, 3.9, segment, {}).action, "stop");
}

function testVoiceDeadlineRateBudget() {
  const segment = { start: 0, end: 3.2, timeboxEnd: 3.2, duration: 3.2 };
  const preparedFitRate = 1.16;
  const budget = helpers.computeVoiceRateBudget(segment, "edge", preparedFitRate);
  assert.equal(budget.comfortTotalRate, 1.16);
  assert.equal(budget.deadlineTotalRate, 1.34);
  assert.ok(budget.liveMaxRateMultiplier > 1.15 && budget.liveMaxRateMultiplier < 1.16);

  const previousSoftLimit = helpers.computeLiveVoiceSync(0, 1, 0, 3.5, segment, {
    finishGuard: 0.06,
    maxRateMultiplier: budget.comfortTotalRate / preparedFitRate
  });
  assert.equal(previousSoftLimit.lateRisk, true, "the former comfort-only ceiling reproduces the clipped previous segment");
  assert.ok(previousSoftLimit.expectedEnd > segment.end);

  const deadlineFit = helpers.computeLiveVoiceSync(0, 1, 0, 3.5, segment, {
    finishGuard: 0.06,
    maxRateMultiplier: budget.liveMaxRateMultiplier
  });
  assert.equal(deadlineFit.lateRisk, false);
  assert.ok(deadlineFit.playbackRate > 1.11 && deadlineFit.playbackRate < 1.12);
  assert.ok(deadlineFit.expectedEnd <= segment.end);
  assert.ok(preparedFitRate * deadlineFit.playbackRate <= budget.deadlineTotalRate + 0.001);

  const measuredNaturalClip = helpers.computeLiveVoiceSync(0.05, 1, 0, 3.499, segment, {
    finishGuard: 0.14,
    startEarly: 0.12,
    maxRateMultiplier: budget.liveMaxRateMultiplier
  });
  assert.ok(
    measuredNaturalClip.expectedEnd <= segment.end - 0.1,
    "a measured natural clip with a small startup delay should still finish perceptibly before the source boundary"
  );
  assert.ok(preparedFitRate * measuredNaturalClip.playbackRate <= 1.34 + 0.001);
}

function testNaturalVoiceStartupReanchor() {
  const timing = helpers.computeVoiceSyncTiming("edge");
  assert.equal(timing.startEarly, 0.12);
  assert.equal(timing.finishGuard, 0.14);

  const segment = { start: 10, end: 13.2, timeboxEnd: 13.2, duration: 3.2 };
  const primed = helpers.computeLiveVoiceSync(9.88, 1, 0, 3.2, segment, {
    finishGuard: timing.finishGuard,
    startEarly: timing.startEarly,
    maxRateMultiplier: 1.14,
    audioPaused: true
  });
  const staleStartupPlan = helpers.computeLiveVoiceSync(10.09, 1, 0, 3.2, segment, {
    finishGuard: timing.finishGuard,
    startEarly: timing.startEarly,
    maxRateMultiplier: 1.14,
    plannedRate: primed.plannedRate,
    anchorVideoTime: 9.88,
    anchorAudioTime: 0,
    audioPaused: false
  });
  const reanchoredAtPlaybackStart = helpers.computeLiveVoiceSync(10.09, 1, 0, 3.2, segment, {
    finishGuard: timing.finishGuard,
    startEarly: timing.startEarly,
    maxRateMultiplier: 1.14,
    audioPaused: false
  });

  assert.ok(
    reanchoredAtPlaybackStart.playbackRate > staleStartupPlan.playbackRate + 0.03,
    "reanchoring after audio.play must recover startup latency instead of carrying the pre-play plan"
  );
  assert.ok(reanchoredAtPlaybackStart.playbackRate < 1.09, "the perceptual correction must remain subtle");
  assert.ok(reanchoredAtPlaybackStart.expectedEnd <= segment.end - timing.finishGuard + 0.002);
}

function testLiveVoiceMediaElements() {
  const video = { currentTime: 11, playbackRate: 1, paused: false, seeking: false };
  const audio = {
    currentTime: 0,
    duration: 3.9,
    playbackRate: 1,
    paused: true,
    pauseCalls: 0,
    pause() {
      this.paused = true;
      this.pauseCalls += 1;
    }
  };
  const segment = { start: 10, end: 13.4, timeboxEnd: 14 };
  const playing = helpers.syncLiveVoiceMediaElements(video, audio, segment, {});
  assert.equal(playing.action, "play");
  assert.ok(audio.playbackRate > 1);

  video.paused = true;
  audio.paused = false;
  assert.equal(helpers.syncLiveVoiceMediaElements(video, audio, segment, {}).action, "pause");
  assert.equal(audio.pauseCalls, 1);

  video.paused = false;
  video.currentTime = 12.5;
  audio.currentTime = 0.1;
  const sought = helpers.syncLiveVoiceMediaElements(video, audio, segment, { explicitSeek: true });
  assert.ok(audio.currentTime > 2);
  assert.equal(sought.seekTo, audio.currentTime);

  video.seeking = true;
  audio.paused = false;
  const seeking = helpers.syncLiveVoiceMediaElements(video, audio, segment, {});
  assert.equal(seeking.action, "pause");
  assert.equal(audio.paused, true);
}

function testInstallReleaseInfo() {
  assert.deepEqual(installHelpers.normalizeReleaseInfo(null, "0.1.82"), {
    channel: "development",
    version: "0.1.82",
    extensionId: "",
    engineBundleName: "LocalTube-Dub-Engine-v0.1.82-macOS.zip",
    engineDownloadUrl: "",
    supportUrl: "",
    signed: false,
    notarized: false
  });
  const customer = installHelpers.normalizeReleaseInfo(
    {
      channel: "private-beta",
      version: "0.1.82",
      extensionId: "abcdefghijklmnopabcdefghijklmnop",
      engineBundleName: "engine.zip",
      engineDownloadUrl: "http://unsafe.example/engine.zip",
      supportUrl: "https://support.example/help",
      signed: false,
      notarized: false
    },
    "0.1.82"
  );
  assert.equal(customer.channel, "private-beta");
  assert.equal(customer.engineDownloadUrl, "");
  assert.equal(customer.supportUrl, "https://support.example/help");
}

function testTranscriptionRequestRegistry() {
  const registry = backgroundHelpers.createTranscriptionRequestRegistry();
  const first = registry.begin("one");
  const second = registry.begin("two");

  assert.equal(registry.size(), 2);
  assert.equal(first.signal.aborted, false);
  assert.equal(registry.cancel("one"), true);
  assert.equal(first.signal.aborted, true);
  assert.equal(registry.size(), 1);
  assert.equal(registry.cancel("missing"), true);
  const cancelledBeforeBegin = registry.begin("missing");
  assert.equal(cancelledBeforeBegin.signal.aborted, true);
  assert.equal(registry.complete("missing", cancelledBeforeBegin.controller), true);
  assert.equal(registry.complete("two", first.controller), false);
  assert.equal(registry.size(), 1);
  const duplicateA = registry.begin("duplicate");
  const duplicateB = registry.begin("duplicate");
  assert.equal(duplicateA.signal.aborted, true);
  assert.equal(duplicateB.signal.aborted, false);
  assert.equal(registry.cancel(), true);
  assert.equal(second.signal.aborted, true);
  assert.equal(duplicateB.signal.aborted, true);
  assert.equal(registry.size(), 0);
}

function testNoCaptionStartupOrder() {
  const content = fs.readFileSync(path.join(root, "extension", "content.js"), "utf8");
  const body = extractFunctionBody(content, "transcribeCurrentAudioWindow");
  const directEngineIndex = body.indexOf("const directWindow = await transcribeVideoWindowFromEngine");
  const localRecordIndex = body.indexOf("const localRecording = await recordVideoElementAudio");
  const capturedTranscribeIndex = body.indexOf("const cues = await transcribeCapturedRecording");
  const fallbackIndex = body.indexOf("const cues = await transcribeWithTabAudioFallback");
  const requestIdIndex = body.indexOf("requestId");

  assert.ok(directEngineIndex >= 0, "local no-caption flow must first try a direct Engine audio window");
  assert.ok(localRecordIndex > directEngineIndex, "player recording should be the fallback after direct Engine extraction");
  assert.ok(localRecordIndex >= 0, "no-caption flow must first try direct video element recording");
  assert.ok(capturedTranscribeIndex > localRecordIndex, "direct recording should be transcribed before tab-capture fallback");
  assert.ok(fallbackIndex > capturedTranscribeIndex, "tab-capture fallback should only run after direct recording is unavailable");
  assert.ok(requestIdIndex >= 0, "transcription request must carry a request id");

  const capturedBody = extractFunctionBody(content, "transcribeCapturedRecording");
  assert.match(capturedBody, /localtube\.transcribeCapturedAudio/);
  assert.match(capturedBody, /dataUrl: recording\.dataUrl/);
  assert.match(capturedBody, /mimeType: recording\.mimeType/);
  assert.match(capturedBody, /await cancelTabAudioRecording\(requestId\)/);

  const fallbackBody = extractFunctionBody(content, "transcribeWithTabAudioFallback");
  const prepareIndex = fallbackBody.indexOf("const preparedCapture = await prepareTabAudioCapture(durationSeconds)");
  const playIndex = fallbackBody.indexOf("await state.video.play()");
  const transcribeMessageIndex = fallbackBody.indexOf('type: "localtube.transcribeTabAudio"');
  const streamIdIndex = fallbackBody.indexOf("streamId: preparedCapture.streamId");
  const cancelOnTimeoutIndex = fallbackBody.indexOf("await cancelTabAudioRecording(requestId)");

  assert.ok(prepareIndex >= 0, "tab-capture fallback must prepare tab audio first");
  assert.ok(playIndex > prepareIndex, "fallback playback must start only after tab-audio preparation succeeds");
  assert.ok(transcribeMessageIndex > playIndex, "fallback transcription request should be sent after recording begins");
  assert.ok(streamIdIndex > transcribeMessageIndex, "fallback transcription request must reuse the prepared stream id");
  assert.ok(cancelOnTimeoutIndex > transcribeMessageIndex, "timeout path must cancel the matching transcription request");
}

function extractFunctionBody(source, functionName) {
  const marker = `function ${functionName}`;
  const functionIndex = source.indexOf(marker);
  assert.ok(functionIndex >= 0, `missing function ${functionName}`);
  const signatureEnd = source.indexOf(")", functionIndex);
  assert.ok(signatureEnd >= 0, `missing signature end for ${functionName}`);
  const start = source.indexOf("{", signatureEnd);
  assert.ok(start >= 0, `missing body for ${functionName}`);

  let depth = 0;
  let inString = false;
  let stringQuote = "";
  let escaped = false;
  let inTemplateExpressionDepth = 0;

  for (let index = start; index < source.length; index += 1) {
    const char = source[index];
    const previous = source[index - 1];

    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (char === "\\") {
        escaped = true;
      } else if (char === stringQuote && !inTemplateExpressionDepth) {
        inString = false;
        stringQuote = "";
      } else if (stringQuote === "`" && previous === "$" && char === "{") {
        inTemplateExpressionDepth += 1;
        depth += 1;
      } else if (stringQuote === "`" && inTemplateExpressionDepth && char === "}") {
        inTemplateExpressionDepth -= 1;
        depth -= 1;
      }
      continue;
    }

    if (char === "\"" || char === "'" || char === "`") {
      inString = true;
      stringQuote = char;
    } else if (char === "{") {
      depth += 1;
    } else if (char === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(start + 1, index);
      }
    }
  }

  throw new Error(`unterminated function ${functionName}`);
}

function testManifestAndFlowGuards() {
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "extension", "manifest.json"), "utf8"));
  assert.deepEqual(manifest.content_scripts[0].js, ["page_probe_helpers.js", "page_probe.js"]);
  assert.equal(manifest.content_scripts[0].world, "MAIN");
  assert.deepEqual(manifest.content_scripts[1].js, ["voice_helpers.js", "content_helpers.js", "content.js"]);
  assert.equal(manifest.version, "0.1.97");
  assert.equal(manifest.permissions.includes("downloads"), false);
  assert.deepEqual(manifest.permissions, ["activeTab", "nativeMessaging", "storage"]);
  assert.deepEqual(manifest.optional_permissions, ["offscreen", "tabCapture"]);
  assert.equal(manifest.minimum_chrome_version, "116");
  assert.deepEqual(manifest.host_permissions, [
    "https://www.youtube.com/*",
    "https://youtube.com/*",
    "http://127.0.0.1/*",
    "http://localhost/*"
  ]);
  assert.deepEqual(manifest.optional_host_permissions, ["https://*/*"]);

  const content = fs.readFileSync(path.join(root, "extension", "content.js"), "utf8");
  assert.match(content, /const EXTENSION_VERSION = chrome\.runtime\.getManifest\(\)\.version/);
  assert.match(content, /LocalTube Dub <span>\$\{EXTENSION_VERSION\}<\/span>/);
  assert.match(content, /handleWidgetVolumeInput/);
  assert.match(content, /widgetVolumeSaveTimer/);
  const volumeInputBody = extractFunctionBody(content, "handleWidgetVolumeInput");
  assert.match(volumeInputBody, /state\.settings = nextSettings/);
  assert.match(volumeInputBody, /updateOriginalVolumeLabel\(\)/);
  assert.match(volumeInputBody, /activateAudioControl\(\)/);
  assert.match(volumeInputBody, /applyAudioMixSettings\(\)/);
  assert.match(content, /function activateAudioControl/);
  assert.match(content, /state\.originalMuted = state\.video\.muted/);
  assert.match(content, /message\?\.type === "localtube\.settingsChanged"[\s\S]*applyAudioMixSettings\(\)/);
  assert.match(content, /if \(!state\.settings\.enabled\) \{\s*stopDubbing\(\{ silent: true \}\);\s*unmountWidget\(\);/);
  assert.match(content, /function unmountWidget/);
  assert.match(content, /isWatchPage\(\) && state\.settings\.enabled/);
  assert.match(content, /localtube\.captionEngineHealth/);
  assert.match(content, /payload\.upgradeRequired/);
  assert.match(content, /localtube\.listVoices/);
  assert.match(content, /renderAvailableVoiceOptions/);
  assert.match(content, /transcriptionProvider === "native" && !payload\.whisper/);
  assert.match(content, /yt-dlp \+ Whisper 就绪/);
  assert.match(content, /localtube\.startEngine/);
  assert.match(content, /localtube\.restartEngine/);
  assert.match(content, /startEngineFromWidget/);
  assert.match(content, /restartEngineFromWidget/);
  assert.match(content, /data-action="engine-start"/);
  assert.match(content, /data-action="engine-restart"/);
  assert.match(content, /data-engine-status/);
  assert.match(content, /state\.settings = await loadSettings\(\)/);
  assert.match(content, /localtube\.getCachedTimeline/);
  assert.match(content, /localtube\.saveCachedTimeline/);
  assert.match(content, /saveTimelineCacheIfComplete/);
  assert.match(content, /makeTimelineCacheLookupRequests/);
  assert.match(content, /targetCaptionsReady \? "youtube-captions" : state\.settings\.provider/);
  assert.match(content, /engineResult\.cues\?\.length &&\s*isTargetLanguageTrack\(engineResult\.track, state\.settings\.targetLanguage\)/);
  assert.match(content, /payload\.translatedByYouTube\s*\? state\.settings\.targetLanguage/);
  assert.match(content, /fallbackToChromeTranslator/);
  assert.match(content, /state\.timelineCacheProvider = "chrome-translator"/);
  assert.match(content, /provider\.startsWith\("youtube-"\) \? ""/);
  assert.match(content, /!state\.settings\.cacheTranslations \|\| state\.partialTranscription/);
  assert.match(content, /isExtensionContextInvalidated/);
  assert.match(content, /请刷新当前 YouTube 页面后再开始翻译/);
  assert.match(content, /requestPageSnapshot\(videoId\)/);
  assert.match(content, /window\.postMessage/);
  assert.match(content, /page-main-world/);
  assert.match(content, /error\?\.name === "OperationStaleError" \|\| state\.operationId !== operationId/);
  assert.match(content, /providerOptions/);
  assert.match(content, /updateProviderOptionsFromResponse/);
  assert.match(content, /allowAudioTranscription/);
  assert.match(content, /为避免消耗转写额度/);
  assert.match(content, /resolveVideoCaptions\(operationId\)/);
  assert.match(content, /正在读取 YouTube 字幕/);
  assert.match(content, /resolveVideoCaptionsFromPage\(videoId\)/);
  assert.match(content, /withTimeoutResult/);
  assert.match(content, /正在通过本地 Engine 读取字幕/);
  assert.match(content, /CAPTION_TOTAL_TIMEOUT_MS/);
  assert.match(content, /setOriginalMutedForDubbing/);
  assert.match(content, /computeAudioMixState/);
  assert.match(content, /mix\.shouldSpeakCurrentCue/);
  assert.match(content, /getPrimaryVideoElement/);
  assert.match(content, /document\.getElementById\("localtube-dub-root"\)/);
  assert.match(content, /root\.dataset\.localtubeOwner = chrome\.runtime\.id/);
  assert.match(content, /refreshActiveVideoReference/);
  assert.match(content, /enforceOriginalAudioMix/);
  assert.match(content, /#movie_player video\.html5-main-video/);
  assert.match(content, /Promise\.all\(workers\)/);
  assert.match(content, /preferredCaptionLanguage/);
  assert.match(content, /fetchInnertubePlayerResponse/);
  assert.match(content, /page-innertube-player/);
  assert.match(content, /makeInnertubePlayerRequest/);
  assert.match(content, /createTranslatedCaptionTracks/);
  assert.match(content, /targetCaptionsReady/);
  assert.match(content, /translatedCues = originalCues\.map\(useCueTextAsTranslation\)/);
  assert.match(content, /translationBatches = \[\]/);
  assert.match(content, /normalizeCaptionLanguageLocal/);
  assert.match(content, /beginChromeTranslationWarmupFromUserGesture/);
  assert.match(content, /prepareChromeTranslator/);
  assert.match(content, /translateCuesWithChromeTranslator/);
  assert.match(content, /prepareChromeLanguageDetector/);
  assert.match(content, /normalizeChromeTranslatorLanguage/);
  assert.match(content, /globalThis\.Translator\.create/);
  assert.match(content, /downloadprogress/);
  assert.match(content, /skipTranslation/);
  assert.match(content, /localtube\.synthesizeSpeech/);
  assert.match(content, /data-field="ttsEngine"/);
  assert.match(content, /Microsoft 自然在线/);
  assert.match(content, /ttsEngine: state\.settings\.ttsEngine \|\| DEFAULT_SETTINGS\.ttsEngine/);
  assert.match(content, /ttsEngine: "edge"/);
  assert.match(content, /loadCachedTimeline\(videoId, operationId, "youtube-captions"\)/);
  assert.match(content, /providerCachedTimeline = await loadCachedTimeline\(videoId, operationId, state\.settings\.provider\)/);
  assert.match(content, /audio\.preservesPitch = true/);
  assert.match(content, /naturalOnline \? 6\.2/);
  assert.match(content, /state\.settings\.ttsEngine === "edge"/);
  assert.match(content, /VOICE_LEAD_SECONDS/);
  assert.match(content, /prewarmVoiceAroundTime/);
  assert.match(content, /buildVoiceSegments/);
  assert.match(content, /buildSemanticVoiceSegments/);
  assert.match(content, /extendSemanticVoiceSegments/);
  assert.match(content, /normalizeRollingCaptionCues\(captionResult\.cues \|\| \[\]\)/);
  assert.match(content, /translatedCues = normalizeRollingCaptionCues\(cachedTimeline\.cues\)/);
  assert.match(content, /alignVoiceAudioToSegment/);
  assert.match(content, /syncActiveVoiceAudio/);
  assert.match(content, /VOICE_PREFETCH_WINDOW_SECONDS/);
  assert.doesNotMatch(content, /VOICE_LIVE_TTS_WAIT_MS/);
  assert.match(content, /const VOICE_PREFETCH_WINDOW_SECONDS = 18/);
  assert.match(content, /const VOICE_PREFETCH_MAX_SEGMENTS = 6/);
  assert.match(content, /const VOICE_AUDIO_MAX_CONCURRENCY = 3/);
  assert.match(content, /beginVoiceEngineWarmup\(operationId\)/);
  assert.match(content, /function voiceWarmupText/);
  assert.match(content, /function pruneQueuedVoiceAudioTasks/);
  assert.match(content, /scheduleVoicePrefetchWindow\(state\.video\.currentTime \|\| 0\)/);
  assert.match(content, /VOICE_TIMEBOX_END_GRACE_SECONDS/);
  assert.match(content, /VOICE_TIMEBOX_SEEK_GRACE_SECONDS/);
  assert.match(content, /VOICE_TIMEBOX_SILENCE_SLACK_SECONDS/);
  assert.match(content, /activeBrowserVoiceSegment/);
  assert.match(content, /browserVoiceStartTimer/);
  assert.match(content, /voicePlaybackGeneration/);
  assert.match(content, /function cancelPendingBrowserSpeechStart/);
  assert.match(content, /clearTimeout\(state\.browserVoiceStartTimer\)/);
  assert.match(content, /isVoicePlaybackAttemptCurrent\(segment, playbackGeneration\)/);
  assert.match(content, /syncActiveBrowserSpeech/);
  assert.match(content, /buffering: state\.videoBuffering/);
  assert.match(content, /state\.video\.paused \|\| state\.videoBuffering/);
  assert.match(content, /computeBrowserVoiceRate/);
  assert.match(content, /const naturalEnd = Math\.max/);
  assert.doesNotMatch(content, /initialLateSeek/);
  assert.match(content, /voiceSeekAlignmentUntil/);
  assert.match(content, /const explicitVideoSeek = Date\.now\(\) <= state\.voiceSeekAlignmentUntil/);
  assert.match(content, /state\.voiceSeekAlignmentUntil = Date\.now\(\) \+ 1200/);
  const seekingBody = extractFunctionBody(content, "handleVideoSeeking");
  assert.match(seekingBody, /state\.voiceSeekAlignmentUntil = Date\.now\(\) \+ 1200/);
  assert.doesNotMatch(seekingBody, /state\.voiceSeekAlignmentUntil = 0/);
  const stopDubbingBody = extractFunctionBody(content, "stopDubbing");
  assert.match(stopDubbingBody, /state\.voiceSeekAlignmentUntil = 0/);
  assert.match(content, /CAPTION_ENGINE_PAGE_FALLBACK_TIMEOUT_MS/);
  assert.match(content, /response\.code === "OLLAMA_UNAVAILABLE"/);
  assert.match(content, /voiceSegmentPlaybackEnd/);
  assert.match(content, /voiceSegmentPlaybackDuration/);
  assert.match(content, /resolveVoiceCaptionText\(cue, state\.voiceSegments, state\.settings\.voiceEnabled\)/);
  assert.match(content, /targetDuration: computeVoiceSynthesisDuration\(segment\)/);
  assert.match(content, /maxFitRate: voiceTotalMaxRate\(segment\)/);
  assert.match(content, /localtubePreparedFitRate/);
  assert.match(content, /computeVoiceRateBudget\(segment, state\.settings\.ttsEngine, preparedFitRate\)\.liveMaxRateMultiplier/);
  assert.match(content, /await audio\.play\(\);\s*resetVoiceAudioSyncPlan\(audio\);\s*syncActiveVoiceAudio/);
  const requestRateBody = extractFunctionBody(content, "computeVoiceRequestRate");
  assert.match(requestRateBody, /state\.settings\.voiceRate/);
  assert.doesNotMatch(requestRateBody, /estimatedSeconds|targetSeconds/);
  assert.match(content, /spokenVoiceSegmentKeys: new Set\(\)/);
  assert.match(content, /spokenVoiceTextWindows: new Map\(\)/);
  assert.match(content, /state\.spokenVoiceSegmentKeys\.has\(segment\.key\)/);
  assert.match(content, /wasVoiceTextRecentlySpoken\(segment\)/);
  assert.match(content, /state\.spokenVoiceSegmentKeys\.add\(segment\.key\)/);
  assert.match(content, /rememberSpokenVoiceText\(segment\)/);
  const refreshVoiceSegmentsBody = extractFunctionBody(content, "refreshVoiceSegments");
  assert.match(refreshVoiceSegmentsBody, /extendSemanticVoiceSegments/);
  assert.match(refreshVoiceSegmentsBody, /remapVoiceSegmentCueIndices/);
  assert.doesNotMatch(refreshVoiceSegmentsBody, /invalidateVoicePlayback/);
  assert.match(content, /function exportCurrentSubtitles/);
  assert.match(content, /serializeSubtitleCues\(cues, format\)/);
  assert.match(content, /LocalTube-Dub_\$\{videoId\}_\$\{language\}_\$\{scope\}/);
  assert.match(content, /format === "srt" \? "\\ufeff" : ""/);
  assert.match(content, /translationPipelineChanged[\s\S]*stopDubbing\(\{ silent: true \}\)/);
  assert.match(content, /function prepareFullTranscript/);
  assert.match(content, /function pollFullTranscriptJob/);
  assert.match(content, /function applyCompleteTranscript/);
  assert.match(content, /localtube\.startFullTranscript/);
  assert.match(content, /localtube\.fullTranscriptStatus/);
  assert.match(content, /localtube\.cancelFullTranscript/);
  assert.match(content, /state\.partialTranscription = false/);
  assert.match(content, /FULL_TRANSCRIPT_MAX_SECONDS = 7200/);
  assert.match(content, /function startDubTrackRendering/);
  assert.match(content, /function pollDubTrackJob/);
  assert.match(content, /function downloadReadyDubTrack/);
  assert.match(content, /function isSafeDubTrackDownloadUrl/);
  assert.match(content, /localtube\.startDubTrack/);
  assert.match(content, /localtube\.dubTrackStatus/);
  assert.match(content, /localtube\.cancelDubTrack/);
  assert.match(content, /下载配音音轨/);
  assert.match(content, /data-field="dubTrackMode"/);
  assert.match(content, /data-field="dubTrackFormat"/);
  assert.match(content, /data-action="preview-dub-track"/);
  assert.match(content, /M4A 小文件/);
  assert.match(content, /WAV 无损/);
  assert.match(content, /mixOriginal: mixedTrack/);
  assert.match(content, /outputFormat/);
  assert.match(content, /makeDubTrackRenderCues\(state\.voiceSegments, state\.translatedCues\)/);
  assert.match(content, /个语义配音段/);
  assert.match(content, /synthesisWorkers/);
  assert.match(content, /function startDubTrackPreview/);
  assert.match(content, /function stopDubTrackPreview/);
  assert.match(content, /function syncDubTrackPreview/);
  assert.match(content, /function requestDubTrackPreviewPlayback/);
  assert.match(content, /function isExpectedDubTrackPlaybackAbort/);
  assert.match(content, /error\?\.name === "AbortError"/);
  assert.match(content, /dubTrackPreviewPlayPromise/);
  assert.match(content, /dubTrackPreviewOperationId/);
  assert.match(content, /videoBuffering/);
  assert.match(content, /addEventListener\("waiting", handleVideoWaiting\)/);
  assert.match(content, /addEventListener\("seeked", handleVideoSeeked\)/);
  assert.match(content, /addEventListener\("ended", handleVideoEnded\)/);
  assert.match(content, /addEventListener\("ratechange", handleVideoRateChange\)/);
  assert.match(content, /computeFullTrackSync/);
  assert.match(content, /preview", "1"/);
  assert.match(content, /state\.dubTrackPreviewActive && state\.dubTrackMixOriginal/);
  assert.match(content, /originalVolume: clampNumber\(state\.settings\.originalVolume/);
  assert.match(content, /stage === "downloading-original"/);
  assert.match(content, /stage === "mixing"/);
  assert.match(content, /stage === "encoding"/);
  const renderCaptionBody = extractFunctionBody(content, "renderCaption");
  assert.doesNotMatch(renderCaptionBody, /cueIndex < 0[\s\S]*stopActiveVoiceAudio\(\)/);
  assert.match(renderCaptionBody, /!state\.activeVoiceAudio && !state\.activeBrowserVoiceSegment/);
  assert.match(content, /const firstAudio = getVoiceSegmentAudio\(firstSegment, \{ priority: true \}\)/);
  assert.doesNotMatch(content, /Promise\.race\(\[audioRequest/);
  assert.match(content, /const audioPayload = await getVoiceSegmentAudio\(segment, \{ priority: true \}\)/);
  assert.match(content, /VOICE_LATE_START_SKIP_SECONDS/);
  assert.match(content, /VOICE_MIN_REMAINING_SECONDS/);
  assert.match(content, /shouldSkipLateVoiceSegment/);
  assert.match(content, /hasVoiceSegmentAudioReady/);
  assert.match(content, /markVoiceSegmentSkipped/);
  assert.match(content, /voiceTimeboxMaxRate/);
  assert.match(content, /voiceId/);
  assert.match(content, /voiceAudioCache/);
  assert.match(content, /function cancelQueuedVoiceAudio/);
  assert.match(content, /task\.cancel = \(\) =>/);
  assert.match(content, /reject\(new Error\("配音请求已取消"\)\)/);
  assert.match(content, /cancelQueuedVoiceAudio\(\)/);
  const stopDubbingQueueBody = extractFunctionBody(content, "stopDubbing");
  assert.doesNotMatch(stopDubbingQueueBody, /state\.voiceAudioActiveCount = 0/);
  assert.match(content, /playVoiceSegment/);
  assert.match(content, /speakSegmentWithBrowserTts/);
  assert.match(content, /new Audio\(audioPayload\.dataUrl\)/);
  assert.match(content, /originalVolume/);
  assert.match(content, /fetchEngineCaptions\(videoId\)/);
  assert.match(content, /localtube\.resolveCaptions/);
  assert.match(content, /normalizeResolvedCues/);
  assert.match(content, /engineResult\?\.status === "captions"/);
  assert.match(content, /CAPTION_FAILURE_BACKOFF_MS/);
  assert.match(content, /captionFailureBackoff/);
  assert.match(content, /rememberCaptionFailure/);
  assert.match(content, /getCaptionFailureBackoff/);
  assert.match(content, /classifyCaptionErrorCode/);
  assert.match(content, /YOUTUBE_RATE_LIMITED/);
  assert.match(content, /captionRetryTimer/);
  assert.match(content, /scheduleCaptionAutoRetry/);
  assert.match(content, /retryAfterSeconds/);
  assert.doesNotMatch(content, /YouTube 字幕服务正在限流[^\n]*无字幕时自动转写/);
  assert.doesNotMatch(content, /字幕 Engine 暂时没有返回可用字幕，页面字幕也没有读到。请点“重启”后重试/);
  assert.doesNotMatch(content, /if \(pageResult\.status === "no_captions"\) \{\s*return pageResult;\s*\}/);
  assert.match(content, /captionResult\.status === "no_captions"/);
  assert.match(content, /已确认这个视频没有可读取的 YouTube 字幕。需要翻译无字幕视频时/);
  assert.match(content, /本地字幕 Engine 读取超时/);
  assert.match(content, /isEngineNoCaptionError/);
  assert.match(content, /engineCaptionErrorMessage/);
  assert.match(content, /collectCaptionTracks/);
  assert.match(content, /limitCaptionTrackAttempts\(\s*rankCaptionTracks/);
  assert.match(content, /makeCaptionFetchCandidates\(track\.baseUrl\)/);
  assert.match(content, /检测到 \$\{sourceResult\.tracks\.length\} 个字幕轨道/);
  assert.match(content, /status: sourceResult\.hadUsableSource \? "no_captions" : "unknown"/);
  assert.match(content, /confirmedNoCaptions: sourceResult\.hadUsableSource/);
  assert.match(content, /pageResult\.status === "no_captions" && pageResult\.confirmedNoCaptions/);
  const resolveCaptionsBody = extractFunctionBody(content, "resolveVideoCaptions");
  assert.match(
    resolveCaptionsBody,
    /pageFastResult\?\.status === "captions"[\s\S]*pageFastResult\?\.cues\?\.length[\s\S]*return pageFastResult/,
    "any readable page caption track must bypass yt-dlp, not only a target-language track"
  );
  assert.ok(
    resolveCaptionsBody.indexOf("await withTimeoutResult(pageResultPromise") <
      resolveCaptionsBody.indexOf("fetchEngineCaptions(videoId)"),
    "the page caption path must finish its fast attempt before starting the Engine"
  );
  assert.ok(
    resolveCaptionsBody.indexOf('engineResult?.code === "YOUTUBE_RATE_LIMITED"') <
      resolveCaptionsBody.indexOf('pageResult.status === "no_captions" && pageResult.confirmedNoCaptions'),
    "rate limiting must remain unknown and must not fall through to no-caption transcription"
  );
  const startDubbingBody = extractFunctionBody(content, "startDubbing");
  const targetCacheIndex = startDubbingBody.indexOf('loadCachedTimeline(videoId, operationId, "youtube-captions")');
  const providerCacheIndex = startDubbingBody.indexOf("loadCachedTimeline(videoId, operationId, state.settings.provider)");
  const sourceCacheIndex = startDubbingBody.indexOf('loadCachedTimeline(videoId, operationId, "youtube-source")');
  const liveCaptionIndex = startDubbingBody.indexOf("resolveVideoCaptions(operationId)");
  assert.ok(targetCacheIndex >= 0 && providerCacheIndex > targetCacheIndex);
  assert.ok(sourceCacheIndex > providerCacheIndex);
  assert.ok(liveCaptionIndex > sourceCacheIndex, "all local subtitle caches must be exhausted before a YouTube request");
  assert.match(startDubbingBody, /resumeVideoAfterCaptionDelay/);
  assert.match(content, /page-player-response 未找到当前视频响应/);
  assert.match(content, /dedupeCaptionTracks/);
  assert.match(content, /captionTrackKey/);
  assert.match(content, /normalizeCaptionBaseUrl/);
  assert.match(content, /rankCaptionTracks/);
  assert.match(content, /captionTrackReliability/);
  assert.match(content, /captionBaseUrlParamCount/);
  assert.doesNotMatch(content, /fetchCaptionTracksFromTimedTextList/);
  assert.doesNotMatch(content, /youtubei\/v1\/get_transcript/);
  assert.match(content, /restoreVideoTime\(startTime\)/);
  assert.match(content, /state\.suppressSeeking/);
  assert.match(content, /queueMicrotask\(\(\) => state\.video\?\.pause\(\)\)/);
  assert.match(content, /state\.partialTranscription/);
  assert.match(content, /pausedVideoForPreparation/);
  assert.match(content, /视频已暂停，可修复设置后重试/);
  assert.match(content, /pendingTranslationTracker/);
  assert.match(content, /reservePendingCues/);
  assert.match(content, /releasePendingCues/);
  assert.match(content, /isCueTranslationPending/);
  assert.match(content, /localtube\.cancelTabAudioRecording/);
  assert.match(content, /activeTranscriptionRequestId/);
  assert.match(content, /activeElementRecording/);
  assert.match(content, /activeDubRequestIds/);
  assert.match(content, /recordVideoElementAudio/);
  assert.match(content, /captureVideoElementAudioStream/);
  assert.match(content, /video\?\.captureStream/);
  assert.match(content, /new MediaStream\(audioTracks\)/);
  assert.match(content, /collectVideoElementRecording/);
  assert.match(content, /const settle = \(callback, value\)/);
  assert.match(content, /无法开始播放器录音/);
  assert.match(content, /cancelElementAudioRecording\(activeTranscriptionRequestId\)/);
  assert.match(content, /localtube\.transcribeCapturedAudio/);
  assert.match(content, /localtube\.transcribeVideoWindow/);
  assert.match(content, /requestId\s*\n\s*\}/);
  assert.match(content, /video-window-\$\{operationId\}/);
  assert.match(content, /if \(activeTranscriptionRequestId\) \{\s*cancelTabAudioRecording\(activeTranscriptionRequestId\)/);
  assert.match(content, /LOCAL_VIDEO_INITIAL_WINDOW_SECONDS = 30/);
  assert.match(content, /LOCAL_VIDEO_ROLLING_WINDOW_SECONDS = 45/);
  assert.match(content, /LOCAL_VIDEO_ROLLING_LEAD_SECONDS = 18/);
  assert.match(content, /maybePrefetchRollingTranscription/);
  assert.match(content, /maybePauseForRollingTranscription/);
  assert.match(content, /releaseRollingTranscriptionBuffer/);
  assert.match(content, /selectNewRollingCues/);
  assert.match(content, /mergeCueTimeline/);
  assert.match(content, /normalizeTranscriptionCues/);
  assert.match(content, /没有识别到可翻译的人声/);
  assert.match(content, /cancelTabAudioRecording\(activeTranscriptionRequestId\)/);
  assert.match(content, /if \(wasBusy && state\.video\)/);
  assert.match(content, /cancelActiveProviderDubs\(\)/);
  assert.match(content, /async function cancelProviderDub/);
  assert.match(content, /localtube\.cancelProviderDub/);
  assert.match(content, /AI 翻译超时/);
  assert.match(content, /await cancelProviderDub\(requestId\)/);
  assert.match(content, /字幕轨道存在，但没有读取到字幕内容/);
  assert.match(content, /VIDEO_UNAVAILABLE/);
  assert.match(content, /VIDEO_UNAVAILABLE: 60 \* 1000/);
  assert.match(content, /不能据此判断为无字幕视频/);
  assert.match(content, /makeCaptionFetchCandidates\(track\.baseUrl\)/);
  assert.doesNotMatch(content, /addQuery\(track\.baseUrl, \{ fmt: "srv1"/);
  assert.doesNotMatch(content, /addQuery\(track\.baseUrl, \{ fmt: "ttml"/);
  assert.match(content, /captionFetchLabel/);
  assert.match(content, /async function youtubeFetch/);
  assert.match(content, /credentials: "include"/);
  assert.match(content, /function canFetchDirectlyFromYouTube/);
  assert.match(content, /function isYouTubeAdShowing/);
  assert.match(content, /function delay/);
  assert.match(content, /requestId\s*=\s*`tab-audio-\$\{operationId\}/);
  assert.match(content, /async function cancelTabAudioRecording/);
  assert.match(content, /await cancelTabAudioRecording\(requestId\)/);
  assert.match(content, /startStatusPulse/);
  assert.match(content, /clearStatusPulse/);
  assert.match(content, /prepareTabAudioCapture\(durationSeconds\)/);
  assert.match(content, /页面录音不可用/);
  assert.match(content, /正在准备当前标签页录音权限/);
  assert.match(content, /streamId: preparedCapture\.streamId/);
  assert.match(content, /setWidgetPhase\("recording"\)/);
  assert.match(content, /setWidgetPhase\("transcribing"\)/);
  assert.match(content, /startButtonLabel/);
  assert.match(content, /startButton\.disabled = state\.busy \|\| state\.running/);
  assert.match(content, /translateCurrentPlaybackWindow/);
  assert.match(content, /maybeTranslatePlaybackGap/);
  assert.match(content, /正在补翻当前播放位置/);
  assert.match(content, /priorityTranslationOperationId/);
  assert.match(content, /正在优先补翻当前进度/);
  assert.match(content, /hasSourceCueAt/);
  assert.match(content, /需要短暂播放录音/);
  assert.match(content, /正在从播放器录制/);
  assert.match(content, /正在录制标签页音频/);
  assert.match(content, /录完会回到原进度并暂停/);
  assert.match(content, /正在转写音频/);
  assert.match(content, /hasTranscriptionApiKey/);
  assert.doesNotMatch(content, /本地 Engine 转写还没有接入/);
  assert.match(content, /translateQueuedCues/);
  assert.match(content, /已同步首段/);
  assert.match(content, /requestId,\s*\n\s*settings: state\.settings/);
  assert.match(content, /state\.activeDubRequestIds\.delete\(requestId\)/);

  const background = fs.readFileSync(path.join(root, "extension", "background.js"), "utf8");
  assert.match(background, /allowAudioTranscription: false/);
  assert.match(background, /allowAudioTranscription: Boolean\(merged\.allowAudioTranscription\)/);
  assert.match(background, /localtube\.resolveCaptions/);
  assert.match(background, /resolveCaptionsWithEngine/);
  assert.match(background, /\/api\/captions/);
  assert.match(background, /captionEngineHttpCode/);
  assert.match(background, /status === 422/);
  assert.match(background, /classifyCaptionEngineErrors/);
  assert.match(background, /type: "captions"/);
  assert.match(background, /credentials: request\.credentials \|\| "omit"/);
  assert.match(background, /TAB_CAPTURE_PERMISSION_REQUIRED/);
  assert.match(background, /TAB_CAPTURE_API_PERMISSION_REQUIRED/);
  assert.match(background, /assertOptionalApiPermissions\(optionalCapturePermissions\(true\)\)/);
  assert.match(background, /assertOptionalApiPermissions\(\["offscreen"\]\)/);
  assert.match(background, /importScripts\("permission_helpers\.js", "background_helpers\.js"\)/);
  assert.match(background, /dubRequestRegistry/);
  assert.match(background, /handleProviderDub/);
  assert.match(background, /code: nativePayload\?\.code \|\| "NATIVE_TRANSLATION_FAILED"/);
  assert.match(background, /localtube\.cancelProviderDub/);
  assert.match(background, /localtube\.transcribeCapturedAudio/);
  assert.match(background, /async function transcribeCapturedAudio/);
  assert.match(background, /async function transcribeVideoWindow/);
  assert.match(background, /async function transcribeVideoWindowRequest/);
  assert.match(background, /transcriptionRequestRegistry\.begin\([\s\S]*video-window:/);
  assert.match(background, /\/api\/transcribe-video/);
  assert.match(background, /type: "transcribe-video"/);
  assert.match(background, /async function startFullTranscript/);
  assert.match(background, /async function getFullTranscriptStatus/);
  assert.match(background, /async function cancelFullTranscript/);
  assert.match(background, /\/api\/full-transcript\/start/);
  assert.match(background, /\/api\/full-transcript\/status\?id=/);
  assert.match(background, /\/api\/full-transcript\/cancel/);
  assert.match(background, /async function startDubTrack/);
  assert.match(background, /async function getDubTrackStatus/);
  assert.match(background, /async function cancelDubTrack/);
  assert.match(background, /function normalizeDubTrackCues/);
  assert.match(background, /\/api\/dub-track\/start/);
  assert.match(background, /\/api\/dub-track\/status\?id=/);
  assert.match(background, /\/api\/dub-track\/cancel/);
  assert.match(background, /mixOriginal: payload\.mixOriginal === true/);
  assert.match(background, /originalVolume: clamp\(Number\(payload\.originalVolume/);
  assert.match(background, /payload\.outputFormat === "wav" \|\| payload\.outputFormat === "m4a"/);
  assert.match(background, /dubTrackFormat: merged\.dubTrackFormat === "wav" \? "wav" : "m4a"/);
  assert.match(background, /let httpTerminalError = ""/);
  assert.match(background, /response\.status && response\.status !== 404/);
  assert.match(background, /transport: "video-element-audio"/);
  assert.match(background, /INVALID_RECORDING/);
  assert.match(background, /hasTranscriptionApiKey: transcriptionProvider\.keyMode === "none" \|\| Boolean\(transcriptionApiKey\)/);
  assert.match(background, /transcribeRecordingWithNativeEngine/);
  assert.match(background, /`\$\{endpoint\}\/api\/transcribe`/);
  assert.match(background, /HTTP Engine：\$\{response\.error/);
  assert.match(background, /Native Engine：\$\{payload\?\.error/);
  assert.match(background, /type: "transcribe"/);
  assert.match(background, /sendNativeMessageWithAbort/);
  assert.match(background, /throwIfAborted/);
  assert.match(background, /翻译已取消/);
  assert.match(background, /abortMessage: request\.abortMessage \|\| "翻译已取消"/);
  assert.match(background, /abortMessage = "转写已取消"/);
  assert.match(background, /fetchProviderJson\(context\.endpoint/);
  assert.match(background, /microsoft-translator/);
  assert.match(background, /google-translate/);
  assert.match(background, /translateBatchWithMicrosoft/);
  assert.match(background, /translateBatchWithGoogleTranslate/);
  assert.match(background, /async function translateApiBatchWithRecovery/);
  assert.match(background, /cleaned\.length === cues\.length && cleaned\.every\(Boolean\)/);
  assert.match(background, /translateApiBatchWithRecovery\(cues\.slice\(0, midpoint\), context\)/);
  assert.doesNotMatch(background, /translations\.concat\(Array\(expectedLength - translations\.length\)\.fill\(""\)\)/);
  assert.match(background, /translationApiLanguage/);
  assert.match(background, /signal: context\.signal/);
  assert.match(background, /signal: options\.signal/);
  assert.match(background, /throwIfAborted\(signal, "转写已取消"\);\s*const recording = await chrome\.runtime\.sendMessage/);
  assert.match(background, /throwIfAborted\(signal, "转写已取消"\);\s*const transcript = await transcribeRecording/);
  assert.match(background, /transcriptionProviders: getTranscriptionProviderList\(\)/);
  assert.match(background, /function getTranscriptionProviderList/);
  assert.match(background, /localtube\.prepareTabAudioCapture/);
  assert.match(background, /localtube\.synthesizeSpeech/);
  assert.match(background, /localtube\.listVoices/);
  assert.match(background, /REQUIRED_ENGINE_PROTOCOL_VERSION = 2/);
  assert.match(background, /assessEngineCompatibility/);
  assert.match(background, /async function listAvailableVoices/);
  assert.match(background, /localtube\.startEngine/);
  assert.match(background, /localtube\.restartEngine/);
  assert.match(background, /async function startLocalEngine/);
  assert.match(background, /async function restartLocalEngine/);
  assert.match(background, /captionEngineAutoStartInFlight/);
  assert.match(background, /requestCaptionsOverHttp/);
  assert.match(background, /shouldAutoStartCaptionEngine\(httpResult\)/);
  assert.match(background, /autoStartCaptionHttpEngine\(localEndpoint, errors, 4500\)/);
  assert.match(background, /async function autoStartCaptionHttpEngine/);
  assert.match(background, /async function recoverHttpEngineAfterNativeError/);
  assert.match(background, /recoveredAfterNativeExit/);
  assert.match(background, /type: "start-http"/);
  assert.match(background, /type: "restart-http"/);
  assert.match(background, /\/api\/restart/);
  assert.match(background, /async function synthesizeSpeechWithEngine/);
  assert.match(background, /targetDuration: clamp\(Number\(payload\.targetDuration \|\| 0\), 0, 30\)/);
  assert.match(background, /maxFitRate: clamp\(Number\(payload\.maxFitRate \|\| 1\.3\), 1, 2\)/);
  assert.match(background, /\/api\/tts/);
  assert.match(background, /type: "tts"/);
  assert.match(background, /async function prepareTabAudioCapture/);
  assert.match(background, /transcriptionRequestRegistry/);
  assert.match(background, /cancelTabAudioRecording\(message\.requestId\)/);
  assert.match(background, /cancelTranscriptionRequest/);
  assert.match(background, /signal/);
  assert.match(background, /转写已取消/);
  assert.match(background, /payload\.streamId \? \{ ok: true, streamId: payload\.streamId \}/);
  assert.match(background, /clamp\(Number\(payload\.durationSeconds \|\| DEFAULT_TRANSCRIPTION_SECONDS\), 6, 20\)/);
  assert.match(background, /spoken wording for dubbing/);
  assert.match(background, /seconds: Number\.isFinite/);
  assert.match(background, /browser-translator/);
  assert.match(background, /BROWSER_TRANSLATOR_PAGE_ONLY/);
  assert.match(background, /classifyProviderFailure/);
  assert.match(background, /providerFailureMessage/);
  assert.match(background, /assertOptionalHostPermission/);
  assert.match(background, /chrome\.permissions\.contains/);
  assert.match(background, /localtube\.installLocalWhisper/);
  assert.match(background, /type: "install-whisper"/);
  assert.match(background, /function sanitizeTtsEngine/);
  assert.match(background, /ttsEngine: sanitizeTtsEngine/);

  const contentCss = fs.readFileSync(path.join(root, "extension", "content.css"), "utf8");
  assert.match(contentCss, /\.ltd-button:disabled/);
  assert.match(contentCss, /\.ltd-actions\s*\{[\s\S]*grid-template-columns: repeat\(2/);
  assert.match(contentCss, /\.ltd-status\s*\{[\s\S]*grid-column: 1 \/ -1/);
  assert.match(contentCss, /\.ltd-export/);
  assert.match(contentCss, /\.ltd-full-transcript/);
  assert.match(contentCss, /\.ltd-dub-track/);
  assert.match(contentCss, /\.ltd-dub-track-preview/);

  const popup = fs.readFileSync(path.join(root, "extension", "popup.js"), "utf8");
  const popupHtml = fs.readFileSync(path.join(root, "extension", "popup.html"), "utf8");
  assert.match(popup, /const EXTENSION_VERSION = chrome\.runtime\.getManifest\(\)\.version/);
  assert.match(popup, /nodes\.appVersion\.textContent = EXTENSION_VERSION/);
  assert.match(popup, /notifyActiveTab\(pageSafeSettings\(settings\)\)/);
  assert.match(popup, /function pageSafeSettings/);
  assert.match(popup, /apiKey: ""/);
  assert.match(popup, /applyProviderRegistry/);
  assert.match(popup, /renderProviderOptions/);
  assert.match(popup, /handleOriginalVolumeInput/);
  assert.match(popup, /volumeSaveTimer/);
  assert.match(popup, /transcriptionProviders/);
  assert.match(popup, /本地 Whisper 尚未安装/);
  assert.match(popup, /allowAudioTranscription/);
  assert.match(popupHtml, /id="allowAudioTranscription"/);
  assert.match(popup, /localtube\.clearTranslationCache/);
  assert.match(popupHtml, /id="cacheTranslations"/);
  assert.match(popupHtml, /id="clearTranslationCache"/);
  assert.match(popupHtml, /LocalTube Dub <span id="appVersion">0\.1\.97<\/span>/);
  assert.match(popupHtml, /id="testProvider"[^>]*>验证翻译 Key<\/button>/);
  assert.match(popup, /saveAndValidateApiKey/);
  assert.match(popupHtml, /免费 \/ 自带 Key/);
  assert.doesNotMatch(popupHtml, /data-mode="(?:local|managed)"/);
  assert.doesNotMatch(popupHtml, /data-panel="(?:local|managed)"/);
  assert.doesNotMatch(popupHtml, /<strong>一键本地<\/strong>|<strong>我们的服务<\/strong>/);
  assert.doesNotMatch(popup, /label: "一键本地"|label: "我们的服务"/);
  assert.doesNotMatch(background, /kind: "managed"/);
  assert.doesNotMatch(content, /\["managed", "我们的服务"\]/);
  assert.match(popupHtml, /<option value="native">本地 Engine（免费，推荐）<\/option>/);
  assert.doesNotMatch(popup, /\.filter\(\(\[id\]\) => id !== "native"\)/);
  assert.doesNotMatch(popup, /next\.transcriptionProvider = "groq"/);
  assert.match(popupHtml, /id="voiceId"/);
  assert.match(popupHtml, /id="ttsEngine"/);
  assert.match(popupHtml, /Microsoft 自然在线（默认）/);
  assert.match(popup, /ttsEngine: "edge"/);
  assert.match(popup, /provider: nodes\.ttsEngine\.value/);
  assert.match(popupHtml, /<script src="voice_helpers\.js"><\/script>/);
  assert.match(popupHtml, /<script src="permission_helpers\.js"><\/script>/);
  assert.match(popup, /ensureSelectedPermissions/);
  assert.match(popup, /optionalCapturePermissions\(Boolean\(settings\.allowAudioTranscription\)\)/);
  assert.match(popup, /permissionsRequest\(details\)/);
  assert.match(popup, /requestPermissions: false/);
  assert.match(popup, /refreshVoiceOptions/);
  assert.match(popup, /selectVoiceOptions/);
  assert.match(popupHtml, /id="originalVolume"/);
  assert.match(popupHtml, /engineStatus/);
  const pageProbe = fs.readFileSync(path.join(root, "extension", "page_probe.js"), "utf8");
  assert.match(pageProbe, /moviePlayer\?\.getPlayerResponse/);
  assert.match(pageProbe, /watchFlexy\?\.playerData/);
  assert.match(pageProbe, /selectCurrentPlayerResponse/);
  assert.match(pageProbe, /window\.ytInitialPlayerResponse/);
  assert.match(pageProbe, /window\.postMessage/);
  assert.match(pageProbe, /localtube-dub:request-page-state/);
  const installJs = fs.readFileSync(path.join(root, "extension", "install.js"), "utf8");
  const installHtml = fs.readFileSync(path.join(root, "extension", "install.html"), "utf8");
  const releaseInfo = JSON.parse(fs.readFileSync(path.join(root, "extension", "release-info.json"), "utf8"));
  assert.equal(releaseInfo.channel, "development");
  assert.match(installHtml, /本地 Engine 体检/);
  assert.match(installHtml, /第一次使用要准备什么/);
  assert.match(installHtml, /升级开发版后要刷新/);
  assert.match(installHtml, /Install LocalTube Dub Engine\.command/);
  assert.match(installHtml, /尚未签名和公证/);
  assert.match(installHtml, /install_helpers\.js[\s\S]*install\.js/);
  assert.match(installHtml, /data-audience="customer"/);
  assert.match(installHtml, /data-audience="developer"/);
  assert.match(installHtml, /页面还在运行旧内容脚本/);
  assert.match(installHtml, /复制一键安装依赖命令/);
  assert.match(installHtml, /一键启动 Engine/);
  assert.match(installHtml, /一键重启 Engine/);
  assert.match(installHtml, /修复开机自启/);
  assert.match(installHtml, /一键安装本地转写/);
  assert.match(installHtml, /whisper\.cpp/);
  assert.match(installHtml, /Address already in use/);
  assert.match(installHtml, /一键重启 Engine.*自动清理确认属于 LocalTube Dub 的旧进程/s);
  assert.match(installHtml, /注册 launcher/);
  assert.match(installHtml, /Native Host 诊断/);
  assert.match(installHtml, /重启 Chrome/);
  assert.match(installJs, /localtube\.startEngine/);
  assert.match(installJs, /localtube\.restartEngine/);
  assert.match(installJs, /localtube\.installLocalWhisper/);
  assert.match(installJs, /localtube\.installEngineAutostart/);
  assert.match(installJs, /install_engine_autostart_macos\.sh/);
  assert.match(installJs, /install_local_whisper_macos\.sh/);
  assert.match(installJs, /install_engine_deps_macos\.sh/);
  assert.match(installJs, /engine-runtime\/\.venv\/bin\/python/);
  assert.match(installJs, /engine-runtime\/companion\/native_host\.py/);
  assert.doesNotMatch(installJs, /\/Users\/kk/);
  assert.match(installJs, /navigator\.clipboard\.writeText/);
  assert.match(installJs, /release-info\.json/);
  assert.match(installJs, /normalizeReleaseInfo/);
  assert.match(installJs, /LOCAL_DUB_YTDLP_COOKIES_FROM_BROWSER=none/);
  assert.match(popup, /isByokProvider/);
  assert.match(popup, /next\.provider = "chrome-translator";\s*next\.transcriptionProvider = "native"/);

  const server = fs.readFileSync(path.join(root, "server", "local_dub_server.py"), "utf8");
  assert.match(server, /CAPTION_FAILURE_BACKOFF_SECONDS/);
  assert.match(server, /"VIDEO_UNAVAILABLE": 60/);
  assert.match(server, /set_cached_caption_failure/);
  assert.match(server, /retryAfterSeconds/);
  assert.match(server, /select_caption_candidates/);
  assert.match(server, /read_ytdlp_caption_candidates/);
  assert.match(server, /def metadata_video_unavailable/);
  assert.match(server, /caption_fetch_urls/);
  assert.match(server, /CAPTION_CANDIDATE_LIMIT/);
  assert.match(server, /CAPTION_URL_ATTEMPT_LIMIT/);
  assert.match(server, /CAPTION_TARGET_URL_ATTEMPT_LIMIT/);
  assert.match(server, /candidate_scope="target"/);
  assert.match(server, /caption_result_matches_target/);
  assert.match(server, /CAPTION_DIRECT_FETCH_BUDGET/);
  assert.match(server, /--ignore-no-formats-error/);
  assert.match(server, /for round_index in range\(max_rounds\)/);
  assert.match(server, /except subprocess\.TimeoutExpired/);
  assert.match(server, /caption_remaining_timeout/);
  assert.match(server, /get_runtime_health/);
  assert.match(server, /EDGE_TTS_VOICES/);
  assert.match(server, /def synthesize_edge_speech_to_wav_file/);
  assert.match(server, /def generate_edge_tts_media/);
  assert.match(server, /edge_tts\.Communicate/);
  assert.match(server, /"edgeTts": edge_tts_available\(\)/);
  assert.match(server, /tts_engine=str\(job\.get\("ttsEngine"\)/);
  assert.match(server, /normalize_caption_language_identity/);
  assert.match(server, /youtube_translated_caption_source_language/);
  assert.match(server, /--write-auto-subs/);
  assert.match(server, /def build_video_transcribe_payload/);
  assert.match(server, /def build_ytdlp_audio_window_command/);
  assert.match(server, /--download-sections/);
  assert.match(server, /def start_full_transcript_job/);
  assert.match(server, /def run_full_transcript_job/);
  assert.match(server, /def build_ytdlp_full_audio_command/);
  assert.match(server, /def run_cancellable_command/);
  assert.match(server, /bestaudio\[abr<=96\]\/bestaudio\/best/);
  assert.match(server, /FULL_TRANSCRIPT_MAX_SECONDS/);
  assert.match(server, /def start_dub_track_job/);
  assert.match(server, /def run_dub_track_job/);
  assert.match(server, /ThreadPoolExecutor/);
  assert.match(server, /as_completed/);
  assert.match(server, /DUB_TRACK_TTS_WORKERS/);
  assert.match(server, /def render_dub_track_segment/);
  assert.match(server, /cancel_event=cancel_event/);
  assert.match(server, /def write_dub_track_wav/);
  assert.match(server, /def write_silent_wav_frames/);
  assert.match(server, /def mix_dub_track_with_original/);
  assert.match(server, /def build_ffmpeg_dub_mix_command/);
  assert.match(server, /amix=inputs=2:duration=longest/);
  assert.match(server, /def encode_dub_track_m4a/);
  assert.match(server, /def build_ffmpeg_m4a_command/);
  assert.match(server, /def probe_audio_duration/);
  assert.match(server, /def find_ffprobe_command/);
  assert.match(server, /"audio\/mp4"/);
  assert.match(server, /stage="encoding"/);
  assert.match(server, /stage="downloading-original"/);
  assert.match(server, /stage="mixing"/);
  assert.match(server, /def synthesize_speech_to_wav_file/);
  assert.match(server, /def build_voices_payload/);
  assert.match(server, /ENGINE_PROTOCOL_VERSION = 2/);
  assert.match(server, /def get_engine_version/);
  assert.match(server, /def parse_system_voice_output/);
  assert.match(server, /\/api\/voices/);
  assert.match(server, /max_fit_rate=4\.5/);
  assert.match(server, /\/api\/dub-track\/download/);
  assert.match(server, /def do_HEAD/);
  assert.match(server, /def parse_http_byte_range/);
  assert.match(server, /content-range/);
  assert.match(server, /accept-ranges/);
  assert.match(server, /inline.*attachment/);
  assert.match(server, /shutil\.copyfileobj/);
  assert.match(server, /def translate_ollama_batch_with_recovery/);
  assert.match(server, /"code": "OLLAMA_UNAVAILABLE"/);
  assert.doesNotMatch(server, /engine = "passthrough"/);
  assert.match(server, /--file-format=WAVE/);
  assert.match(server, /wave\.open/);
  assert.match(server, /def validate_wav_duration/);
  assert.match(server, /def fit_wav_to_target_duration/);
  assert.match(server, /payload\.get\("maxFitRate"\)/);
  assert.match(server, /def build_atempo_filter/);
  assert.match(server, /"-filter:a"/);

  const fullTrackHarness = fs.readFileSync(path.join(root, "tools", "full_track_media_harness.js"), "utf8");
  assert.match(fullTrackHarness, /syncFullTrackMediaElements/);
  assert.match(fullTrackHarness, /requestDubPlayback/);
  assert.match(fullTrackHarness, /error\?\.name !== "AbortError"/);
  assert.match(fullTrackHarness, /data-action='seek'/);
  assert.match(fullTrackHarness, /video\.playbackRate = video\.playbackRate === 1\.5/);
  const liveVoiceHarness = fs.readFileSync(path.join(root, "tools", "live_voice_media_harness.js"), "utf8");
  assert.match(liveVoiceHarness, /syncLiveVoiceMediaElements/);
  assert.match(liveVoiceHarness, /data-action='self-test'/);
  assert.match(liveVoiceHarness, /late\.expectedEnd <= 5\.05/);
  assert.match(liveVoiceHarness, /late\.playbackRate <= 1\.2/);
  assert.match(liveVoiceHarness, /plannedRate: late\.plannedRate/);
  assert.match(liveVoiceHarness, /stable\.playbackRate <= late\.plannedRate \* 1\.03/);
  const voicePickerHarness = fs.readFileSync(path.join(root, "tools", "voice_picker_harness.js"), "utf8");
  assert.match(voicePickerHarness, /http:\/\/127\.0\.0\.1:8787\/api\/voices/);
  assert.doesNotMatch(voicePickerHarness, /127\.0\.0\.1:8790\/api\/voices/);
  assert.match(voicePickerHarness, /api\/voices/);
  assert.match(voicePickerHarness, /hasSpacedVoiceName/);
  const dubTrackBenchmark = fs.readFileSync(path.join(root, "tools", "benchmark_dub_track_parallel.py"), "utf8");
  assert.match(dubTrackBenchmark, /run_render\(server, 1/);
  assert.match(dubTrackBenchmark, /run_render\(server, 3/);
  assert.match(dubTrackBenchmark, /"speedup"/);

  const macNativeInstall = fs.readFileSync(path.join(root, "companion", "install_native_host_macos.sh"), "utf8");
  const macNativeLauncher = fs.readFileSync(path.join(root, "companion", "native_host_launcher_macos.sh"), "utf8");
  const nativeHost = fs.readFileSync(path.join(root, "companion", "native_host.py"), "utf8");
  const dependencyInstall = fs.readFileSync(path.join(root, "scripts", "install_engine_deps_macos.sh"), "utf8");
  const localWhisperInstall = fs.readFileSync(path.join(root, "scripts", "install_local_whisper_macos.sh"), "utf8");
  const engineStart = fs.readFileSync(path.join(root, "scripts", "start_engine_macos.sh"), "utf8");
  const engineAutostartInstall = fs.readFileSync(path.join(root, "scripts", "install_engine_autostart_macos.sh"), "utf8");
  const engineAutostartUninstall = fs.readFileSync(path.join(root, "scripts", "uninstall_engine_autostart_macos.sh"), "utf8");
  const nativeUninstall = fs.readFileSync(path.join(root, "companion", "uninstall_native_host_macos.sh"), "utf8");
  const releaseBuild = fs.readFileSync(path.join(root, "scripts", "build_release_macos.sh"), "utf8");
  const releaseVerify = fs.readFileSync(path.join(root, "tools", "verify_release_packages.py"), "utf8");
  const releaseSmoke = fs.readFileSync(path.join(root, "tools", "smoke_release_macos.sh"), "utf8");
  assert.match(macNativeInstall, /native_host_launcher_macos\.sh/);
  assert.match(macNativeInstall, /\.localtube_python_path/);
  assert.match(macNativeInstall, /install_engine_autostart_macos\.sh/);
  assert.match(macNativeInstall, /Application Support\/LocalTube Dub\/engine-runtime/);
  assert.match(macNativeLauncher, /\.localtube_python_path/);
  assert.match(macNativeLauncher, /RUNTIME_PYTHON="\$SCRIPT_DIR\/\.\.\/\.venv\/bin\/python"/);
  assert.match(macNativeLauncher, /RUNTIME_BIN="\$SCRIPT_DIR\/\.\.\/\.venv\/bin"/);
  assert.match(macNativeLauncher, /-x "\$RUNTIME_PYTHON"/);
  assert.match(macNativeLauncher, /exec "\$PYTHON_BIN" "\$SCRIPT_DIR\/native_host\.py"/);
  assert.match(nativeHost, /NATIVE_LOG_PATH/);
  assert.match(nativeHost, /ENGINE_START_WAIT_SECONDS/);
  assert.match(nativeHost, /start_local_whisper_install/);
  assert.match(nativeHost, /install_local_whisper_macos\.sh/);
  assert.match(nativeHost, /install_engine_autostart/);
  assert.match(nativeHost, /install-autostart/);
  assert.match(nativeHost, /managedByLaunchAgent/);
  assert.match(dependencyInstall, /sys\.version_info >= \(3, 10\)/);
  assert.match(dependencyInstall, /brew install python/);
  assert.match(dependencyInstall, /\.venv/);
  assert.match(dependencyInstall, /\.localtube_python_path/);
  assert.match(dependencyInstall, /edge-tts/);
  assert.match(localWhisperInstall, /brew install whisper-cpp ffmpeg/);
  assert.match(localWhisperInstall, /ggml-\$\{MODEL_NAME\}\.bin/);
  assert.match(localWhisperInstall, /huggingface\.co\/ggerganov\/whisper\.cpp/);
  assert.match(localWhisperInstall, /nohup "\$ROOT_DIR\/scripts\/start_engine_macos\.sh"/);
  assert.match(engineStart, /\.venv\/bin\/python/);
  assert.match(engineStart, /protocolVersion/);
  assert.match(engineStart, /engineVersion/);
  assert.match(engineStart, /EXPECTED_VERSION/);
  assert.match(engineAutostartInstall, /com\.localtube\.dub\.engine\.http/);
  assert.match(engineAutostartInstall, /KeepAlive/);
  assert.match(engineAutostartInstall, /SuccessfulExit/);
  assert.match(engineAutostartInstall, /launchctl bootstrap/);
  assert.match(engineAutostartInstall, /local_dub_server\.py/);
  assert.match(engineAutostartInstall, /LOCAL_DUB_AUTOSTART_DRY_RUN/);
  assert.match(engineAutostartInstall, /Application Support\/LocalTube Dub\/engine-runtime/);
  assert.match(engineAutostartInstall, /release\.json/);
  assert.match(engineAutostartInstall, /protocolVersion/);
  assert.match(engineAutostartInstall, /ditto "\$SOURCE_ROOT\/\.venv"/);
  assert.match(engineAutostartInstall, /companion\/\.localtube_python_path/);
  assert.match(engineAutostartUninstall, /launchctl bootout/);
  assert.match(macNativeInstall, /\^\[a-p\]\{32\}\$/);
  assert.match(macNativeInstall, /LOCAL_DUB_NATIVE_INSTALL_DRY_RUN/);
  assert.match(nativeUninstall, /LOCAL_DUB_UNINSTALL_DRY_RUN/);
  assert.match(nativeUninstall, /Refusing to remove an unrecognized Native Messaging manifest/);
  assert.match(releaseBuild, /LocalTube-Dub-extension-v\$VERSION\.zip/);
  assert.match(releaseBuild, /LocalTube-Dub-Engine-v\$VERSION-macOS/);
  assert.match(releaseBuild, /LOCAL_DUB_ENGINE_DOWNLOAD_URL/);
  assert.match(releaseBuild, /LOCAL_DUB_SUPPORT_URL/);
  assert.match(releaseBuild, /release-info\.json/);
  assert.match(releaseBuild, /must use HTTPS/);
  assert.match(releaseBuild, /verify_release_packages\.py/);
  assert.match(releaseBuild, /smoke_release_macos\.sh/);
  assert.match(releaseVerify, /extension ZIP must contain manifest\.json at its root/);
  assert.match(releaseVerify, /customer install page must keep customer and developer content separated/);
  assert.match(releaseVerify, /engineDownloadUrl/);
  assert.match(releaseVerify, /allowed_origins/);
  assert.match(releaseVerify, /signed.*notarized/s);
  assert.match(releaseSmoke, /macOS release installer smoke test ok/);

  const changelog = fs.readFileSync(path.join(root, "CHANGELOG.md"), "utf8");
  const developmentAudit = fs.readFileSync(path.join(root, "docs", "development-audit.md"), "utf8");
  assert.match(changelog, /0\.1\.93/);
  assert.match(changelog, /exact full text spoken/i);
  assert.match(developmentAudit, /0\.1\.93 Verification Evidence/);
  assert.match(changelog, /0\.1\.92/);
  assert.match(changelog, /leading silence/i);
  assert.match(developmentAudit, /0\.1\.92 Verification Evidence/);
  assert.match(changelog, /0\.1\.86/);
  assert.match(changelog, /Microsoft Edge neural voices/i);
  assert.match(developmentAudit, /0\.1\.86 Verification Evidence/);
  assert.match(changelog, /0\.1\.72/);
  assert.match(changelog, /privacy-bounded local cache/i);
  assert.match(changelog, /0\.1\.71/);
  assert.match(changelog, /Engine protocol version 2/i);
  assert.match(changelog, /outdated HTTP Engine/i);
  assert.match(changelog, /0\.1\.70/);
  assert.match(changelog, /dynamic system-voice discovery/i);
  assert.match(changelog, /175 installed voices/i);
  assert.match(changelog, /0\.1\.69/);
  assert.match(changelog, /live voice timebox synchronizer/i);
  assert.match(changelog, /real HTMLMediaElement self-test/i);
  assert.match(changelog, /0\.1\.68/);
  assert.match(changelog, /real no-caption end-to-end verification/i);
  assert.match(changelog, /0\.1\.67/);
  assert.match(changelog, /round-robin across candidate tracks/i);
  assert.match(changelog, /0\.1\.66/);
  assert.match(changelog, /one-click local mode/i);
  assert.match(changelog, /semantic voice segments/i);
  assert.match(changelog, /0\.1\.65/);
  assert.match(changelog, /customer install view/);
  assert.match(changelog, /0\.1\.64/);
  assert.match(changelog, /private-beta release builder/);
  assert.match(changelog, /0\.1\.63/);
  assert.match(changelog, /2\.19x speedup/);
  assert.match(changelog, /0\.1\.62/);
  assert.match(changelog, /real Chrome media elements/);
  assert.match(changelog, /0\.1\.61/);
  assert.match(changelog, /206 Content-Range/);
  assert.match(changelog, /0\.1\.60/);
  assert.match(changelog, /M4A 小文件/);
  assert.match(changelog, /0\.1\.58/);
  assert.match(changelog, /voice-track rendering/);
  assert.match(changelog, /0\.1\.57/);
  assert.match(changelog, /one-shot full-video transcription/);
  assert.match(changelog, /0\.1\.56/);
  assert.match(changelog, /subtitle export/);
  assert.match(changelog, /0\.1\.55/);
  assert.match(changelog, /LaunchAgent/);
  assert.match(changelog, /0\.1\.54/);
  assert.match(changelog, /ffmpeg `atempo`/);
  assert.match(changelog, /0\.1\.53/);
  assert.match(changelog, /rolling ahead-of-playback transcription/);
  assert.match(changelog, /0\.1\.52/);
  assert.match(changelog, /Chrome local translation.*local whisper\.cpp/s);
  assert.match(changelog, /HTTP Engine.*Native Host/s);
  assert.match(changelog, /0\.1\.51/);
  assert.match(changelog, /whisper\.cpp/);
  assert.match(changelog, /0\.1\.50/);
  assert.match(changelog, /Chrome 本地翻译/);
  assert.match(changelog, /0\.1\.49/);
  assert.match(changelog, /bounded deadline/);
  assert.match(changelog, /0\.1\.48/);
  assert.match(changelog, /rolling cache/);
  assert.match(changelog, /0\.1\.47/);
  assert.match(changelog, /Native Host/);
  assert.match(changelog, /0\.1\.91/);
  assert.match(changelog, /single customer workflow/);
  assert.match(developmentAudit, /Current reviewed version: 0\.1\.97/);
  assert.match(developmentAudit, /Dubbed voice-track export/);
  assert.match(developmentAudit, /Subtitle export/);
  assert.match(developmentAudit, /starts Engine at login/);
  assert.match(developmentAudit, /Historical Failure Modes That Must Not Return/);
  assert.match(developmentAudit, /Source separation and final media muxing/);
  assert.match(developmentAudit, /Required Verification Before Each Release/);
}

async function main() {
  testOptionalHostPermissions();
  testPageProbePlayerResponseSelection();
  testCaptionTrackPicking();
  testCaptionRequestBudget();
  testVoiceOptions();
  testEngineCompatibility();
  testProviderFailureClassification();
  testCaptionEngineAutoStartDecision();
  testTimelineCache();
  testVideoResponseMatching();
  testCaptionPayloadParsing();
  testBalancedJsonExtraction();
  testPlaybackTranslationBatches();
  testSemanticVoiceSegments();
  testCueLockedVoicePresentation();
  testRollingCaptionNormalization();
  await testBackgroundModeNormalization();
  testCueTranslationTracker();
  testRollingTranscriptionCueMerge();
  testSubtitleExportSerialization();
  testDubTrackRenderCues();
  testAudioMixState();
  testFullTrackSync();
  testFullTrackMediaElements();
  testLiveVoiceSync();
  testVoiceDeadlineRateBudget();
  testNaturalVoiceStartupReanchor();
  testLiveVoiceMediaElements();
  testInstallReleaseInfo();
  testTranscriptionRequestRegistry();
  testNoCaptionStartupOrder();
  testManifestAndFlowGuards();
  console.log("extension flow checks ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
