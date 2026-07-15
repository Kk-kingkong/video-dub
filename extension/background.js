importScripts("permission_helpers.js", "background_helpers.js");

const { optionalCapturePermissions, optionalOriginForEndpoint } = globalThis.LocalTubeDubPermissionHelpers;

const DEFAULT_SETTINGS = {
  enabled: true,
  setupMode: "byok",
  provider: "chrome-translator",
  endpoint: "http://127.0.0.1:8787",
  customEndpoint: "https://api.openai.com/v1/chat/completions",
  model: "",
  transcriptionProvider: "native",
  transcriptionModel: "",
  allowAudioTranscription: false,
  transcriptionWindowSeconds: 12,
  targetLanguage: "zh-CN",
  sourceLanguage: "auto",
  voiceEnabled: true,
  muteOriginal: false,
  originalVolume: 0.25,
  ttsEngine: "edge",
  voiceId: "auto",
  voiceRate: 1,
  voicePitch: 1,
  cacheTranslations: true,
  dubTrackMode: "voice-only",
  dubTrackFormat: "m4a"
};

const PROVIDERS = {
  openai: {
    label: "OpenAI",
    kind: "openai-compatible",
    endpoint: "https://api.openai.com/v1/chat/completions",
    defaultModel: "gpt-4.1-mini",
    requiresApiKey: true
  },
  gemini: {
    label: "Gemini",
    kind: "gemini",
    endpoint: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    defaultModel: "gemini-2.5-flash",
    requiresApiKey: true
  },
  anthropic: {
    label: "Claude",
    kind: "anthropic",
    endpoint: "https://api.anthropic.com/v1/messages",
    defaultModel: "claude-3-5-haiku-latest",
    requiresApiKey: true
  },
  deepseek: {
    label: "DeepSeek",
    kind: "openai-compatible",
    endpoint: "https://api.deepseek.com/chat/completions",
    defaultModel: "deepseek-chat",
    requiresApiKey: true
  },
  microsoft: {
    label: "Microsoft Translator",
    kind: "microsoft-translator",
    endpoint: "https://api.cognitive.microsofttranslator.com/translate",
    defaultModel: "",
    requiresApiKey: true
  },
  "google-translate": {
    label: "Google Cloud Translation",
    kind: "google-translate",
    endpoint: "https://translation.googleapis.com/language/translate/v2",
    defaultModel: "",
    requiresApiKey: true
  },
  "chrome-translator": {
    label: "Chrome 本地翻译（免费）",
    kind: "browser-translator",
    endpoint: "",
    defaultModel: "",
    requiresApiKey: false
  },
  openrouter: {
    label: "OpenRouter",
    kind: "openai-compatible",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    defaultModel: "openai/gpt-4o-mini",
    requiresApiKey: true
  },
  custom: {
    label: "自定义 OpenAI-compatible",
    kind: "openai-compatible",
    endpoint: "",
    defaultModel: "gpt-4.1-mini",
    requiresApiKey: false
  },
  native: {
    label: "Ollama（本地 Engine）",
    kind: "native",
    endpoint: "",
    defaultModel: "",
    requiresApiKey: false
  },
  "local-http": {
    label: "localhost 调试",
    kind: "local-http",
    endpoint: "http://127.0.0.1:8787",
    defaultModel: "",
    requiresApiKey: false
  }
};

const NATIVE_HOST_NAME = "com.localtube.dub.engine";
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const REQUIRED_ENGINE_PROTOCOL_VERSION = 2;
const OFFSCREEN_DOCUMENT_PATH = "offscreen.html";
const OPENAI_TRANSCRIPTION_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions";
const GROQ_TRANSCRIPTION_ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions";
const DEEPGRAM_TRANSCRIPTION_ENDPOINT = "https://api.deepgram.com/v1/listen";
const DEFAULT_TRANSCRIPTION_SECONDS = 12;
const TIMELINE_CACHE_STORAGE_KEY = "translationTimelineCacheV1";
let creatingOffscreenDocument = null;
let captionEngineAutoStartInFlight = null;
let captionEngineAutoStartCooldownUntil = 0;
const captionResolutionInflight = new Map();
const transcriptionRequestRegistry = LocalTubeDubBackgroundHelpers.createTranscriptionRequestRegistry();
const dubRequestRegistry = LocalTubeDubBackgroundHelpers.createTranscriptionRequestRegistry();

const TRANSCRIPTION_PROVIDERS = {
  groq: {
    label: "Groq Whisper",
    endpoint: GROQ_TRANSCRIPTION_ENDPOINT,
    defaultModel: "whisper-large-v3-turbo",
    keyMode: "transcription"
  },
  deepgram: {
    label: "Deepgram Nova",
    endpoint: DEEPGRAM_TRANSCRIPTION_ENDPOINT,
    defaultModel: "nova-3",
    keyMode: "transcription"
  },
  openai: {
    label: "OpenAI Whisper",
    endpoint: OPENAI_TRANSCRIPTION_ENDPOINT,
    defaultModel: "whisper-1",
    keyMode: "shared-openai"
  },
  native: {
    label: "本地 Engine",
    endpoint: "",
    defaultModel: "",
    keyMode: "none"
  }
};

const ALLOWED_FETCH_URLS = [
  /^https:\/\/(www\.)?youtube\.com\//,
  /^http:\/\/127\.0\.0\.1(:\d+)?\//,
  /^http:\/\/localhost(:\d+)?\//
];

