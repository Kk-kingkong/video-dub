const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const helpers = require("../extension/background_helpers.js");
const contentHelpers = require("../extension/content_helpers.js");

const extension = path.resolve(__dirname, "../extension");
const localData = { apiKey_custom: "private-api-key" };
const syncData = { provider: "custom", sourceLanguage: "auto", cacheTranslations: true };
const context = vm.createContext({
  AbortController,
  URL,
  TextEncoder,
  crypto: require("node:crypto").webcrypto,
  chrome: {
    storage: {
      sync: { get: async (defaults) => ({ ...defaults, ...syncData }) },
      local: {
        get: async (key) => ({ [key]: structuredClone(localData[key]) }),
        set: async (values) => Object.assign(localData, structuredClone(values)),
        remove: async (key) => { delete localData[key]; }
      }
    },
    runtime: {
      getManifest: () => ({ version: "test" }),
      onInstalled: { addListener() {} },
      onMessage: { addListener() {} }
    }
  },
  importScripts(...names) {
    for (const name of names) {
      vm.runInContext(fs.readFileSync(path.join(extension, name), "utf8"), context);
    }
  }
});
vm.runInContext(fs.readFileSync(path.join(extension, "background.js"), "utf8"), context);

async function verifyContentCacheIdentity(failures) {
  let failNextApi = false;
  let cacheReadGate = null;
  const page = vm.createContext({
    URL, URLSearchParams, setTimeout, clearTimeout,
    location: new URL("https://www.youtube.com/watch?v=active-cache-video"),
    LocalTubeDubHelpers: contentHelpers,
    LocalTubeDubVoiceHelpers: require("../extension/voice_helpers.js"),
    chrome: { runtime: {
      getManifest: () => ({ version: "test" }),
      async sendMessage(message) {
        if (message.type === "localtube.saveCachedTimeline") {
          return context.saveCachedTranslationTimeline(message.payload, message.settings);
        }
        if (message.type === "localtube.getCachedTimeline") {
          const result = await context.getCachedTranslationTimeline(message.payload, message.settings);
          if (cacheReadGate) await cacheReadGate;
          return result;
        }
        if (message.type === "localtube.providerDub") {
          if (failNextApi) {
            failNextApi = false;
            return { ok: false, error: "API temporarily unavailable" };
          }
          return { ok: true, payload: { cues: message.payload.cues.map((cue) => ({ ...cue, translatedText: `AI ${message.settings.model}: ${cue.text}` })) } };
        }
        throw new Error(`unexpected cache test message: ${message.type}`);
      }
    } }
  });
  vm.runInContext(fs.readFileSync(path.join(extension, "content.js"), "utf8").replace("\nboot();", "\n"), page);
  page.prepareChromeTranslator = async () => ({ translate: async (text) => `Chrome: ${text}` });
  const state = vm.runInContext("state", page);
  const baseSettings = {
    ...state.settings, provider: "custom", model: "model-a", effectiveModel: "model-a", sourceLanguage: "en",
    customEndpoint: "https://selected.example/v1/chat/completions"
  };
  const cues = [0, 1, 2].map((id) => ({ id: String(id), start: id, end: id + 1, text: `caption ${id}` }));
  const reset = async () => {
    await context.clearTranslationTimelineCache();
    state.settings = { ...baseSettings };
    state.runtimeProfile = contentHelpers.createRuntimeProfile(state.settings, "full");
    state.operationId += 1;
    state.timelineCacheProvider = "custom";
    state.timelineCacheIdentity = JSON.stringify([page.timelineCacheRequest(page.getCurrentVideoId(), state.settings.provider), state.settings.model]);
    state.originalCues = cues;
    state.translatedCues = cues.map((cue) => ({ ...cue, translatedText: `original: ${cue.text}` }));
    state.running = true;
  };
  const check = async (body) => {
    try { await reset(); await body(); } catch (error) { failures.push(error); }
  };
  await check(async () => {
    assert.equal(await page.saveSourceCaptionCache(page.getCurrentVideoId(), state.operationId, cues, "en"), true, "an unchanged source track remains cacheable");
    assert.equal(await page.saveTimelineCacheIfComplete(state.operationId), true, "an unchanged complete timeline remains cacheable");
    assert.ok(await page.loadCachedTimeline(page.getCurrentVideoId(), state.operationId, "custom"));
    state.settings.originalVolume = 0.7;
    state.settings.voiceId = "another-voice";
    assert.equal(await page.saveTimelineCacheIfComplete(state.operationId), true, "audio preferences do not invalidate translation caches");
    state.timelineCacheProvider = "youtube-captions";
    assert.equal(await page.saveTimelineCacheIfComplete(state.operationId), true, "native target captions remain cacheable");
  });
  await check(async () => {
    state.translatedCues = [];
    for (const [index, cue] of cues.entries()) {
      failNextApi = index === 1;
      state.translatedCues.push(...await page.translateCues([cue], "en"));
    }
    assert.match(state.translatedCues[0].translatedText, /^AI /);
    assert.match(state.translatedCues[1].translatedText, /^Chrome:/);
    assert.match(state.translatedCues[2].translatedText, /^AI /);
    assert.equal(await page.saveTimelineCacheIfComplete(state.operationId), false, "AI/Chrome mixed timelines must never be stored as a single provider's result");
    assert.equal(localData.translationTimelineCacheV1?.entries?.length || 0, 0, "mixed provider results do not enter durable cache");
    assert.equal(state.running, true, "cache invalidation keeps playback running");
  });
  for (const changed of [
    { model: "model-b" }, { customEndpoint: "https://other.example/v1" },
    { targetLanguage: "ja-JP" }, { sourceLanguage: "ja" }, { provider: "deepseek" }
  ]) {
    await check(async () => {
      Object.assign(state.settings, changed);
      assert.equal(await page.saveTimelineCacheIfComplete(state.operationId), false, `changing ${Object.keys(changed)[0]} must not store an old timeline under new settings`);
      assert.equal(await page.saveSourceCaptionCache(page.getCurrentVideoId(), state.operationId, cues, "en"), false, "changed settings must not relabel an old source track");
      assert.equal(state.running, true);
    });
  }
  await check(async () => {
    state.settings.model = state.settings.effectiveModel = "model-b";
    await page.translateCues([cues[0]], "en");
    state.settings.model = state.settings.effectiveModel = "model-a";
    assert.equal(await page.saveTimelineCacheIfComplete(state.operationId), false, "changing settings back cannot re-enable a timeline that translated with mixed settings");
  });
  await check(async () => {
    await page.saveTimelineCacheIfComplete(state.operationId);
    let releaseRead;
    cacheReadGate = new Promise((resolve) => { releaseRead = resolve; });
    const loading = page.loadCachedTimeline(page.getCurrentVideoId(), state.operationId, "custom");
    state.settings.targetLanguage = "ja-JP";
    releaseRead();
    try {
      assert.equal(await loading, null, "a delayed cache result cannot be applied after its settings change");
    } finally {
      cacheReadGate = null;
    }
  });
}