chrome.runtime.onInstalled.addListener(() => {
  getStoredSettings().then((settings) => {
    chrome.storage.sync.set(sanitizeSettings(settings));
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !message.type) {
    return false;
  }

  if (message.type === "localtube.getSettings") {
    buildSettingsResponse()
      .then((response) => sendResponse(response))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.setSettings") {
    saveSettings(message.settings || {})
      .then((settings) => buildSettingsResponse(settings.provider))
      .then((response) => sendResponse(response))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.clearApiKey") {
    const provider = sanitizeProvider(message.provider);
    chrome.storage.local.remove(secretStorageKey(provider), () => {
      buildSettingsResponse(provider).then((response) => sendResponse(response));
    });
    return true;
  }

  if (message.type === "localtube.clearTranscriptionApiKey") {
    const provider = sanitizeTranscriptionProvider(message.provider);
    chrome.storage.local.remove(transcriptionSecretStorageKey(provider), () => {
      buildSettingsResponse().then((response) => sendResponse(response));
    });
    return true;
  }

  if (message.type === "localtube.getCachedTimeline") {
    getCachedTranslationTimeline(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.saveCachedTimeline") {
    saveCachedTranslationTimeline(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.clearTranslationCache") {
    clearTranslationTimelineCache()
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.engineHealth" || message.type === "localtube.providerHealth") {
    checkProviderHealth(message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.captionEngineHealth") {
    checkCaptionEngineHealth(message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.listVoices") {
    listAvailableVoices(message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.restartEngine") {
    restartLocalEngine(message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.startEngine") {
    startLocalEngine(message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.installLocalWhisper") {
    installLocalWhisper()
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.installEngineAutostart") {
    installEngineAutostart()
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.openInstallGuide") {
    chrome.tabs.create({ url: chrome.runtime.getURL("install.html") });
    sendResponse({ ok: true });
    return false;
  }

  if (message.type === "localtube.engineDub" || message.type === "localtube.providerDub") {
    handleProviderDub(message, sender.tab?.id)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.resolveCaptions") {
    resolveCaptionsWithEngine(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.synthesizeSpeech") {
    synthesizeSpeechWithEngine(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.cancelProviderDub") {
    sendResponse({ ok: true, cancelled: dubRequestRegistry.cancel(message.requestId) });
    return false;
  }

  if (message.type === "localtube.transcribeTabAudio") {
    transcribeTabAudio(message.payload, message.settings, sender.tab?.id)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.transcribeCapturedAudio") {
    transcribeCapturedAudio(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.transcribeVideoWindow") {
    transcribeVideoWindow(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.startFullTranscript") {
    startFullTranscript(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.fullTranscriptStatus") {
    getFullTranscriptStatus(message.jobId, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.cancelFullTranscript") {
    cancelFullTranscript(message.jobId, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.startDubTrack") {
    startDubTrack(message.payload, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.dubTrackStatus") {
    getDubTrackStatus(message.jobId, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.cancelDubTrack") {
    cancelDubTrack(message.jobId, message.settings)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.prepareTabAudioCapture") {
    prepareTabAudioCapture(message.payload, message.settings, sender.tab?.id)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.cancelTabAudioRecording") {
    cancelTabAudioRecording(message.requestId)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message.type === "localtube.fetch") {
    fetchForExtension(message.request)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  return false;
});

async function getStoredSettings() {
  const stored = await chrome.storage.sync.get(DEFAULT_SETTINGS);
  return migrateSettings(stored);
}

async function buildSettingsResponse(providerHint) {
  const settings = sanitizeSettings(await getStoredSettings());
  const provider = sanitizeProvider(providerHint || settings.provider);
  const apiKey = await getApiKey(provider);
  const openaiApiKey = await getApiKey("openai");
  const transcriptionApiKey = await getTranscriptionApiKey(settings.transcriptionProvider);
  const transcriptionProvider = getTranscriptionProvider(settings.transcriptionProvider);

  return {
    ok: true,
    settings: {
      ...settings,
      provider,
      hasApiKey: Boolean(apiKey),
      hasOpenAIKey: Boolean(openaiApiKey),
      hasTranscriptionApiKey: transcriptionProvider.keyMode === "none" || Boolean(transcriptionApiKey),
      providerLabel: getProvider(provider).label,
      transcriptionProviderLabel: transcriptionProvider.label,
      effectiveEndpoint: resolveProviderEndpoint(settings),
      effectiveModel: resolveProviderModel(settings),
      effectiveTranscriptionModel: resolveTranscriptionModel(settings)
    },
    providers: getProviderList(),
    transcriptionProviders: getTranscriptionProviderList()
  };
}

async function saveSettings(rawSettings) {
  const settings = sanitizeSettings(rawSettings);
  const secretProvider = sanitizeProvider(rawSettings.provider || settings.provider);
  const apiKey = String(rawSettings.apiKey || "").trim();
  const transcriptionApiKey = String(rawSettings.transcriptionApiKey || "").trim();
  const transcriptionProvider = sanitizeTranscriptionProvider(
    rawSettings.transcriptionProvider || settings.transcriptionProvider
  );

  await chrome.storage.sync.set(settings);

  if (apiKey) {
    await chrome.storage.local.set({ [secretStorageKey(secretProvider)]: apiKey });
  }

  if (transcriptionApiKey) {
    await chrome.storage.local.set({ [transcriptionSecretStorageKey(transcriptionProvider)]: transcriptionApiKey });
  }

  return settings;
}

function migrateSettings(settings) {
  if (settings.provider) {
    return settings;
  }

  if (settings.engineMode === "http") {
    return { ...settings, provider: "local-http" };
  }

  if (settings.engineMode === "native") {
    return { ...settings, provider: "native" };
  }

  return { ...settings, provider: DEFAULT_SETTINGS.provider };
}

function sanitizeSettings(settings) {
  const merged = migrateSettings({ ...DEFAULT_SETTINGS, ...settings });
  const legacySetupMode = String(merged.setupMode || "");
  const setupMode = DEFAULT_SETTINGS.setupMode;
  let provider = sanitizeProvider(merged.provider);
  const endpoint = String(merged.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const customEndpoint = String(merged.customEndpoint || DEFAULT_SETTINGS.customEndpoint).replace(/\/+$/, "");
  const model = String(merged.model || "").trim();
  let transcriptionProvider = sanitizeTranscriptionProvider(merged.transcriptionProvider);
  const transcriptionModel = String(merged.transcriptionModel || "").trim();

  if (legacySetupMode === "local") {
    provider = "chrome-translator";
    transcriptionProvider = "native";
  } else if (legacySetupMode === "managed" || merged.provider === "managed") {
    provider = "chrome-translator";
  }

  return {
    enabled: Boolean(merged.enabled),
    setupMode,
    provider,
    endpoint,
    customEndpoint,
    model,
    transcriptionProvider,
    transcriptionModel,
    allowAudioTranscription: Boolean(merged.allowAudioTranscription),
    transcriptionWindowSeconds: clamp(Number(merged.transcriptionWindowSeconds || DEFAULT_SETTINGS.transcriptionWindowSeconds), 6, 20),
    targetLanguage: String(merged.targetLanguage || DEFAULT_SETTINGS.targetLanguage),
    sourceLanguage: String(merged.sourceLanguage || DEFAULT_SETTINGS.sourceLanguage),
    voiceEnabled: Boolean(merged.voiceEnabled),
    muteOriginal: Boolean(merged.muteOriginal),
    originalVolume: clamp(Number(merged.originalVolume ?? DEFAULT_SETTINGS.originalVolume), 0, 1),
    ttsEngine: sanitizeTtsEngine(merged.ttsEngine),
    voiceId: sanitizeVoiceId(merged.voiceId),
    voiceRate: clamp(Number(merged.voiceRate || DEFAULT_SETTINGS.voiceRate), 0.6, 1.4),
    voicePitch: clamp(Number(merged.voicePitch || DEFAULT_SETTINGS.voicePitch), 0.7, 1.3),
    cacheTranslations: Boolean(merged.cacheTranslations),
    dubTrackMode: merged.dubTrackMode === "mixed" ? "mixed" : "voice-only",
    dubTrackFormat: merged.dubTrackFormat === "wav" ? "wav" : "m4a"
  };
}

async function getCachedTranslationTimeline(payload = {}, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  if (!storedSettings.cacheTranslations) {
    return { ok: true, payload: { hit: false, disabled: true } };
  }
  const stored = await chrome.storage.local.get(TIMELINE_CACHE_STORAGE_KEY);
  const result = LocalTubeDubBackgroundHelpers.findTimelineCache(stored[TIMELINE_CACHE_STORAGE_KEY], payload);
  await chrome.storage.local.set({ [TIMELINE_CACHE_STORAGE_KEY]: result.cache });
  return {
    ok: true,
    payload: {
      hit: Boolean(result.entry),
      entry: result.entry || null,
      count: result.cache.entries.length
    }
  };
}

async function saveCachedTranslationTimeline(payload = {}, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  if (!storedSettings.cacheTranslations) {
    return { ok: true, payload: { saved: false, disabled: true } };
  }
  const request = {
    videoId: String(payload.videoId || ""),
    targetLanguage: String(payload.targetLanguage || storedSettings.targetLanguage || ""),
    provider: String(payload.provider || storedSettings.provider || ""),
    model: String(payload.model || storedSettings.model || "")
  };
  const stored = await chrome.storage.local.get(TIMELINE_CACHE_STORAGE_KEY);
  const cache = LocalTubeDubBackgroundHelpers.upsertTimelineCache(
    stored[TIMELINE_CACHE_STORAGE_KEY],
    request,
    {
      sourceLanguage: payload.sourceLanguage,
      trackLanguage: payload.trackLanguage,
      cues: payload.cues
    }
  );
  await chrome.storage.local.set({ [TIMELINE_CACHE_STORAGE_KEY]: cache });
  const entry = LocalTubeDubBackgroundHelpers.findTimelineCache(cache, request).entry;
  return { ok: true, payload: { saved: Boolean(entry), count: cache.entries.length } };
}

async function clearTranslationTimelineCache() {
  await chrome.storage.local.remove(TIMELINE_CACHE_STORAGE_KEY);
  return { ok: true, payload: { cleared: true } };
}

function sanitizeVoiceId(voiceId) {
  const value = String(voiceId || DEFAULT_SETTINGS.voiceId).trim();
  return value || DEFAULT_SETTINGS.voiceId;
}

function sanitizeTtsEngine(value) {
  return String(value || "").toLowerCase() === "system" ? "system" : "edge";
}

function sanitizeProvider(provider) {
  return PROVIDERS[provider] ? provider : DEFAULT_SETTINGS.provider;
}

function getProvider(provider) {
  return PROVIDERS[sanitizeProvider(provider)];
}

function sanitizeTranscriptionProvider(provider) {
  return TRANSCRIPTION_PROVIDERS[provider] ? provider : DEFAULT_SETTINGS.transcriptionProvider;
}

function getTranscriptionProvider(provider) {
  return TRANSCRIPTION_PROVIDERS[sanitizeTranscriptionProvider(provider)];
}

function getProviderList() {
  return Object.entries(PROVIDERS)
    .filter(([id]) => id !== "local-http")
    .map(([id, provider]) => ({
      id,
      label: provider.label,
      kind: provider.kind,
      endpoint: provider.endpoint,
      defaultModel: provider.defaultModel,
      requiresApiKey: provider.requiresApiKey
    }));
}

function getTranscriptionProviderList() {
  return Object.entries(TRANSCRIPTION_PROVIDERS).map(([id, provider]) => ({
    id,
    label: provider.label,
    endpoint: provider.endpoint,
    defaultModel: provider.defaultModel,
    requiresApiKey: provider.keyMode !== "none"
  }));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));
}

function secretStorageKey(provider) {
  return `apiKey:${sanitizeProvider(provider)}`;
}

function transcriptionSecretStorageKey(provider) {
  return `transcriptionApiKey:${sanitizeTranscriptionProvider(provider)}`;
}

async function getApiKey(provider) {
  const key = secretStorageKey(provider);
  const stored = await chrome.storage.local.get(key);
  return String(stored[key] || "").trim();
}

async function getTranscriptionApiKey(provider) {
  const safeProvider = sanitizeTranscriptionProvider(provider);
  if (safeProvider === "openai") {
    const dedicatedKey = await getStoredSecret(transcriptionSecretStorageKey(safeProvider));
    return dedicatedKey || getApiKey("openai");
  }

  if (safeProvider === "native") {
    return "";
  }

  return getStoredSecret(transcriptionSecretStorageKey(safeProvider));
}

async function getStoredSecret(key) {
  const stored = await chrome.storage.local.get(key);
  return String(stored[key] || "").trim();
}

async function checkProviderHealth(settings = {}) {
  const nextSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const provider = getProvider(nextSettings.provider);

  if (provider.kind === "browser-translator") {
    return {
      ok: true,
      payload: {
        transport: "chrome-translator",
        requiresPageCheck: true
      }
    };
  }

  if (provider.kind === "local-http") {
    return fetchJson(`${nextSettings.endpoint}/api/health`, { method: "GET" });
  }

  if (provider.kind === "native") {
    try {
      const payload = await sendNativeMessage({ type: "health" });
      return { ok: Boolean(payload?.ok), payload };
    } catch (error) {
      return {
        ok: false,
        code: "ENGINE_NOT_INSTALLED",
        error: error.message || String(error)
      };
    }
  }

  const demoPayload = {
    videoUrl: "health-check",
    targetLanguage: nextSettings.targetLanguage,
    sourceLanguage: "en",
    cues: [{ id: "health", start: 0, end: 1, text: "Hello" }]
  };

  return dubWithProvider(demoPayload, nextSettings, { healthCheck: true });
}

async function checkCaptionEngineHealth(settings = {}) {
  const nextSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const endpoint = (nextSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const errors = [];

  try {
    const response = await fetchJson(`${endpoint}/api/health`, {
      method: "GET",
      timeoutMs: 2500,
      timeoutMessage: "HTTP Engine 体检超时"
    });
    if (response.ok) {
      return httpEngineSuccessPayload(response, { endpoint });
    }
    errors.push(`HTTP Engine：${response.error || "健康检查失败"}`);
  } catch (error) {
    errors.push(`HTTP Engine：${error.message || String(error)}`);
  }

  try {
    const nativePayload = await sendNativeMessage({ type: "health" });
    if (nativePayload?.ok) {
      const recovered = await autoStartCaptionHttpEngine(endpoint, errors);
      if (recovered?.ok) {
        return recovered;
      }
      return nativeEngineSuccessPayload(nativePayload, {
        httpOffline: true,
        endpoint
      });
    }
    errors.push(`Native Engine：${nativePayload?.error || "健康检查失败"}`);
  } catch (error) {
    errors.push(`Native Engine：${error.message || String(error)}`);
    const recovered = await recoverHttpEngineAfterNativeError(endpoint, 9000, {
      autoStarted: true,
      recoveredAfterNativeExit: true,
      endpoint
    });
    if (recovered?.ok) {
      return recovered;
    }
  }

  return {
    ok: false,
    code: "CAPTION_ENGINE_OFFLINE",
    error: errors.join("；")
  };
}

async function handleProviderDub(message = {}, tabId) {
  const payload = message.payload || {};
  const requestIdHint = payload.requestId || message.requestId || `dub:${tabId || "background"}:${Date.now()}`;
  const { requestId, controller, signal } = dubRequestRegistry.begin(requestIdHint);

  try {
    throwIfAborted(signal, "翻译已取消");
    return await dubWithProvider(payload, message.settings, { requestId, signal });
  } finally {
    dubRequestRegistry.complete(requestId, controller);
  }
}

async function dubWithProvider(payload = {}, settings = {}, options = {}) {
  const storedSettings = await getStoredSettings();
  const nextSettings = sanitizeSettings({ ...storedSettings, ...settings });
  const provider = getProvider(nextSettings.provider);
  throwIfAborted(options.signal, options.abortMessage || "翻译已取消");

  if (provider.kind === "local-http") {
    return fetchJson(`${nextSettings.endpoint}/api/dub`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      signal: options.signal,
      abortMessage: "翻译已取消"
    });
  }

  if (provider.kind === "native") {
    return dubWithNativeEngine(payload, options);
  }

  if (provider.kind === "browser-translator") {
    return {
      ok: false,
      code: "BROWSER_TRANSLATOR_PAGE_ONLY",
      error: "Chrome 本地翻译需要在当前 YouTube 页面中运行。"
    };
  }

  return dubWithApiProvider(payload, nextSettings, provider, options);
}

async function resolveCaptionsWithEngine(payload = {}, settings = {}) {
  const storedSettings = await getStoredSettings();
  const nextSettings = sanitizeSettings({ ...storedSettings, ...settings });
  const requestPayload = {
    videoId: String(payload.videoId || ""),
    videoUrl: String(payload.videoUrl || ""),
    sourceLanguage: String(payload.sourceLanguage || nextSettings.sourceLanguage || "auto"),
    targetLanguage: String(payload.targetLanguage || nextSettings.targetLanguage || DEFAULT_SETTINGS.targetLanguage)
  };
  const localEndpoint = (nextSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const requestKey = [
    requestPayload.videoId || requestPayload.videoUrl,
    requestPayload.sourceLanguage,
    requestPayload.targetLanguage,
    localEndpoint
  ].join("|");
  const existingRequest = captionResolutionInflight.get(requestKey);
  if (existingRequest) {
    return existingRequest;
  }

  const resolution = resolveCaptionsWithPreparedSettings(requestPayload, localEndpoint);
  captionResolutionInflight.set(requestKey, resolution);
  try {
    return await resolution;
  } finally {
    if (captionResolutionInflight.get(requestKey) === resolution) {
      captionResolutionInflight.delete(requestKey);
    }
  }
}

async function resolveCaptionsWithPreparedSettings(requestPayload, localEndpoint) {
  const errors = [];
  let httpResult = await requestCaptionsOverHttp(localEndpoint, requestPayload);
  if (httpResult.ok) {
    return httpResult.result;
  }
  if (httpResult.terminal) {
    return httpResult.result;
  }
  errors.push(httpResult.error);

  if (LocalTubeDubBackgroundHelpers.shouldAutoStartCaptionEngine(httpResult)) {
    const recovery = await autoStartCaptionHttpEngine(localEndpoint, errors, 4500);
    if (recovery?.ok) {
      httpResult = await requestCaptionsOverHttp(localEndpoint, requestPayload);
      if (httpResult.ok || httpResult.terminal) {
        return httpResult.result;
      }
      errors.push(`HTTP Engine 自动恢复后：${httpResult.error}`);
    }
  }

  try {
    const nativePayload = await sendNativeMessage({
      type: "captions",
      payload: requestPayload
    });
    if (nativePayload?.ok && normalizeCues(nativePayload.cues).length) {
      return {
        ok: true,
        payload: {
          ...nativePayload,
          cues: normalizeCues(nativePayload.cues),
          transport: nativePayload.transport || "native"
        }
      };
    }
    errors.push(`Native Engine：${nativePayload?.code ? `${nativePayload.code} ` : ""}${nativePayload?.error || "没有返回字幕"}`);
  } catch (error) {
    errors.push(`Native Engine：${error.message || String(error)}`);
  }

  return {
    ok: false,
    code: classifyCaptionEngineErrors(errors.join("；")),
    error: errors.join("；")
  };
}

async function requestCaptionsOverHttp(localEndpoint, requestPayload) {
  try {
    const response = await fetchJson(`${localEndpoint}/api/captions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(requestPayload)
    });
    const cues = normalizeCues(response.payload?.cues);
    if (response.ok && cues.length) {
      return {
        ok: true,
        result: {
          ok: true,
          payload: {
            ...response.payload,
            cues,
            transport: response.payload.transport || "http"
          }
        }
      };
    }
    if (response.status) {
      const code = response.payload?.code || captionEngineHttpCode(response.status);
      const retryAfterSeconds = Math.max(0, Number(response.payload?.retryAfterSeconds || 0) || 0);
      return {
        ok: false,
        terminal: true,
        status: response.status,
        code,
        retryAfterSeconds,
        error: `HTTP Engine：${response.error || `HTTP ${response.status}`}`,
        result: {
          ok: false,
          code,
          retryAfterSeconds,
          error: `HTTP Engine：${response.error || `HTTP ${response.status}`}`
        }
      };
    }
    const error = `HTTP Engine：${response.error || "没有返回字幕"}`;
    return {
      ok: false,
      terminal: false,
      status: 0,
      code: classifyCaptionEngineErrors(error),
      error
    };
  } catch (error) {
    const message = `HTTP Engine：${error.message || String(error)}`;
    return {
      ok: false,
      terminal: false,
      status: 0,
      code: classifyCaptionEngineErrors(message),
      error: message
    };
  }
}

function captionEngineHttpCode(status) {
  if (status === 429) {
    return "YOUTUBE_RATE_LIMITED";
  }
  if (status === 404) {
    return "NO_PUBLIC_CAPTIONS";
  }
  if (status === 422) {
    return "VIDEO_UNAVAILABLE";
  }
  if (status === 504) {
    return "ENGINE_TIMEOUT";
  }
  if (status === 400) {
    return "CAPTION_ENGINE_REJECTED";
  }
  return "CAPTION_ENGINE_HTTP_ERROR";
}

function classifyCaptionEngineErrors(message) {
  const text = String(message || "");
  if (/VIDEO_UNAVAILABLE|video unavailable|private video|members.?only|age.?restricted|requested format is not available/i.test(text)) {
    return "VIDEO_UNAVAILABLE";
  }
  if (/429|too many requests|rate.?limit|限流/i.test(text)) {
    return "YOUTUBE_RATE_LIMITED";
  }
  if (/没有读取到可用字幕|no captions|no subtitles|subtitles are disabled/i.test(text)) {
    return "NO_PUBLIC_CAPTIONS";
  }
  if (/返回空内容|empty/i.test(text)) {
    return "CAPTION_EMPTY";
  }
  if (/timeout|timed out|超时/i.test(text)) {
    return "ENGINE_TIMEOUT";
  }
  if (/Failed to fetch|Could not establish connection|ECONNREFUSED|native.*host|host has exited|Extension context invalidated/i.test(text)) {
    return "CAPTION_ENGINE_UNAVAILABLE";
  }
  return "CAPTION_ENGINE_ERROR";
}

async function synthesizeSpeechWithEngine(payload = {}, settings = {}) {
  const storedSettings = await getStoredSettings();
  const nextSettings = sanitizeSettings({ ...storedSettings, ...settings });
  const requestPayload = {
    text: String(payload.text || ""),
    language: String(payload.language || nextSettings.targetLanguage || DEFAULT_SETTINGS.targetLanguage),
    voice: String(payload.voice || nextSettings.voiceId || DEFAULT_SETTINGS.voiceId),
    ttsEngine: sanitizeTtsEngine(payload.ttsEngine || nextSettings.ttsEngine),
    rate: Number(payload.rate || nextSettings.voiceRate || 1),
    targetDuration: clamp(Number(payload.targetDuration || 0), 0, 30),
    maxFitRate: clamp(Number(payload.maxFitRate || 1.3), 1, 2)
  };
  if (!requestPayload.text.trim()) {
    return { ok: false, error: "Missing TTS text" };
  }

  const errors = [];
  const localEndpoint = (nextSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  try {
    const response = await fetchJson(`${localEndpoint}/api/tts`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(requestPayload),
      timeoutMs: 30000,
      timeoutMessage: "本地 TTS 生成超时"
    });
    if (response.ok && response.payload?.dataUrl) {
      return {
        ok: true,
        payload: {
          ...response.payload,
          transport: response.payload.transport || "http"
        }
      };
    }
    errors.push(`HTTP TTS：${response.error || "没有返回音频"}`);
  } catch (error) {
    errors.push(`HTTP TTS：${error.message || String(error)}`);
  }

  try {
    const nativePayload = await sendNativeMessage({
      type: "tts",
      payload: requestPayload
    });
    if (nativePayload?.ok && nativePayload.dataUrl) {
      return {
        ok: true,
        payload: {
          ...nativePayload,
          transport: nativePayload.transport || "native"
        }
      };
    }
    errors.push(`Native TTS：${nativePayload?.error || "没有返回音频"}`);
  } catch (error) {
    errors.push(`Native TTS：${error.message || String(error)}`);
  }

  return {
    ok: false,
    code: "TTS_ENGINE_UNAVAILABLE",
    error: errors.join("；")
  };
}

async function listAvailableVoices(settings = {}) {
  const storedSettings = await getStoredSettings();
  const nextSettings = sanitizeSettings({ ...storedSettings, ...settings });
  const localEndpoint = (nextSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const errors = [];

  try {
    const response = await fetchJson(`${localEndpoint}/api/voices`, {
      method: "GET",
      timeoutMs: 4000,
      timeoutMessage: "读取本机音色超时"
    });
    if (response.ok && Array.isArray(response.payload?.voices)) {
      return {
        ok: true,
        payload: {
          ...response.payload,
          transport: response.payload.transport || "http"
        }
      };
    }
    errors.push(`HTTP TTS：${response.error || "没有返回音色"}`);
  } catch (error) {
    errors.push(`HTTP TTS：${error.message || String(error)}`);
  }

  try {
    const nativePayload = await sendNativeMessage({ type: "voices" });
    if (nativePayload?.ok && Array.isArray(nativePayload.voices)) {
      return {
        ok: true,
        payload: {
          ...nativePayload,
          transport: nativePayload.transport || "native"
        }
      };
    }
    errors.push(`Native TTS：${nativePayload?.error || "没有返回音色"}`);
  } catch (error) {
    errors.push(`Native TTS：${error.message || String(error)}`);
  }

  return {
    ok: false,
    code: "VOICE_LIST_UNAVAILABLE",
    error: errors.join("；")
  };
}

async function restartLocalEngine(settings = {}) {
  const storedSettings = await getStoredSettings();
  const nextSettings = sanitizeSettings({ ...storedSettings, ...settings });
  const localEndpoint = (nextSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const errors = [];

  const response = await fetchJson(`${localEndpoint}/api/restart`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: "{}",
    timeoutMs: 8000,
    timeoutMessage: "Engine 重启请求超时"
  }).catch((error) => ({ ok: false, error: error.message || String(error) }));

  if (response?.ok) {
    const health = await waitForHttpEngine(localEndpoint, 9000);
    if (health?.ok) {
      return httpEngineSuccessPayload(health, { restarted: true });
    }
    errors.push("HTTP 重启后健康检查暂未恢复");
  } else {
    errors.push(
      response?.status === 404
        ? "HTTP Engine 版本过旧，不支持直接重启"
        : `HTTP 重启失败：${response?.error || "Engine 没有响应"}`
    );
  }

  let nativePayload = null;
  try {
    nativePayload = await sendNativeMessage({ type: "restart-http" });
  } catch (error) {
    const message = error.message || String(error);
    const recovered = await recoverHttpEngineAfterNativeError(localEndpoint, 10000, {
      restarted: true,
      recoveredAfterNativeExit: true
    });
    if (recovered?.ok) {
      return recovered;
    }
    return {
      ok: false,
      code: "NATIVE_HOST_NOT_INSTALLED",
      error: `一键重启需要 Native Host。若刚安装过，请完全退出并重启 Chrome；也可以复制启动命令手动启动。${errors.join("；")}；${message}`
    };
  }

  if (!nativePayload?.ok) {
    const recovered = await recoverHttpEngineAfterNativeError(localEndpoint, 10000, {
      restarted: true,
      recoveredAfterNativeExit: true,
      logPath: nativePayload?.logPath || ""
    });
    if (recovered?.ok) {
      return recovered;
    }
    return {
      ok: false,
      code: "ENGINE_RESTART_FAILED",
      error: `${nativePayload?.error || "Native Host 重启失败"}${errors.length ? `；${errors.join("；")}` : ""}`
    };
  }

  const health = await waitForHttpEngine(localEndpoint, 9000);
  if (!health?.ok) {
    return {
      ok: false,
      code: "ENGINE_RESTART_TIMEOUT",
      error: `Engine 已请求强制重启，但健康检查暂未恢复。${nativePayload.logPath ? `日志：${nativePayload.logPath}` : ""}`
    };
  }

  return httpEngineSuccessPayload(health, {
    restarted: true,
    logPath: nativePayload.logPath || ""
  });
}

async function startLocalEngine(settings = {}) {
  const storedSettings = await getStoredSettings();
  const nextSettings = sanitizeSettings({ ...storedSettings, ...settings });
  const localEndpoint = (nextSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");

  const existing = await fetchJson(`${localEndpoint}/api/health`, {
    method: "GET",
    timeoutMs: 1200,
    timeoutMessage: "Engine 未启动"
  }).catch(() => null);
  if (existing?.ok) {
    return httpEngineSuccessPayload(existing, { alreadyRunning: true });
  }

  let nativePayload = null;
  try {
    nativePayload = await sendNativeMessage({ type: "start-http" });
  } catch (error) {
    const message = error.message || String(error);
    const recovered = await recoverHttpEngineAfterNativeError(localEndpoint, 10000, {
      started: true,
      recoveredAfterNativeExit: true
    });
    if (recovered?.ok) {
      return recovered;
    }
    return {
      ok: false,
      code: "NATIVE_HOST_NOT_INSTALLED",
      error: `无法一键启动：Native Host 未安装或 Chrome 还没刷新配置。如果刚安装过 Native Host，请完全退出并重启 Chrome；也可以直接复制启动命令手动启动。${message}`
    };
  }

  if (!nativePayload?.ok) {
    const recovered = await recoverHttpEngineAfterNativeError(localEndpoint, 10000, {
      started: true,
      recoveredAfterNativeExit: true,
      logPath: nativePayload?.logPath || ""
    });
    if (recovered?.ok) {
      return recovered;
    }
    return {
      ok: false,
      code: "ENGINE_START_FAILED",
      error: nativePayload?.error || "Engine 启动失败"
    };
  }

  const health = await waitForHttpEngine(localEndpoint, 10000);
  if (!health?.ok) {
    return {
      ok: false,
      code: "ENGINE_START_TIMEOUT",
      error: "Engine 已请求启动，但健康检查暂未响应。请稍后再点检查，或打开说明查看日志。"
    };
  }

  return httpEngineSuccessPayload(health, {
    started: true,
    logPath: nativePayload.logPath || ""
  });
}

async function installLocalWhisper() {
  try {
    const payload = await sendNativeMessage({ type: "install-whisper" });
    if (!payload?.ok) {
      return {
        ok: false,
        code: "WHISPER_INSTALL_FAILED",
        error: payload?.error || "本地转写安装失败"
      };
    }
    return { ok: true, payload };
  } catch (error) {
    return {
      ok: false,
      code: "NATIVE_HOST_NOT_INSTALLED",
      error: `一键安装本地转写需要先安装 Native Host。${error.message || String(error)}`
    };
  }
}

async function installEngineAutostart() {
  try {
    const payload = await sendNativeMessage({ type: "install-autostart" });
    if (!payload?.ok) {
      return {
        ok: false,
        code: "AUTOSTART_INSTALL_FAILED",
        error: payload?.error || "Engine 开机自启动安装失败"
      };
    }
    return { ok: true, payload };
  } catch (error) {
    return {
      ok: false,
      code: "NATIVE_HOST_NOT_INSTALLED",
      error: `一键安装开机自启动需要先安装 Native Host。${error.message || String(error)}`
    };
  }
}

function httpEngineSuccessPayload(health, extra = {}) {
  const payload = health?.payload || {};
  const compatibility = LocalTubeDubBackgroundHelpers.assessEngineCompatibility(
    payload,
    REQUIRED_ENGINE_PROTOCOL_VERSION,
    EXTENSION_VERSION
  );
  return {
    ok: true,
    payload: {
      ...payload,
      ...compatibility,
      ...extra,
      transport: "http"
    }
  };
}

function nativeEngineSuccessPayload(nativePayload, extra = {}) {
  const compatibility = LocalTubeDubBackgroundHelpers.assessEngineCompatibility(
    nativePayload,
    REQUIRED_ENGINE_PROTOCOL_VERSION,
    EXTENSION_VERSION
  );
  return {
    ok: true,
    payload: {
      ...(nativePayload || {}),
      ...compatibility,
      ...extra,
      transport: "native"
    }
  };
}

async function recoverHttpEngineAfterNativeError(endpoint, timeoutMs, extra = {}) {
  const health = await waitForHttpEngine(endpoint, timeoutMs);
  if (!health?.ok) {
    return null;
  }
  return httpEngineSuccessPayload(health, extra);
}

async function autoStartCaptionHttpEngine(endpoint, errors = [], timeoutMs = 10000) {
  if (captionEngineAutoStartCooldownUntil > Date.now()) {
    return null;
  }

  if (!captionEngineAutoStartInFlight) {
    captionEngineAutoStartInFlight = (async () => {
      try {
        const nativePayload = await sendNativeMessage({ type: "start-http" });
        if (!nativePayload?.ok) {
          errors.push(`Native 自动启动失败：${nativePayload?.error || "没有返回启动结果"}`);
        }
        const health = await waitForHttpEngine(endpoint, timeoutMs);
        if (health?.ok) {
          return httpEngineSuccessPayload(health, {
            autoStarted: true,
            endpoint,
            logPath: nativePayload?.logPath || ""
          });
        }
        captionEngineAutoStartCooldownUntil = Date.now() + 15000;
        return null;
      } catch (error) {
        errors.push(`Native 自动启动异常：${error.message || String(error)}`);
        const recovered = await recoverHttpEngineAfterNativeError(endpoint, timeoutMs, {
          autoStarted: true,
          recoveredAfterNativeExit: true,
          endpoint
        });
        if (recovered?.ok) {
          return recovered;
        }
        captionEngineAutoStartCooldownUntil = Date.now() + 15000;
        return null;
      } finally {
        captionEngineAutoStartInFlight = null;
      }
    })();
  }

  return captionEngineAutoStartInFlight;
}

async function waitForHttpEngine(endpoint, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const health = await fetchJson(`${endpoint}/api/health`, {
      method: "GET",
      timeoutMs: 1000,
      timeoutMessage: "Engine 健康检查超时"
    }).catch(() => null);
    if (health?.ok) {
      return health;
    }
    await delay(300);
  }
  return null;
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function transcribeTabAudio(payload = {}, settings = {}, tabId) {
  if (!tabId) {
    return { ok: false, error: "无法定位当前 YouTube 标签页" };
  }

  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const transcriptionProvider = getTranscriptionProvider(storedSettings.transcriptionProvider);

  const needsTranscriptionApiKey = transcriptionProvider.keyMode !== "none";
  const transcriptionApiKey = needsTranscriptionApiKey
    ? await getTranscriptionApiKey(storedSettings.transcriptionProvider)
    : "";
  if (needsTranscriptionApiKey && !transcriptionApiKey) {
    return {
      ok: false,
      code: "MISSING_TRANSCRIPTION_KEY",
      error: `无字幕视频需要先在扩展弹窗保存 ${transcriptionProvider.label} Key，用于音频转写。翻译 Provider 可继续使用 DeepSeek、Gemini 等。`
    };
  }

  const durationSeconds = clamp(Number(payload.durationSeconds || DEFAULT_TRANSCRIPTION_SECONDS), 6, 20);
  await ensureOffscreenDocument();
  const streamIdResult = payload.streamId ? { ok: true, streamId: payload.streamId } : await getTabAudioStreamId(tabId);
  if (!streamIdResult.ok) {
    return streamIdResult;
  }

  const { requestId, controller: abortController, signal } = transcriptionRequestRegistry.begin(
    payload.requestId || `tab:${tabId}:${Date.now()}`
  );

  try {
    throwIfAborted(signal, "转写已取消");
    const recording = await chrome.runtime.sendMessage({
      type: "localtube.offscreenRecordTabAudio",
      streamId: streamIdResult.streamId,
      durationMs: Math.round(durationSeconds * 1000)
    });

    throwIfAborted(signal, "转写已取消");

    if (!recording?.ok) {
      return {
        ok: false,
        error: recording?.error || "录制当前标签页音频失败"
      };
    }

    const startTime = Number(payload.startTime || 0);
    const transcript = await transcribeRecording(recording, {
      providerId: storedSettings.transcriptionProvider,
      provider: transcriptionProvider,
      model: resolveTranscriptionModel(storedSettings),
      apiKey: transcriptionApiKey,
      startTime,
      durationSeconds,
      language: storedSettings.sourceLanguage === "auto" ? "" : storedSettings.sourceLanguage || "",
      endpoint: storedSettings.endpoint,
      signal
    });

    return {
      ok: true,
      payload: {
        ok: true,
        engine: `${storedSettings.transcriptionProvider}:${resolveTranscriptionModel(storedSettings) || "default"}`,
        transport: "tab-audio",
        sourceLanguage: transcript.language || settings?.sourceLanguage || "auto",
        cues: transcript.cues
      }
    };
  } finally {
    transcriptionRequestRegistry.complete(requestId, abortController);
  }
}

async function transcribeCapturedAudio(payload = {}, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const transcriptionProvider = getTranscriptionProvider(storedSettings.transcriptionProvider);

  const needsTranscriptionApiKey = transcriptionProvider.keyMode !== "none";
  const transcriptionApiKey = needsTranscriptionApiKey
    ? await getTranscriptionApiKey(storedSettings.transcriptionProvider)
    : "";
  if (needsTranscriptionApiKey && !transcriptionApiKey) {
    return {
      ok: false,
      code: "MISSING_TRANSCRIPTION_KEY",
      error: `无字幕视频需要先在扩展弹窗保存 ${transcriptionProvider.label} Key，用于音频转写。翻译 Provider 可继续使用 DeepSeek、Gemini 等。`
    };
  }

  const dataUrl = String(payload.dataUrl || "");
  if (!/^data:(audio|video)\//.test(dataUrl)) {
    return { ok: false, code: "INVALID_RECORDING", error: "播放器录音数据为空或格式不支持。" };
  }

  const durationSeconds = clamp(Number(payload.durationSeconds || DEFAULT_TRANSCRIPTION_SECONDS), 6, 20);
  const { requestId, controller: abortController, signal } = transcriptionRequestRegistry.begin(
    payload.requestId || `captured:${Date.now()}`
  );

  try {
    throwIfAborted(signal, "转写已取消");
    const transcript = await transcribeRecording(
      {
        ok: true,
        dataUrl,
        mimeType: payload.mimeType || "audio/webm"
      },
      {
        providerId: storedSettings.transcriptionProvider,
        provider: transcriptionProvider,
        model: resolveTranscriptionModel(storedSettings),
        apiKey: transcriptionApiKey,
        startTime: Number(payload.startTime || 0),
        durationSeconds,
        language: storedSettings.sourceLanguage === "auto" ? "" : storedSettings.sourceLanguage || "",
        endpoint: storedSettings.endpoint,
        signal
      }
    );

    return {
      ok: true,
      payload: {
        ok: true,
        engine: `${storedSettings.transcriptionProvider}:${resolveTranscriptionModel(storedSettings) || "default"}`,
        transport: "video-element-audio",
        sourceLanguage: transcript.language || settings?.sourceLanguage || "auto",
        cues: transcript.cues
      }
    };
  } finally {
    transcriptionRequestRegistry.complete(requestId, abortController);
  }
}

async function transcribeVideoWindow(payload = {}, settings = {}) {
  const { requestId, controller, signal } = transcriptionRequestRegistry.begin(
    payload.requestId || `video-window:${Date.now()}`
  );
  try {
    return await transcribeVideoWindowRequest(payload, settings, signal);
  } finally {
    transcriptionRequestRegistry.complete(requestId, controller);
  }
}

async function startFullTranscript(payload = {}, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  if (storedSettings.transcriptionProvider !== "native") {
    return {
      ok: false,
      code: "LOCAL_FULL_TRANSCRIPT_NOT_SELECTED",
      error: "完整视频转写仅支持本地 Engine。"
    };
  }
  const durationSeconds = Number(payload.durationSeconds || 0);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    return { ok: false, code: "INVALID_VIDEO_DURATION", error: "当前视频时长不可用，无法准备完整字幕。" };
  }
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const response = await fetchJson(`${endpoint}/api/full-transcript/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      videoId: String(payload.videoId || ""),
      videoUrl: String(payload.videoUrl || ""),
      durationSeconds,
      language: storedSettings.sourceLanguage === "auto" ? "" : storedSettings.sourceLanguage || "",
      model: resolveTranscriptionModel(storedSettings)
    }),
    timeoutMs: 15000,
    timeoutMessage: "完整字幕任务启动超时"
  });
  if (!response.ok) {
    return { ok: false, code: response.payload?.code || "FULL_TRANSCRIPT_START_FAILED", error: response.error };
  }
  return { ok: true, payload: response.payload };
}

async function getFullTranscriptStatus(jobId, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const response = await fetchJson(`${endpoint}/api/full-transcript/status?id=${encodeURIComponent(String(jobId || ""))}`, {
    method: "GET",
    timeoutMs: 10000,
    timeoutMessage: "完整字幕进度查询超时"
  });
  if (!response.ok) {
    return { ok: false, code: response.payload?.code || "FULL_TRANSCRIPT_STATUS_FAILED", error: response.error };
  }
  return { ok: true, payload: response.payload };
}

async function cancelFullTranscript(jobId, settings = {}) {
  if (!jobId) {
    return { ok: true, payload: { cancelled: false } };
  }
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const response = await fetchJson(`${endpoint}/api/full-transcript/cancel`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jobId: String(jobId) }),
    timeoutMs: 10000,
    timeoutMessage: "完整字幕任务取消超时"
  });
  if (!response.ok && response.status !== 404) {
    return { ok: false, code: response.payload?.code || "FULL_TRANSCRIPT_CANCEL_FAILED", error: response.error };
  }
  return { ok: true, payload: response.payload || { cancelled: true } };
}

async function startDubTrack(payload = {}, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const cues = normalizeDubTrackCues(payload.cues);
  if (!cues.length) {
    return { ok: false, code: "INVALID_DUB_TRACK_CUES", error: "没有可导出的翻译字幕。" };
  }
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const response = await fetchJson(`${endpoint}/api/dub-track/start`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      videoId: String(payload.videoId || ""),
      durationSeconds: Number(payload.durationSeconds || 0),
      targetLanguage: storedSettings.targetLanguage,
      ttsEngine: storedSettings.ttsEngine,
      voiceId: storedSettings.voiceId || "auto",
      rate: storedSettings.voiceRate || 1,
      mixOriginal: payload.mixOriginal === true,
      originalVolume: clamp(Number(payload.originalVolume ?? storedSettings.originalVolume), 0, 1),
      videoUrl: String(payload.videoUrl || ""),
      outputFormat:
        payload.outputFormat === "wav" || payload.outputFormat === "m4a"
          ? payload.outputFormat
          : storedSettings.dubTrackFormat === "wav"
            ? "wav"
            : "m4a",
      cues
    }),
    timeoutMs: 20000,
    timeoutMessage: "配音音轨任务启动超时"
  });
  if (!response.ok) {
    return { ok: false, code: response.payload?.code || "DUB_TRACK_START_FAILED", error: response.error };
  }
  return { ok: true, payload: response.payload };
}

function normalizeDubTrackCues(rawCues) {
  return (Array.isArray(rawCues) ? rawCues : [])
    .map((cue) => {
      const text = String(cue?.translatedText || cue?.text || "").trim();
      const rawStart = Number(cue?.start || 0);
      const start = Number.isFinite(rawStart) ? Math.max(0, rawStart) : 0;
      const rawEnd = Number(cue?.end);
      const end = Number.isFinite(rawEnd) ? Math.max(start + 0.2, rawEnd) : start + 1.8;
      return { start, end, text };
    })
    .filter((cue) => cue.text)
    .sort((a, b) => a.start - b.start || a.end - b.end);
}

async function getDubTrackStatus(jobId, settings = {}) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const response = await fetchJson(`${endpoint}/api/dub-track/status?id=${encodeURIComponent(String(jobId || ""))}`, {
    method: "GET",
    timeoutMs: 10000,
    timeoutMessage: "配音音轨进度查询超时"
  });
  if (!response.ok) {
    return { ok: false, code: response.payload?.code || "DUB_TRACK_STATUS_FAILED", error: response.error };
  }
  return { ok: true, payload: response.payload };
}

async function cancelDubTrack(jobId, settings = {}) {
  if (!jobId) {
    return { ok: true, payload: { cancelled: false } };
  }
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const response = await fetchJson(`${endpoint}/api/dub-track/cancel`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jobId: String(jobId) }),
    timeoutMs: 10000,
    timeoutMessage: "配音音轨任务取消超时"
  });
  if (!response.ok && response.status !== 404) {
    return { ok: false, code: response.payload?.code || "DUB_TRACK_CANCEL_FAILED", error: response.error };
  }
  return { ok: true, payload: response.payload || { cancelled: true } };
}

async function transcribeVideoWindowRequest(payload = {}, settings = {}, signal) {
  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  if (storedSettings.transcriptionProvider !== "native") {
    return {
      ok: false,
      code: "LOCAL_VIDEO_TRANSCRIPTION_NOT_SELECTED",
      error: "视频音频窗口直取仅用于本地 Engine 转写。"
    };
  }

  const requestPayload = {
    videoId: String(payload.videoId || ""),
    videoUrl: String(payload.videoUrl || ""),
    startTime: Math.max(0, Number(payload.startTime || 0)),
    durationSeconds: clamp(Number(payload.durationSeconds || 30), 6, 90),
    language: storedSettings.sourceLanguage === "auto" ? "" : storedSettings.sourceLanguage || "",
    model: resolveTranscriptionModel(storedSettings)
  };
  const endpoint = String(storedSettings.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  const errors = [];
  let httpTerminalError = "";

  try {
    const response = await fetchJson(`${endpoint}/api/transcribe-video`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(requestPayload),
      timeoutMs: 90000,
      timeoutMessage: "本地视频窗口转写超时",
      signal,
      abortMessage: "视频窗口转写已取消"
    });
    const cues = normalizeCues(response.payload?.cues);
    if (response.ok) {
      return {
        ok: true,
        payload: {
          ...response.payload,
          cues,
          transport: response.payload?.transport || "http"
        }
      };
    }
    errors.push(`HTTP Engine：${response.error || "没有识别到语音"}`);
    if (response.status && response.status !== 404) {
      httpTerminalError = errors[errors.length - 1];
    }
  } catch (error) {
    errors.push(`HTTP Engine：${error.message || String(error)}`);
    if (/timeout|超时/i.test(error.message || String(error))) {
      httpTerminalError = errors[errors.length - 1];
    }
  }

  if (httpTerminalError) {
    return {
      ok: false,
      code: "LOCAL_VIDEO_TRANSCRIPTION_FAILED",
      error: httpTerminalError
    };
  }

  try {
    const nativePayload = await sendNativeMessageWithAbort(
      { type: "transcribe-video", payload: requestPayload },
      signal,
      "视频窗口转写已取消"
    );
    const cues = normalizeCues(nativePayload?.cues);
    if (nativePayload?.ok) {
      return {
        ok: true,
        payload: {
          ...nativePayload,
          cues,
          transport: nativePayload.transport || "native"
        }
      };
    }
    errors.push(`Native Engine：${nativePayload?.error || "没有识别到语音"}`);
  } catch (error) {
    errors.push(`Native Engine：${error.message || String(error)}`);
  }

  return {
    ok: false,
    code: "LOCAL_VIDEO_TRANSCRIPTION_FAILED",
    error: errors.join("；") || "本地视频窗口转写失败"
  };
}

async function prepareTabAudioCapture(payload = {}, settings = {}, tabId) {
  if (!tabId) {
    return { ok: false, error: "无法定位当前 YouTube 标签页" };
  }

  const storedSettings = sanitizeSettings({ ...(await getStoredSettings()), ...settings });
  const transcriptionProvider = getTranscriptionProvider(storedSettings.transcriptionProvider);

  const needsTranscriptionApiKey = transcriptionProvider.keyMode !== "none";
  const transcriptionApiKey = needsTranscriptionApiKey
    ? await getTranscriptionApiKey(storedSettings.transcriptionProvider)
    : "";
  if (needsTranscriptionApiKey && !transcriptionApiKey) {
    return {
      ok: false,
      code: "MISSING_TRANSCRIPTION_KEY",
      error: `无字幕视频需要先在扩展弹窗保存 ${transcriptionProvider.label} Key，用于音频转写。翻译 Provider 可继续使用 DeepSeek、Gemini 等。`
    };
  }

  try {
    await assertOptionalApiPermissions(optionalCapturePermissions(true));
  } catch (error) {
    return {
      ok: false,
      code: "TAB_CAPTURE_API_PERMISSION_REQUIRED",
      error: error.message || String(error)
    };
  }

  const durationSeconds = clamp(Number(payload.durationSeconds || DEFAULT_TRANSCRIPTION_SECONDS), 6, 20);
  await ensureOffscreenDocument();
  const streamIdResult = await getTabAudioStreamId(tabId);
  if (!streamIdResult.ok) {
    return streamIdResult;
  }

  return {
    ok: true,
    payload: {
      streamId: streamIdResult.streamId,
      durationSeconds
    }
  };
}

async function getTabAudioStreamId(tabId) {
  try {
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tabId });
    return { ok: true, streamId };
  } catch (error) {
    return normalizeTabCaptureError(error);
  }
}

function normalizeTabCaptureError(error) {
  const message = error?.message || String(error);
  if (/activeTab|has not been invoked|Chrome pages cannot be captured|Cannot capture/i.test(message)) {
    return {
      ok: false,
      code: "TAB_CAPTURE_PERMISSION_REQUIRED",
      error: "需要先授权当前视频页录音：请停留在这个 YouTube 视频页，点击浏览器右上角 LocalTube Dub 图标打开一次弹窗，然后回到视频页点“开始翻译”。Chrome 设置页、扩展页不能录音。"
    };
  }

  return {
    ok: false,
    code: "TAB_CAPTURE_FAILED",
    error: `录制当前标签页音频失败：${message}`
  };
}

async function ensureOffscreenDocument() {
  await assertOptionalApiPermissions(["offscreen"]);
  if (!chrome.offscreen) {
    throw new Error("当前 Chrome 不支持 offscreen 音频录制，请升级 Chrome 或使用本地 Engine。");
  }

  const offscreenUrl = chrome.runtime.getURL(OFFSCREEN_DOCUMENT_PATH);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [offscreenUrl]
  });

  if (contexts.length) {
    return;
  }

  if (!creatingOffscreenDocument) {
    creatingOffscreenDocument = chrome.offscreen
      .createDocument({
        url: OFFSCREEN_DOCUMENT_PATH,
        reasons: ["USER_MEDIA"],
        justification: "Record YouTube tab audio so videos without captions can be transcribed."
      })
      .finally(() => {
        creatingOffscreenDocument = null;
      });
  }

  await creatingOffscreenDocument;
}

async function cancelOffscreenRecording() {
  const offscreenUrl = chrome.runtime.getURL(OFFSCREEN_DOCUMENT_PATH);
  const contexts = chrome.runtime.getContexts
    ? await chrome.runtime.getContexts({
        contextTypes: ["OFFSCREEN_DOCUMENT"],
        documentUrls: [offscreenUrl]
      })
    : [];

  if (!contexts.length) {
    return { ok: true, cancelled: false };
  }

  const response = await chrome.runtime.sendMessage({ type: "localtube.offscreenCancelTabAudio" }).catch(() => null);
  return response || { ok: true, cancelled: false };
}

async function cancelTabAudioRecording(requestId) {
  const transcriptionCancelled = cancelTranscriptionRequest(requestId);
  const recordingResult = await cancelOffscreenRecording();
  return {
    ok: true,
    cancelled: Boolean(recordingResult.cancelled || transcriptionCancelled),
    recordingCancelled: Boolean(recordingResult.cancelled),
    transcriptionCancelled
  };
}

function cancelTranscriptionRequest(requestId) {
  return transcriptionRequestRegistry.cancel(requestId);
}

async function transcribeRecording(recording, options) {
  if (options.providerId === "native") {
    return transcribeRecordingWithNativeEngine(recording, options);
  }

  if (options.providerId === "deepgram") {
    return transcribeRecordingWithDeepgram(recording, options);
  }

  return transcribeRecordingWithOpenAICompatible(recording, options);
}

async function transcribeRecordingWithNativeEngine(recording, options) {
  throwIfAborted(options.signal, "转写已取消");
  const requestPayload = {
    dataUrl: recording.dataUrl,
    mimeType: recording.mimeType || "audio/webm",
    startTime: options.startTime,
    durationSeconds: options.durationSeconds,
    language: options.language || "",
    model: options.model || ""
  };
  const errors = [];
  const endpoint = String(options.endpoint || DEFAULT_SETTINGS.endpoint).replace(/\/+$/, "");
  let httpTerminalError = "";

  try {
    const response = await fetchJson(`${endpoint}/api/transcribe`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(requestPayload),
      timeoutMs: 75000,
      timeoutMessage: "本地 Engine 转写超时",
      signal: options.signal,
      abortMessage: "转写已取消"
    });
    throwIfAborted(options.signal, "转写已取消");
    const cues = normalizeCues(response.payload?.cues);
    if (response.ok && cues.length) {
      return {
        language: response.payload?.sourceLanguage || "",
        cues
      };
    }
    errors.push(`HTTP Engine：${response.error || "没有识别到语音"}`);
    if (response.status && response.status !== 404) {
      httpTerminalError = errors[errors.length - 1];
    }
  } catch (error) {
    throwIfAborted(options.signal, "转写已取消");
    errors.push(`HTTP Engine：${error.message || String(error)}`);
    if (/timeout|超时/i.test(error.message || String(error))) {
      httpTerminalError = errors[errors.length - 1];
    }
  }

  if (httpTerminalError) {
    throw new Error(httpTerminalError);
  }

  try {
    const payload = await sendNativeMessageWithAbort(
      { type: "transcribe", payload: requestPayload },
      options.signal,
      "转写已取消"
    );
    throwIfAborted(options.signal, "转写已取消");
    const cues = normalizeCues(payload?.cues);
    if (payload?.ok && cues.length) {
      return {
        language: payload.sourceLanguage || "",
        cues
      };
    }
    errors.push(`Native Engine：${payload?.error || "没有识别到语音"}`);
  } catch (error) {
    throwIfAborted(options.signal, "转写已取消");
    errors.push(`Native Engine：${error.message || String(error)}`);
  }

  throw new Error(errors.join("；") || "本地 Engine 没有从这段音频中识别到语音。");
}

function throwIfAborted(signal, message = "操作已取消") {
  if (signal?.aborted) {
    throw new Error(message);
  }
}

function sendNativeMessageWithAbort(message, signal, abortMessage = "操作已取消") {
  if (!signal) {
    return sendNativeMessage(message);
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (callback, value) => {
      if (settled) {
        return;
      }
      settled = true;
      signal.removeEventListener?.("abort", abort);
      callback(value);
    };
    const abort = () => settle(reject, new Error(abortMessage));

    if (signal.aborted) {
      abort();
      return;
    }

    signal.addEventListener?.("abort", abort, { once: true });
    sendNativeMessage(message)
      .then((payload) => settle(resolve, payload))
      .catch((error) => settle(reject, error));
  });
}

async function transcribeRecordingWithOpenAICompatible(recording, options) {
  const audioBlob = dataUrlToBlob(recording.dataUrl, recording.mimeType || "audio/webm");
  if (!audioBlob.size) {
    throw new Error("录音为空，请确认视频正在播放且当前标签页有声音。");
  }

  const formData = new FormData();
  formData.append("file", audioBlob, "youtube-audio.webm");
  formData.append("model", options.model);
  formData.append("response_format", "verbose_json");
  formData.append("timestamp_granularities[]", "segment");
  if (options.language && /^[a-z]{2}(-[A-Z]{2})?$/.test(options.language)) {
    formData.append("language", options.language.slice(0, 2));
  }

  await assertOptionalHostPermission(options.provider.endpoint);
  const response = await fetchWithTimeout(options.provider.endpoint, {
    method: "POST",
    headers: {
      authorization: `Bearer ${options.apiKey}`
    },
    body: formData,
    credentials: "omit",
    signal: options.signal
  }, 75000, `${options.provider.label} 转写请求超时`);

  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`OpenAI 转写返回了非 JSON 响应：${text.slice(0, 120)}`);
  }

  if (!response.ok) {
    throw new Error(readProviderError(payload) || `${options.provider.label} 转写返回 HTTP ${response.status}`);
  }

  const cues = transcriptionPayloadToCues(payload, options.startTime, options.durationSeconds);
  if (!cues.length) {
    throw new Error(`${options.provider.label} 没有从这段音频中识别到语音。`);
  }

  return {
    language: payload.language || "",
    cues
  };
}