async function main() {
  const failures = [];
  try {
    const responses = ['["第一段","额外重复","第二段"]', '["第一段"]', '["第二段"]'];
    context.translateBatchWithApiProvider = async (cues) => context.parseTranslationArray(responses.shift(), cues.length);
    const translated = await context.translateApiBatchWithRecovery([{ text: "first" }, { text: "second" }], {});
    assert.deepEqual(Array.from(translated), ["第一段", "第二段"], "extra translations must trigger existing batch recovery");
    assert.equal(responses.length, 0, "both smaller batches must be retried");
  } catch (error) {
    failures.push(error);
  }

  try {
    const request = {
      videoId: "lookup-video", targetLanguage: "zh-CN", provider: "custom", model: "model-a",
      requestedSourceLanguage: "ja", endpoint: "https://selected.example/v1/chat/completions"
    };
    const settings = { provider: "custom", model: "model-a", sourceLanguage: "auto", customEndpoint: "https://default.example/v1/chat/completions" };
    const cues = [{ start: 0, end: 1, text: "こんにちは", translatedText: "你好" }];
    await context.saveCachedTranslationTimeline({ ...request, sourceLanguage: "ja", cues }, settings);
    const lookupRequests = contentHelpers.makeTimelineCacheLookupRequests(request);
    assert.equal((await context.getCachedTranslationTimeline(lookupRequests[1], settings)).payload.hit, true, "frontend lookups preserve the source language and endpoint used for saving");
    assert.equal((await context.getCachedTranslationTimeline(contentHelpers.makeTimelineCacheLookupRequests({
      ...request, requestedSourceLanguage: "en"
    })[1], settings)).payload.hit, false, "frontend source changes miss prior translations");
    assert.equal((await context.getCachedTranslationTimeline(contentHelpers.makeTimelineCacheLookupRequests({
      ...request, endpoint: "https://other.example/v1/chat/completions"
    })[1], settings)).payload.hit, false, "frontend endpoint changes miss prior translations");
    const youtubeRequest = lookupRequests[0];
    assert.equal(youtubeRequest.requestedSourceLanguage, "", "native target captions do not retain translation source overrides");
    assert.equal(youtubeRequest.endpoint, "", "native target captions do not carry custom endpoint credentials");
    await context.saveCachedTranslationTimeline({ ...youtubeRequest, cues }, settings);
    const crossProviderLookup = contentHelpers.makeTimelineCacheLookupRequests({ ...request, provider: "deepseek", model: "other", requestedSourceLanguage: "en" });
    assert.equal((await context.getCachedTranslationTimeline(crossProviderLookup[0], settings)).payload.hit, true, "provider-neutral caption lookups still hit");
    const defaultRequest = { videoId: "default-lookup", targetLanguage: "zh-CN", provider: "custom" };
    await context.saveCachedTranslationTimeline({ ...defaultRequest, cues }, settings);
    assert.equal((await context.getCachedTranslationTimeline(contentHelpers.makeTimelineCacheLookupRequests(defaultRequest)[1], settings)).payload.hit, true, "missing optional fields use the same backend defaults on get/save");
  } catch (error) {
    failures.push(error);
  }

  for (const [field, value] of [["videoId", "ABCdef"], ["model", "Model-a"], ["requestedSourceLanguage", "ja"]]) {
    try {
      const request = { videoId: "abcDEF", targetLanguage: "zh-CN", provider: "custom", model: "model-a", requestedSourceLanguage: "en" };
      const cache = helpers.upsertTimelineCache({}, request, {
        cues: [{ start: 0, end: 1, text: "hello", translatedText: "你好" }]
      });
      assert.equal(helpers.findTimelineCache(cache, { ...request, [field]: value }).entry, null, `${field} changes must miss stale translations`);
    } catch (error) {
      failures.push(error);
    }
  }

  try {
    const request = { videoId: "video", targetLanguage: "zh-CN", provider: "custom", model: "model-a" };
    const legacyCache = {
      version: 1,
      entries: [{ key: helpers.timelineCacheKey(request), updatedAt: Date.now(), cues: [{ start: 0, end: 1, text: "stale", translatedText: "错配" }] }]
    };
    localData.translationTimelineCacheV1 = legacyCache;
    assert.equal(helpers.findTimelineCache(legacyCache, request).cache.entries.length, 0, "legacy entries are removed even if their keys would match");
    assert.equal((await context.getCachedTranslationTimeline(request)).payload.hit, false, "legacy timelines with untrustworthy identity must expire automatically");
    assert.equal(localData.translationTimelineCacheV1.entries.length, 0, "migration removes only obsolete caption entries");
    assert.equal(localData.apiKey_custom, "private-api-key", "cache migration preserves API keys");
    assert.deepEqual(syncData, { provider: "custom", sourceLanguage: "auto", cacheTranslations: true }, "cache migration preserves settings");
  } catch (error) {
    failures.push(error);
  }

  try {
    const payload = { videoId: "api-video", cues: [{ start: 0, end: 1, text: "hello", translatedText: "你好" }], sourceLanguage: "en" };
    const settings = {
      provider: "custom", model: "model-a", sourceLanguage: "auto",
      customEndpoint: "https://user:password@api.example/v1/chat/completions?key=url-secret&api-version=1#private-fragment"
    };
    assert.equal((await context.saveCachedTranslationTimeline(payload, settings)).payload.saved, true);
    assert.equal((await context.getCachedTranslationTimeline(payload, settings)).payload.hit, true, "get/save use identical resolved defaults; detected source language is metadata");
    for (const changed of [
      { customEndpoint: "https://other.example/v1/chat/completions?api-version=1" },
      { customEndpoint: "https://api.example/v2/chat/completions?api-version=1" },
      { customEndpoint: "https://api.example/v1/chat/completions?api-version=2" },
      { sourceLanguage: "ja" },
      { model: "model-b" }
    ]) {
      assert.equal((await context.getCachedTranslationTimeline(payload, { ...settings, ...changed })).payload.hit, false, `changed ${Object.keys(changed)[0]} must miss cache`);
    }
    assert.equal((await context.getCachedTranslationTimeline(payload, {
      ...settings, customEndpoint: "https://api.example/v1/chat/completions?api-version=1&key=rotated-secret"
    })).payload.hit, true, "credential rotation does not alter translation identity");
    const persistedCache = JSON.stringify(localData.translationTimelineCacheV1);
    assert.doesNotMatch(persistedCache, /url-secret|rotated-secret|password|private-fragment|api\.example/, "cache persists only an endpoint fingerprint");
    for (const provider of ["native", "local-http"]) {
      const engineSettings = { provider, endpoint: "http://127.0.0.1:8787" };
      await context.saveCachedTranslationTimeline(payload, engineSettings);
      assert.equal((await context.getCachedTranslationTimeline(payload, engineSettings)).payload.hit, true);
      assert.equal((await context.getCachedTranslationTimeline(payload, { ...engineSettings, endpoint: "http://127.0.0.1:8788" })).payload.hit, false, "different local engines must not share translations");
    }
    for (const provider of ["youtube-captions", "youtube-source"]) {
      const captions = { ...payload, provider };
      await context.saveCachedTranslationTimeline(captions, settings);
      assert.equal((await context.getCachedTranslationTimeline(captions, { provider: "deepseek", model: "ignored", sourceLanguage: "ja" })).payload.hit, true, "YouTube caption caches remain provider-neutral");
      assert.equal((await context.getCachedTranslationTimeline({ ...captions, targetLanguage: "ja" }, settings)).payload.hit, false, "YouTube track selection still depends on target language");
    }
    const beforeDisable = JSON.stringify(localData);
    assert.equal((await context.getCachedTranslationTimeline(payload, { ...settings, cacheTranslations: false })).payload.disabled, true);
    assert.equal((await context.saveCachedTranslationTimeline(payload, { ...settings, cacheTranslations: false })).payload.disabled, true);
    assert.equal(JSON.stringify(localData), beforeDisable, "disabled cache performs no writes");
    await context.clearTranslationTimelineCache();
    assert.deepEqual(localData, { apiKey_custom: "private-api-key" }, "clear cache preserves credentials");
  } catch (error) {
    failures.push(error);
  }

  try {
    const request = { videoId: "test-video", targetLanguage: "zh-CN", provider: "chrome-translator" };
    const cues = Array.from({ length: 5001 }, (_, index) => ({
      id: String(index), start: index, end: index + 1, text: `source ${index}`, translatedText: `译文 ${index}`
    }));
    const oversized = helpers.upsertTimelineCache({}, request, { cues });
    assert.equal(Boolean(helpers.findTimelineCache(oversized, request).entry), false, "oversized timelines must not become partial cache hits");
    const complete = helpers.upsertTimelineCache({}, request, { cues: cues.slice(0, 5000) });
    assert.equal(helpers.findTimelineCache(complete, request).entry.cues.length, 5000, "complete timelines at the limit remain cacheable");
    const unchanged = helpers.upsertTimelineCache(complete, { ...request, videoId: "oversized-video" }, { cues });
    assert.equal(helpers.findTimelineCache(unchanged, request).entry.cues.length, 5000, "rejecting an oversized timeline preserves other entries");
  } catch (error) {
    failures.push(error);
  }

  await verifyContentCacheIdentity(failures);
  for (const error of failures) console.error(error);
  assert.equal(failures.length, 0, "translation integrity regressions");
  console.log("translation integrity checks ok");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