async function transcribeRecordingWithDeepgram(recording, options) {
  const audioBlob = dataUrlToBlob(recording.dataUrl, recording.mimeType || "audio/webm");
  if (!audioBlob.size) {
    throw new Error("录音为空，请确认视频正在播放且当前标签页有声音。");
  }

  const endpoint = new URL(DEEPGRAM_TRANSCRIPTION_ENDPOINT);
  endpoint.searchParams.set("model", options.model);
  endpoint.searchParams.set("smart_format", "true");
  endpoint.searchParams.set("paragraphs", "true");
  endpoint.searchParams.set("utterances", "true");
  if (options.language && /^[a-z]{2}(-[A-Z]{2})?$/.test(options.language)) {
    endpoint.searchParams.set("language", options.language.slice(0, 2));
  }

  await assertOptionalHostPermission(endpoint.toString());
  const response = await fetchWithTimeout(endpoint.toString(), {
    method: "POST",
    headers: {
      authorization: `Token ${options.apiKey}`,
      "content-type": recording.mimeType || "audio/webm"
    },
    body: audioBlob,
    credentials: "omit",
    signal: options.signal
  }, 75000, "Deepgram 转写请求超时");

  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`Deepgram 转写返回了非 JSON 响应：${text.slice(0, 120)}`);
  }

  if (!response.ok) {
    throw new Error(readProviderError(payload) || `Deepgram 转写返回 HTTP ${response.status}`);
  }

  const cues = deepgramPayloadToCues(payload, options.startTime);
  if (!cues.length) {
    throw new Error("Deepgram 没有从这段音频中识别到语音。");
  }

  return {
    language: payload.metadata?.detected_language || "",
    cues
  };
}

function transcriptionPayloadToCues(payload, startTime, durationSeconds) {
  const baseTime = Number(startTime || 0);
  const segments = Array.isArray(payload.segments) ? payload.segments : [];
  const cues = segments
    .map((segment, index) => {
      const start = baseTime + Number(segment.start || 0);
      const end = baseTime + Number(segment.end || segment.start || 0);
      return {
        id: `asr-${index}`,
        start,
        end: Math.max(end, start + 0.8),
        text: cleanText(segment.text || "")
      };
    })
    .filter((cue) => cue.text);

  if (cues.length) {
    return cues;
  }

  return estimateCuesFromTranscript(payload.text || "", baseTime, durationSeconds);
}

function deepgramPayloadToCues(payload, startTime) {
  const baseTime = Number(startTime || 0);
  const alternative = payload.results?.channels?.[0]?.alternatives?.[0] || {};
  const sentences = (alternative.paragraphs?.paragraphs || []).flatMap((paragraph) => paragraph.sentences || []);
  const sentenceCues = sentences
    .map((sentence, index) => {
      const start = baseTime + Number(sentence.start || 0);
      const end = baseTime + Number(sentence.end || sentence.start || 0);
      return {
        id: `asr-${index}`,
        start,
        end: Math.max(end, start + 0.8),
        text: cleanText(sentence.text || "")
      };
    })
    .filter((cue) => cue.text);

  if (sentenceCues.length) {
    return sentenceCues;
  }

  const words = Array.isArray(alternative.words) ? alternative.words : [];
  const wordCues = [];
  let current = null;

  for (const word of words) {
    const text = cleanText(word.punctuated_word || word.word || "");
    if (!text) {
      continue;
    }

    const start = baseTime + Number(word.start || 0);
    const end = baseTime + Number(word.end || word.start || 0);
    if (!current) {
      current = { id: `asr-${wordCues.length}`, start, end, parts: [] };
    }

    current.parts.push(text);
    current.end = Math.max(current.end, end);

    const shouldFlush = /[.!?。！？]$/.test(text) || current.parts.length >= 14 || current.end - current.start >= 6;
    if (shouldFlush) {
      wordCues.push({
        id: current.id,
        start: current.start,
        end: Math.max(current.end, current.start + 0.8),
        text: cleanText(current.parts.join(" "))
      });
      current = null;
    }
  }

  if (current?.parts.length) {
    wordCues.push({
      id: current.id,
      start: current.start,
      end: Math.max(current.end, current.start + 0.8),
      text: cleanText(current.parts.join(" "))
    });
  }

  if (wordCues.length) {
    return wordCues;
  }

  return estimateCuesFromTranscript(alternative.transcript || "", baseTime, payload.metadata?.duration || 45);
}

function estimateCuesFromTranscript(text, startTime, durationSeconds) {
  const sentences = cleanText(text)
    .split(/(?<=[.!?。！？])\s+/)
    .map((part) => cleanText(part))
    .filter(Boolean);

  if (!sentences.length) {
    return [];
  }

  const cueDuration = Math.max(2, Number(durationSeconds || DEFAULT_TRANSCRIPTION_SECONDS) / sentences.length);
  return sentences.map((sentence, index) => ({
    id: `asr-${index}`,
    start: startTime + index * cueDuration,
    end: startTime + (index + 1) * cueDuration,
    text: sentence
  }));
}

function dataUrlToBlob(dataUrl, fallbackMimeType) {
  const [header, base64] = String(dataUrl || "").split(",");
  if (!base64) {
    return new Blob([], { type: fallbackMimeType });
  }

  const mimeMatch = header.match(/^data:([^;]+)/);
  const mimeType = mimeMatch?.[1] || fallbackMimeType;
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new Blob([bytes], { type: mimeType });
}

async function dubWithApiProvider(payload, settings, provider, options = {}) {
  const cues = normalizeCues(payload?.cues);
  if (!cues.length) {
    return { ok: false, error: "No caption cues supplied" };
  }

  const apiKey = await getApiKey(settings.provider);
  if (provider.requiresApiKey && !apiKey) {
    return { ok: false, code: "MISSING_API_KEY", error: `请先在扩展弹窗填写 ${provider.label} API Key` };
  }

  const model = resolveProviderModel(settings);
  const endpoint = resolveProviderEndpoint(settings);
  if (!endpoint) {
    return { ok: false, code: "MISSING_ENDPOINT", error: "请先填写 API Endpoint" };
  }

  const batches = makeCueBatches(cues);
  const translatedCues = [];

  try {
    for (const batch of batches) {
      throwIfAborted(options.signal, "翻译已取消");
      const translations = await translateApiBatchWithRecovery(batch, {
        providerId: settings.provider,
        provider,
        apiKey,
        endpoint,
        model,
        targetLanguage: payload.targetLanguage || settings.targetLanguage,
        sourceLanguage: payload.sourceLanguage || settings.sourceLanguage,
        signal: options.signal
      });
      throwIfAborted(options.signal, "翻译已取消");

      for (const [index, cue] of batch.entries()) {
        translatedCues.push({
          ...cue,
          translatedText: cleanText(translations[index] || cue.text)
        });
      }
    }
  } catch (error) {
    if (error?.name === "AbortError") {
      throw error;
    }
    const status = Number(error?.status || 0);
    const code = error?.code || LocalTubeDubBackgroundHelpers.classifyProviderFailure(status, error?.message || error);
    return {
      ok: false,
      code,
      status,
      error: LocalTubeDubBackgroundHelpers.providerFailureMessage(provider.label, code, status)
    };
  }

  return {
    ok: true,
    payload: {
      ok: true,
      engine: `${settings.provider}:${model || "default"}`,
      transport: "api",
      provider: settings.provider,
      model,
      warning: "",
      cues: translatedCues
    },
    healthCheck: Boolean(options.healthCheck)
  };
}

async function translateApiBatchWithRecovery(cues, context) {
  const translations = await translateBatchWithApiProvider(cues, context);
  const cleaned = Array.isArray(translations) ? translations.map(cleanText) : [];
  if (cleaned.length === cues.length && cleaned.every(Boolean)) {
    return cleaned;
  }

  if (cues.length <= 1) {
    throw new Error(`AI 返回 ${cleaned.length} 条有效翻译，但字幕批次有 ${cues.length} 条`);
  }

  const midpoint = Math.ceil(cues.length / 2);
  const left = await translateApiBatchWithRecovery(cues.slice(0, midpoint), context);
  const right = await translateApiBatchWithRecovery(cues.slice(midpoint), context);
  return [...left, ...right];
}

async function translateBatchWithApiProvider(cues, context) {
  if (context.provider.kind === "microsoft-translator") {
    return translateBatchWithMicrosoft(cues, context);
  }

  if (context.provider.kind === "google-translate") {
    return translateBatchWithGoogleTranslate(cues, context);
  }

  if (context.provider.kind === "gemini") {
    return translateBatchWithGemini(cues, context);
  }

  if (context.provider.kind === "anthropic") {
    return translateBatchWithAnthropic(cues, context);
  }

  return translateBatchWithOpenAICompatible(cues, context);
}

async function translateBatchWithMicrosoft(cues, context) {
  const targetLanguage = translationApiLanguage(context.targetLanguage, "microsoft");
  const sourceLanguage = translationApiLanguage(context.sourceLanguage, "microsoft");
  const endpoint = addUrlQuery(context.endpoint, {
    "api-version": "3.0",
    to: targetLanguage,
    ...(sourceLanguage ? { from: sourceLanguage } : {})
  });
  const region = String(context.model || "").trim();
  const response = await fetchProviderJson(endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "ocp-apim-subscription-key": context.apiKey,
      ...(region ? { "ocp-apim-subscription-region": region } : {})
    },
    body: JSON.stringify(cues.map((cue) => ({ Text: cue.text }))),
    signal: context.signal
  });

  return (Array.isArray(response) ? response : [])
    .map((item) => cleanText(item?.translations?.[0]?.text || ""))
    .slice(0, cues.length);
}

async function translateBatchWithGoogleTranslate(cues, context) {
  const endpoint = addUrlQuery(context.endpoint, { key: context.apiKey });
  const targetLanguage = translationApiLanguage(context.targetLanguage, "google");
  const sourceLanguage = translationApiLanguage(context.sourceLanguage, "google");
  const response = await fetchProviderJson(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      q: cues.map((cue) => cue.text),
      target: targetLanguage,
      format: "text",
      ...(sourceLanguage ? { source: sourceLanguage } : {})
    }),
    signal: context.signal
  });

  const translations = response?.data?.translations || [];
  return translations
    .map((item) => cleanText(decodeBasicHtmlEntities(item?.translatedText || "")))
    .slice(0, cues.length);
}

async function translateBatchWithOpenAICompatible(cues, context) {
  const response = await fetchProviderJson(context.endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      ...(context.apiKey ? { authorization: `Bearer ${context.apiKey}` } : {}),
      ...(context.providerId === "openrouter"
        ? {
            "http-referer": "https://localtube-dub.local",
            "x-title": "LocalTube Dub"
          }
        : {})
    },
    body: JSON.stringify({
      model: context.model,
      temperature: 0.15,
      messages: buildTranslationMessages(cues, context)
    }),
    signal: context.signal
  });

  const text = readOpenAICompatibleText(response);
  return parseTranslationArray(text, cues.length);
}

async function translateBatchWithAnthropic(cues, context) {
  const response = await fetchProviderJson(context.endpoint, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": context.apiKey,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: context.model,
      max_tokens: 2200,
      temperature: 0.15,
      system: buildSystemPrompt(context),
      messages: [{ role: "user", content: buildUserPrompt(cues) }]
    }),
    signal: context.signal
  });

  const text = (response.content || [])
    .map((part) => (part?.type === "text" ? part.text : ""))
    .join("")
    .trim();
  return parseTranslationArray(text, cues.length);
}

async function translateBatchWithGemini(cues, context) {
  const endpoint = `${context.endpoint.replace("{model}", encodeURIComponent(context.model))}?key=${encodeURIComponent(
    context.apiKey
  )}`;
  const response = await fetchProviderJson(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      contents: [
        {
          role: "user",
          parts: [{ text: `${buildSystemPrompt(context)}\n\n${buildUserPrompt(cues)}` }]
        }
      ],
      generationConfig: {
        temperature: 0.15,
        responseMimeType: "application/json"
      }
    }),
    signal: context.signal
  });

  const text = (response.candidates?.[0]?.content?.parts || [])
    .map((part) => part?.text || "")
    .join("")
    .trim();
  return parseTranslationArray(text, cues.length);
}

function buildTranslationMessages(cues, context) {
  return [
    { role: "system", content: buildSystemPrompt(context) },
    { role: "user", content: buildUserPrompt(cues) }
  ];
}

function buildSystemPrompt(context) {
  return [
    "You are a professional audiovisual subtitle translator.",
    `Translate each caption from ${context.sourceLanguage || "auto"} into ${languageName(context.targetLanguage)}.`,
    "Keep the same number of items and use natural spoken wording for dubbing.",
    "If a duration is provided, keep that item concise enough to be spoken comfortably within that many seconds.",
    "Do not add explanations, markdown, numbering, timestamps, or extra fields.",
    "Return only a valid JSON array of translated strings."
  ].join("\n");
}

function buildUserPrompt(cues) {
  return `Captions JSON:\n${JSON.stringify(
    cues.map((cue) => ({
      text: cue.text,
      seconds: Number.isFinite(Number(cue.end) - Number(cue.start))
        ? Math.max(0.5, Number((Number(cue.end) - Number(cue.start)).toFixed(2)))
        : undefined
    }))
  )}`;
}

function languageName(code) {
  const names = {
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "en-US": "English",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "es-ES": "Spanish",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
    "pt-BR": "Brazilian Portuguese",
    "ru-RU": "Russian",
    "ar-SA": "Arabic"
  };

  return names[code] || code || "the target language";
}

function translationApiLanguage(code, providerKind) {
  const normalized = String(code || "").trim();
  if (!normalized || normalized === "auto") {
    return "";
  }
  if (/^zh-CN$/i.test(normalized)) {
    return providerKind === "microsoft" ? "zh-Hans" : "zh-CN";
  }
  if (/^zh-TW$/i.test(normalized)) {
    return providerKind === "microsoft" ? "zh-Hant" : "zh-TW";
  }
  if (/^pt-BR$/i.test(normalized)) {
    return "pt";
  }
  return normalized.split(/[_-]/)[0] || normalized;
}

function addUrlQuery(url, params) {
  const next = new URL(url);
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && value !== "") {
      next.searchParams.set(key, value);
    }
  }
  return next.toString();
}

function decodeBasicHtmlEntities(value) {
  return String(value || "")
    .replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code)))
    .replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(parseInt(code, 16)))
    .replace(/&quot;/g, "\"")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function readOpenAICompatibleText(response) {
  const content = response.choices?.[0]?.message?.content || response.choices?.[0]?.text || "";
  if (Array.isArray(content)) {
    return content
      .map((part) => part?.text || part?.content || "")
      .join("")
      .trim();
  }
  return String(content || "").trim();
}

function parseTranslationArray(text, expectedLength) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    const match = String(text || "").match(/\[[\s\S]*\]/);
    if (!match) {
      throw new Error("AI 没有返回 JSON 字符串数组");
    }
    parsed = JSON.parse(match[0]);
  }

  if (!Array.isArray(parsed)) {
    throw new Error("AI 返回的结果不是 JSON 数组");
  }

  return parsed.map((item) => normalizeTranslationItem(item)).slice(0, expectedLength);
}

function normalizeTranslationItem(item) {
  if (item && typeof item === "object") {
    return cleanText(item.translatedText || item.translation || item.text || item.content || "");
  }
  return cleanText(item);
}

function resolveProviderModel(settings) {
  const provider = getProvider(settings.provider);
  return settings.model || provider.defaultModel || "";
}

function resolveTranscriptionModel(settings) {
  const provider = getTranscriptionProvider(settings.transcriptionProvider);
  return settings.transcriptionModel || provider.defaultModel || "";
}

function resolveProviderEndpoint(settings) {
  const provider = getProvider(settings.provider);

  if (provider.kind === "local-http") {
    return settings.endpoint || provider.endpoint;
  }

  if (settings.provider === "custom") {
    return settings.customEndpoint || "";
  }

  return provider.endpoint;
}

async function fetchProviderJson(url, request = {}) {
  assertProviderUrl(url);
  await assertOptionalHostPermission(url);
  const response = await fetchWithTimeout(url, {
    method: request.method || "POST",
    headers: request.headers || {},
    body: request.body || undefined,
    credentials: "omit",
    signal: request.signal,
    abortMessage: request.abortMessage || "翻译已取消"
  }, 90000, "AI 翻译请求超时");

  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    throw new Error(`AI 服务返回了非 JSON 响应：${text.slice(0, 120)}`);
  }

  if (!response.ok) {
    const providerMessage = readProviderError(payload) || `AI 服务返回 HTTP ${response.status}`;
    const error = new Error(providerMessage);
    error.status = response.status;
    error.code = LocalTubeDubBackgroundHelpers.classifyProviderFailure(response.status, providerMessage);
    throw error;
  }

  return payload;
}

function assertProviderUrl(url) {
  const parsed = new URL(url);
  if (!["https:", "http:"].includes(parsed.protocol)) {
    throw new Error("API Endpoint 必须是 http 或 https");
  }

  if (parsed.protocol === "http:" && !["localhost", "127.0.0.1"].includes(parsed.hostname)) {
    throw new Error("非本机 API Endpoint 必须使用 https");
  }
}

async function assertOptionalHostPermission(url) {
  const origin = optionalOriginForEndpoint(url);
  if (!origin || typeof chrome.permissions?.contains !== "function") {
    return;
  }
  const granted = await new Promise((resolve) => {
    chrome.permissions.contains({ origins: [origin] }, (result) => resolve(Boolean(result)));
  });
  if (!granted) {
    throw new Error(`请打开扩展弹窗，重新选择当前服务并授权访问 ${new URL(origin).host}`);
  }
}

async function assertOptionalApiPermissions(permissions) {
  const required = Array.from(new Set(Array.isArray(permissions) ? permissions.filter(Boolean) : []));
  if (!required.length || typeof chrome.permissions?.contains !== "function") {
    return;
  }
  const granted = await new Promise((resolve) => {
    chrome.permissions.contains({ permissions: required }, (result) => resolve(Boolean(result)));
  });
  if (!granted) {
    throw new Error("请打开扩展弹窗，开启“无字幕时自动转写”并允许标签页录音权限。");
  }
}

function readProviderError(payload) {
  if (typeof payload?.error === "string") {
    return payload.error;
  }
  if (typeof payload?.error?.message === "string") {
    return payload.error.message;
  }
  if (typeof payload?.message === "string") {
    return payload.message;
  }
  if (typeof payload?.err_msg === "string") {
    return payload.err_msg;
  }
  if (typeof payload?.reason === "string") {
    return payload.reason;
  }
  return "";
}

async function dubWithNativeEngine(payload, options = {}) {
  const cues = normalizeCues(payload?.cues);
  if (!cues.length) {
    return { ok: false, error: "No caption cues supplied" };
  }

  const batches = makeCueBatches(cues, 32, 8000);
  const mergedCues = [];
  let firstPayload = null;
  let warning = "";

  for (const batch of batches) {
    throwIfAborted(options.signal, "翻译已取消");
    const nativePayload = await sendNativeMessageWithAbort(
      {
        type: "dub",
        payload: { ...payload, cues: batch }
      },
      options.signal,
      "翻译已取消"
    );
    throwIfAborted(options.signal, "翻译已取消");

    if (!nativePayload?.ok) {
      return {
        ok: false,
        code: nativePayload?.code || "NATIVE_TRANSLATION_FAILED",
        error: nativePayload?.error || "LocalTube Dub Engine returned an error",
        payload: nativePayload
      };
    }

    firstPayload ||= nativePayload;
    warning ||= nativePayload.warning || "";
    mergedCues.push(...(nativePayload.cues || []));
  }

  return {
    ok: true,
    payload: {
      ...firstPayload,
      warning,
      cues: mergedCues,
      transport: "native"
    }
  };
}

function normalizeCues(rawCues) {
  if (!Array.isArray(rawCues)) {
    return [];
  }

  return rawCues
    .map((cue, index) => {
      const text = String(cue?.text || "").trim();
      const start = Number(cue?.start || 0);
      const end = Number(cue?.end || start + 1.8);
      return {
        id: String(cue?.id || index),
        start,
        end: Math.max(end, start + 0.8),
        text
      };
    })
    .filter((cue) => cue.text);
}

function makeCueBatches(cues, maxItems = 24, maxChars = 3200) {
  const batches = [];
  let batch = [];
  let charCount = 0;

  for (const cue of cues) {
    const nextChars = String(cue?.text || "").length;
    if (batch.length && (batch.length >= maxItems || charCount + nextChars > maxChars)) {
      batches.push(batch);
      batch = [];
      charCount = 0;
    }

    batch.push(cue);
    charCount += nextChars;
  }

  if (batch.length) {
    batches.push(batch);
  }

  return batches;
}

function cleanText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function sendNativeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(NATIVE_HOST_NAME, message, (response) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(response);
    });
  });
}

async function fetchJson(url, request = {}) {
  const response = await fetchForExtension({
    url,
    method: request.method || "GET",
    headers: request.headers || {},
    body: request.body || undefined,
    signal: request.signal,
    timeoutMs: request.timeoutMs,
    abortMessage: request.abortMessage,
    timeoutMessage: request.timeoutMessage
  });

  let payload = null;
  try {
    payload = response.text ? JSON.parse(response.text) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    return {
      ok: false,
      status: response.status,
      error: payload?.error || response.error || `HTTP ${response.status}`,
      payload,
      text: response.text
    };
  }

  try {
    payload = payload || JSON.parse(response.text);
    return {
      ok: payload.ok !== false,
      status: response.status,
      payload,
      error: payload.error || ""
    };
  } catch (error) {
    return {
      ok: false,
      status: response.status,
      error: `Invalid JSON response: ${error.message}`,
      text: response.text
    };
  }
}

async function fetchForExtension(request = {}) {
  const url = String(request.url || "");
  if (!ALLOWED_FETCH_URLS.some((pattern) => pattern.test(url))) {
    throw new Error(`Blocked extension request to ${url}`);
  }

  const response = await fetchWithTimeout(url, {
    method: request.method || "GET",
    headers: request.headers || {},
    body: request.body || undefined,
    credentials: request.credentials || "omit",
    signal: request.signal,
    abortMessage: request.abortMessage || "操作已取消"
  }, request.timeoutMs || 30000, request.timeoutMessage || "扩展网络请求超时");

  const text = await response.text();
  return {
    ok: response.ok,
    status: response.status,
    url: response.url,
    text
  };
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 60000, timeoutMessage = "网络请求超时") {
  const controller = new AbortController();
  const externalSignal = options.signal;
  const { signal, abortMessage = "转写已取消", ...fetchOptions } = options;
  const abortFromExternalSignal = () => controller.abort();
  if (externalSignal?.aborted) {
    controller.abort();
  } else if (externalSignal?.addEventListener) {
    externalSignal.addEventListener("abort", abortFromExternalSignal, { once: true });
  }
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, {
      ...fetchOptions,
      signal: controller.signal
    });
  } catch (error) {
    if (error?.name === "AbortError") {
      if (externalSignal?.aborted) {
        throw new Error(abortMessage);
      }
      throw new Error(timeoutMessage);
    }
    throw error;
  } finally {
    clearTimeout(timer);
    if (externalSignal?.removeEventListener) {
      externalSignal.removeEventListener("abort", abortFromExternalSignal);
    }
  }
}
