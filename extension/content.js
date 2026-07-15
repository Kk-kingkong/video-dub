const LANGUAGE_OPTIONS = [
  ["zh-CN", "中文（简体）"],
  ["zh-TW", "中文（繁体）"],
  ["en-US", "English"],
  ["ja-JP", "日本語"],
  ["ko-KR", "한국어"],
  ["es-ES", "Español"],
  ["fr-FR", "Français"],
  ["de-DE", "Deutsch"],
  ["it-IT", "Italiano"],
  ["pt-BR", "Português"],
  ["ru-RU", "Русский"],
  ["ar-SA", "العربية"]
];

const PROVIDER_OPTIONS = [
  ["openai", "OpenAI"],
  ["microsoft", "Microsoft Translator"],
  ["google-translate", "Google Translate"],
  ["chrome-translator", "Chrome 本地翻译（免费）"],
  ["gemini", "Gemini"],
  ["anthropic", "Claude"],
  ["deepseek", "DeepSeek"],
  ["openrouter", "OpenRouter"],
  ["custom", "自定义 API"],
  ["native", "Ollama（本地 Engine）"]
];

const VOICE_OPTIONS = [
  ["auto", "自动匹配"],
  ["Tingting", "中文女声 Tingting"],
  ["Meijia", "中文女声 Meijia"],
  ["Samantha", "英文女声 Samantha"],
  ["Alex", "英文男声 Alex"],
  ["Kyoko", "日文女声 Kyoko"],
  ["Yuna", "韩文女声 Yuna"]
];

const DEFAULT_SETTINGS = {
  enabled: true,
  setupMode: "byok",
  provider: "chrome-translator",
  endpoint: "http://127.0.0.1:8787",
  customEndpoint: "https://api.openai.com/v1/chat/completions",
  model: "",
  transcriptionProvider: "native",
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

const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const YOUTUBE_SOURCE_CACHE_PROVIDER = "youtube-source";
const { mergeVoiceOptions, selectVoiceOptions } = globalThis.LocalTubeDubVoiceHelpers;
const CAPTION_FAST_TIMEOUT_MS = 6000;
const CAPTION_TOTAL_TIMEOUT_MS = 23000;
const CAPTION_ENGINE_PAGE_FALLBACK_TIMEOUT_MS = 2000;
const CAPTION_FAILURE_BACKOFF_MS = {
  YOUTUBE_RATE_LIMITED: 5 * 60 * 1000,
  NO_PUBLIC_CAPTIONS: 60 * 1000,
  VIDEO_UNAVAILABLE: 60 * 1000
};
const VOICE_LEAD_SECONDS = 0.55;
const VOICE_FIRST_CUE_WAIT_MS = 1800;
const VOICE_PREFETCH_WINDOW_SECONDS = 18;
const VOICE_PREFETCH_MAX_SEGMENTS = 6;
const VOICE_AUDIO_MAX_CONCURRENCY = 3;
const VOICE_WARMUP_TTL_MS = 5 * 60 * 1000;
const VOICE_SEGMENT_MIN_SECONDS = 1.6;
const VOICE_SEGMENT_MAX_SECONDS = 5.2;
const VOICE_SEGMENT_MAX_GAP_SECONDS = 0.3;
const VOICE_SEGMENT_MAX_CUES = 4;
const VOICE_SEGMENT_MAX_CHARS = 96;
const VOICE_LATE_SKIP_SECONDS = 0.18;
const VOICE_LATE_START_SKIP_SECONDS = 0.8;
const VOICE_MIN_REMAINING_SECONDS = 0.45;
const VOICE_FIRST_SEGMENT_MIN_REMAINING_SECONDS = 0.22;
const VOICE_TIMEBOX_END_GRACE_SECONDS = 0.04;
const VOICE_TIMEBOX_SEEK_GRACE_SECONDS = 0.42;
const VOICE_TIMEBOX_SEEK_THRESHOLD_SECONDS = 0.55;
const VOICE_TIMEBOX_SILENCE_SLACK_SECONDS = 0.65;
const LOCAL_VIDEO_INITIAL_WINDOW_SECONDS = 30;
const LOCAL_VIDEO_ROLLING_WINDOW_SECONDS = 45;
const LOCAL_VIDEO_ROLLING_LEAD_SECONDS = 18;
const LOCAL_VIDEO_WINDOW_OVERLAP_SECONDS = 1.2;
const LOCAL_VIDEO_BUFFER_EDGE_SECONDS = 0.18;
const FULL_TRANSCRIPT_MAX_SECONDS = 7200;
const FULL_TRANSCRIPT_POLL_MS = 1500;

const {
  addQuery,
  buildSemanticVoiceSegments,
  captionEngineWaitTimeout,
  computeAudioMixState,
  computeFullTrackSync,
  computeLiveVoiceSync,
  computeVoiceRateBudget,
  computeVoiceSynthesisDuration,
  computeVoiceSyncTiming,
  createCueTranslationTracker,
  cueKey,
  extractBalancedJson,
  extendSemanticVoiceSegments,
  limitCaptionTrackAttempts,
  makeCaptionFetchCandidates,
  makeInnertubePlayerRequest,
  makePlaybackTranslationBatches,
  makeTimelineCacheLookupRequests,
  makeDubTrackRenderCues,
  mergeCueTimeline,
  normalizeCaptionLanguage,
  normalizeExportCues,
  normalizeRollingCaptionCues,
  parseCaptionPayload,
  pickCaptionTrack,
  responseMatchesVideo,
  resolveVoiceCaptionText,
  selectNewRollingCues,
  serializeSubtitleCues,
  syncFullTrackMediaElements
} = globalThis.LocalTubeDubHelpers;

const state = {
  settings: { ...DEFAULT_SETTINGS },
  providerOptions: [...PROVIDER_OPTIONS],
  root: null,
  caption: null,
  video: null,
  originalCues: [],
  detectedSourceLanguage: "auto",
  translatedCues: [],
  voiceSegments: [],
  availableVoices: [],
  pendingTranslationTracker: createCueTranslationTracker((cue) => hasTranslatedCue(cue)),
  activeCueIndex: -1,
  spokenCueIndex: -1,
  spokenVoiceSegmentKey: "",
  spokenVoiceSegmentKeys: new Set(),
  spokenVoiceTextWindows: new Map(),
  running: false,
  originalMuted: false,
  originalVolumeBeforeDubbing: 1,
  mutedByLocalTube: false,
  busy: false,
  operationId: 0,
  boundVideo: null,
  partialTranscription: false,
  transcriptionCoverageEnd: 0,
  rollingTranscriptionInFlight: false,
  rollingTranscriptionRetryAfter: 0,
  fullTranscriptJobId: "",
  fullTranscriptPreparing: false,
  fullTranscriptProgress: 0,
  dubTrackJobId: "",
  dubTrackRendering: false,
  dubTrackProgress: 0,
  dubTrackDownloadUrl: "",
  dubTrackFilename: "",
  dubTrackMixOriginal: false,
  dubTrackOutputFormat: "",
  dubTrackPreviewAudio: null,
  dubTrackPreviewActive: false,
  dubTrackPreviewPlayPromise: null,
  dubTrackPreviewOperationId: 0,
  videoBuffering: false,
  pausedForTranscriptionBuffer: false,
  skipTranslation: false,
  suppressSeeking: false,
  lastUrl: location.href,
  rafId: 0,
  statusPulseId: 0,
  captionRetryTimer: 0,
  captionRetryVideoId: "",
  captionRetryUntil: 0,
  phase: "idle",
  priorityTranslationOperationId: 0,
  activeTranscriptionRequestId: "",
  activeElementRecording: null,
  activeDubRequestIds: new Set(),
  pageSnapshotCache: null,
  captionFailureBackoff: new Map(),
  timelineCacheProvider: "",
  engineHealthTimer: 0,
  widgetVolumeSaveTimer: 0,
  speechActive: false,
  voiceAudioCache: new Map(),
  voiceAudioPending: new Map(),
  voiceAudioQueue: [],
  voiceAudioActiveCount: 0,
  activeVoiceAudio: null,
  activeVoiceCueKey: "",
  activeVoiceSegment: null,
  activeBrowserVoiceSegment: null,
  browserVoiceStartTimer: 0,
  voicePlaybackGeneration: 0,
  voicePendingCueKey: "",
  voiceSeekAlignmentUntil: 0,
  localTtsUnavailableUntil: 0,
  voiceWarmupKey: "",
  voiceWarmupAt: 0,
  voiceWarmupPromise: null,
  chromeTranslatorCache: new Map(),
  chromeLanguageDetectorPromise: null
};

boot();

async function boot() {
  state.settings = await loadSettings();
  installNavigationWatcher();
  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "localtube.settingsChanged") {
      state.settings = { ...state.settings, ...message.settings };
      if (!state.settings.enabled) {
        stopDubbing({ silent: true });
        unmountWidget();
        return;
      }
      mountWidget();
      updateControlsFromSettings();
      activateAudioControl();
      applyAudioMixSettings();
    }
  });
  if (state.settings.enabled) {
    mountWidget();
  }
}

async function loadSettings() {
  const response = await sendRuntimeMessage({ type: "localtube.getSettings" }).catch((error) => {
    if (isExtensionContextInvalidated(error)) {
      throw error;
    }
    return null;
  });
  updateProviderOptionsFromResponse(response);
  return { ...DEFAULT_SETTINGS, ...(response?.settings || {}) };
}

function isExtensionContextInvalidated(errorOrMessage) {
  const message = String(errorOrMessage?.message || errorOrMessage || "");
  return /Extension context invalidated|context invalidated|Extension context was invalidated/i.test(message);
}

function friendlyErrorMessage(errorOrMessage) {
  const message = String(errorOrMessage?.message || errorOrMessage || "");
  if (isExtensionContextInvalidated(message)) {
    return "扩展刚刚更新或重新加载了，请刷新当前 YouTube 页面后再开始翻译。";
  }
  return message || "操作失败";
}

async function sendRuntimeMessage(message) {
  try {
    return await chrome.runtime.sendMessage(message);
  } catch (error) {
    if (isExtensionContextInvalidated(error)) {
      throw new Error(friendlyErrorMessage(error));
    }
    throw error;
  }
}

function updateProviderOptionsFromResponse(response) {
  if (!Array.isArray(response?.providers) || !response.providers.length) {
    return;
  }

  state.providerOptions = response.providers
    .filter((provider) => provider?.id && provider?.label)
    .map((provider) => [provider.id, provider.label]);
}

function mountWidget() {
  if (state.root || !isWatchPage()) {
    return;
  }
  if (document.getElementById("localtube-dub-root")) {
    return;
  }

  const root = document.createElement("div");
  root.id = "localtube-dub-root";
  root.dataset.localtubeOwner = chrome.runtime.id;
  root.innerHTML = renderWidget();
  document.documentElement.append(root);
  state.root = root;

  state.caption = document.createElement("div");
  state.caption.className = "ltd-caption";
  attachCaptionOverlay();

  root.querySelector("[data-action='collapse']").addEventListener("click", () => root.classList.add("is-collapsed"));
  root.querySelector(".ltd-mini").addEventListener("click", () => root.classList.remove("is-collapsed"));
  root.querySelector("[data-action='start']").addEventListener("click", startDubbing);
  root.querySelector("[data-action='stop']").addEventListener("click", stopDubbing);
  root.querySelector("[data-action='engine-guide']").addEventListener("click", openEngineInstallGuide);
  root.querySelector("[data-action='engine-start']").addEventListener("click", startEngineFromWidget);
  root.querySelector("[data-action='engine-restart']").addEventListener("click", restartEngineFromWidget);
  root.querySelector("[data-action='export-subtitles']").addEventListener("click", exportCurrentSubtitles);
  root.querySelector("[data-action='prepare-full-transcript']").addEventListener("click", toggleFullTranscriptPreparation);
  root.querySelector("[data-action='export-dub-track']").addEventListener("click", handleDubTrackAction);
  root.querySelector("[data-action='preview-dub-track']").addEventListener("click", toggleDubTrackPreview);

  root.querySelector("[data-field='targetLanguage']").addEventListener("change", async () => {
    root.querySelector("[data-field='voiceId']").value = "auto";
    await saveSettingsFromWidget();
    renderAvailableVoiceOptions(state.settings.voiceId);
  });
  root.querySelector("[data-field='provider']").addEventListener("change", saveSettingsFromWidget);
  root.querySelector("[data-field='ttsEngine']").addEventListener("change", async () => {
    root.querySelector("[data-field='voiceId']").value = "auto";
    await saveSettingsFromWidget();
    await refreshAvailableVoiceOptions();
  });
  root.querySelector("[data-field='voiceEnabled']").addEventListener("change", saveSettingsFromWidget);
  root.querySelector("[data-field='muteOriginal']").addEventListener("change", saveSettingsFromWidget);
  root.querySelector("[data-field='voiceId']").addEventListener("change", saveSettingsFromWidget);
  root.querySelector("[data-field='dubTrackMode']").addEventListener("change", handleDubTrackModeChange);
  root.querySelector("[data-field='dubTrackFormat']").addEventListener("change", handleDubTrackModeChange);
  root.querySelector("[data-field='originalVolume']").addEventListener("input", handleWidgetVolumeInput);
  root.querySelector("[data-field='originalVolume']").addEventListener("change", saveSettingsFromWidget);
  updateControlsFromSettings();
  refreshAvailableVoiceOptions();
  window.speechSynthesis?.addEventListener?.("voiceschanged", refreshAvailableVoiceOptions, { once: true });
  refreshEngineStatus();
  startEngineStatusPolling();
  setWidgetPhase("idle");
}

function unmountWidget() {
  if (state.engineHealthTimer) {
    clearInterval(state.engineHealthTimer);
    state.engineHealthTimer = 0;
  }
  state.root?.remove();
  state.root = null;
  state.caption?.remove();
  state.caption = null;
}

function renderWidget() {
  const languageOptions = LANGUAGE_OPTIONS.map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  const providerOptions = (state.providerOptions || PROVIDER_OPTIONS)
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  const voiceOptions = VOICE_OPTIONS
    .map(([value, label]) => `<option value="${value}">${label}</option>`)
    .join("");
  const iconUrl = chrome.runtime.getURL("assets/icon-128.png");

  return `
    <section class="ltd-panel" aria-label="LocalTube Dub">
      <header class="ltd-head">
        <img class="ltd-logo" src="${iconUrl}" alt="">
        <div>
          <h2 class="ltd-title">LocalTube Dub <span>${EXTENSION_VERSION}</span></h2>
          <p class="ltd-subtitle">自带 AI Key 或本地模型翻译 YouTube。</p>
        </div>
        <button class="ltd-icon-button" data-action="collapse" title="收起">×</button>
      </header>
      <div class="ltd-body">
        <div class="ltd-row">
          <label class="ltd-field">
            <span>目标语言</span>
            <select data-field="targetLanguage">${languageOptions}</select>
          </label>
          <label class="ltd-field">
            <span>AI 提供商</span>
            <select data-field="provider">${providerOptions}</select>
          </label>
        </div>
        <div class="ltd-engine-hint" data-provider-label>API Key 和模型在扩展弹窗中配置。</div>
        <div class="ltd-engine-status is-checking" data-engine-status>
          <span class="ltd-engine-dot" aria-hidden="true"></span>
          <span data-engine-status-text>正在检查字幕 Engine...</span>
          <span class="ltd-engine-actions">
            <button type="button" data-action="engine-start">启动</button>
            <button type="button" data-action="engine-restart">重启</button>
            <button type="button" data-action="engine-guide">说明</button>
          </span>
        </div>
        <div class="ltd-checks">
          <label class="ltd-check">
            <input data-field="voiceEnabled" type="checkbox">
            <span>同步配音</span>
          </label>
          <label class="ltd-check">
            <input data-field="muteOriginal" type="checkbox">
            <span>静音原声</span>
          </label>
        </div>
        <div class="ltd-row ltd-voice-row">
          <label class="ltd-field">
            <span>配音引擎</span>
            <select data-field="ttsEngine">
              <option value="edge">Microsoft 自然在线（默认）</option>
              <option value="system">本地系统（快速）</option>
            </select>
          </label>
          <label class="ltd-field">
            <span>配音音色</span>
            <select data-field="voiceId">${voiceOptions}</select>
          </label>
        </div>
        <label class="ltd-volume">
          <span>原声大小 <b data-original-volume-label>25%</b></span>
          <input data-field="originalVolume" type="range" min="0" max="100" step="5">
        </label>
        <div class="ltd-export">
          <select data-field="exportFormat" aria-label="字幕导出格式">
            <option value="srt">SRT 字幕</option>
            <option value="vtt">WebVTT 字幕</option>
          </select>
          <button class="ltd-button" data-action="export-subtitles" type="button" disabled>导出字幕</button>
          <button class="ltd-button ltd-full-transcript" data-action="prepare-full-transcript" type="button" hidden>准备完整字幕</button>
          <select class="ltd-dub-track-mode" data-field="dubTrackMode" aria-label="音轨导出模式">
            <option value="voice-only">纯配音</option>
            <option value="mixed">配音 + 原声</option>
          </select>
          <select class="ltd-dub-track-format" data-field="dubTrackFormat" aria-label="音轨文件格式">
            <option value="m4a">M4A 小文件</option>
            <option value="wav">WAV 无损</option>
          </select>
          <button class="ltd-button ltd-dub-track" data-action="export-dub-track" type="button" disabled>生成配音音轨</button>
          <button class="ltd-button ltd-dub-track-preview" data-action="preview-dub-track" type="button" hidden>播放音轨</button>
        </div>
        <div class="ltd-actions">
          <button class="ltd-button primary" data-action="start" type="button">开始翻译</button>
          <button class="ltd-button" data-action="stop" type="button" disabled>停止</button>
          <span class="ltd-status" role="status">等待视频字幕</span>
        </div>
      </div>
    </section>
    <button class="ltd-mini" type="button">
      <img src="${iconUrl}" alt="">
      <span>LocalTube Dub</span>
    </button>
  `;
}

function updateControlsFromSettings() {
  if (!state.root) {
    return;
  }

  state.root.querySelector("[data-field='targetLanguage']").value = state.settings.targetLanguage;
  state.root.querySelector("[data-field='provider']").value = state.settings.provider || "chrome-translator";
  state.root.querySelector("[data-field='voiceEnabled']").checked = state.settings.voiceEnabled;
  state.root.querySelector("[data-field='muteOriginal']").checked = state.settings.muteOriginal;
  state.root.querySelector("[data-field='ttsEngine']").value = state.settings.ttsEngine === "edge" ? "edge" : "system";
  const voiceSelect = state.root.querySelector("[data-field='voiceId']");
  if (voiceSelect) {
    voiceSelect.value = selectHasOption(voiceSelect, state.settings.voiceId) ? state.settings.voiceId : "auto";
  }
  const volumeInput = state.root.querySelector("[data-field='originalVolume']");
  if (volumeInput) {
    volumeInput.value = String(Math.round(clampNumber(state.settings.originalVolume, 0, 1, DEFAULT_SETTINGS.originalVolume) * 100));
  }
  const dubTrackModeSelect = state.root.querySelector("[data-field='dubTrackMode']");
  if (dubTrackModeSelect) {
    dubTrackModeSelect.value = state.settings.dubTrackMode === "mixed" ? "mixed" : "voice-only";
  }
  const dubTrackFormatSelect = state.root.querySelector("[data-field='dubTrackFormat']");
  if (dubTrackFormatSelect) {
    dubTrackFormatSelect.value = state.settings.dubTrackFormat === "wav" ? "wav" : "m4a";
  }
  updateOriginalVolumeLabel();

  const providerLabel = state.root.querySelector("[data-provider-label]");
  if (providerLabel) {
    providerLabel.textContent = providerHint(state.settings.provider || "openai", state.settings);
  }
  refreshEngineStatus();
  updateWidgetState();
}

async function refreshAvailableVoiceOptions() {
  const response = await sendRuntimeMessage({
    type: "localtube.listVoices",
    settings: state.settings
  }).catch(() => null);
  const engineVoices = Array.isArray(response?.payload?.voices) ? response.payload.voices : [];
  const browserVoices = window.speechSynthesis?.getVoices?.() || [];
  const merged = mergeVoiceOptions(engineVoices, browserVoices);
  if (merged.length) {
    state.availableVoices = merged;
  }
  renderAvailableVoiceOptions(state.settings.voiceId || "auto");
}

function renderAvailableVoiceOptions(selectedVoice = "auto") {
  const select = state.root?.querySelector("[data-field='voiceId']");
  if (!select) {
    return;
  }
  const current = String(selectedVoice || "auto");
  const fallbackVoices = VOICE_OPTIONS.filter(([id]) => id !== "auto").map(([id, name]) => ({ id, name }));
  const voices = selectVoiceOptions(
    state.availableVoices,
    state.settings.targetLanguage,
    current,
    fallbackVoices,
    { provider: state.settings.ttsEngine || DEFAULT_SETTINGS.ttsEngine }
  );
  const options = [new Option("自动匹配（推荐）", "auto")];
  for (const voice of voices) {
    const locale = voice.language ? ` · ${voice.language}` : "";
    options.push(new Option(`${voice.name}${locale}`, voice.id));
  }
  if (!state.availableVoices.length) {
    for (const [id, label] of VOICE_OPTIONS) {
      if (id !== "auto" && !options.some((option) => option.value === id)) {
        options.push(new Option(label, id));
      }
    }
  }
  select.replaceChildren(...options);
  select.value = selectHasOption(select, current) ? current : "auto";
}

function startEngineStatusPolling() {
  if (state.engineHealthTimer) {
    clearInterval(state.engineHealthTimer);
  }
  state.engineHealthTimer = setInterval(refreshEngineStatus, 5000);
}

async function refreshEngineStatus() {
  if (!state.root) {
    return;
  }
  const node = state.root.querySelector("[data-engine-status]");
  const textNode = state.root.querySelector("[data-engine-status-text]");
  if (!node || !textNode) {
    return;
  }

  node.classList.remove("is-ok", "is-warn", "is-error");
  node.classList.add("is-checking");
  textNode.textContent = "正在检查字幕 Engine...";

  const response = await sendRuntimeMessage({
    type: "localtube.captionEngineHealth",
    settings: state.settings
  }).catch((error) => ({
    ok: false,
    error: friendlyErrorMessage(error)
  }));

  node.classList.remove("is-checking", "is-ok", "is-warn", "is-error");
  if (response?.ok) {
    const payload = response.payload || {};
    const transport = payload.transport === "native" ? "Native" : "HTTP";
    if (payload.upgradeRequired) {
      node.classList.add("is-error");
      textNode.textContent = `Engine 版本过旧（${payload.engineVersion || "未知"} / 协议 ${payload.protocolVersion || 0}），请安装与扩展 ${EXTENSION_VERSION} 匹配的 Engine`;
      return;
    }
    if (state.settings.ttsEngine === "edge" && !payload.edgeTts) {
      node.classList.add("is-warn");
      textNode.textContent = "自然在线语音尚未安装，请打开说明重新安装 Engine 依赖";
      return;
    }
    if (payload.ytDlp) {
      if (state.settings.allowAudioTranscription && state.settings.transcriptionProvider === "native" && !payload.whisper) {
        node.classList.add("is-warn");
        textNode.textContent = `字幕 Engine 已启动，但本地 Whisper 尚未安装`;
        return;
      }
      node.classList.add(payload.versionMismatch ? "is-warn" : "is-ok");
      textNode.textContent =
        payload.versionMismatch
          ? `Engine ${payload.engineVersion} 与扩展 ${EXTENSION_VERSION} 版本不同（协议兼容）`
          : state.settings.transcriptionProvider === "native" && payload.whisper
          ? `字幕 Engine 已启动（${transport} / yt-dlp + Whisper 就绪）`
          : `字幕 Engine 已启动（${transport} / yt-dlp 就绪）`;
      return;
    }
    node.classList.add("is-warn");
    textNode.textContent = `Engine 已启动，但还缺少 yt-dlp 依赖`;
    return;
  }

  node.classList.add("is-error");
  textNode.textContent = `字幕 Engine 未连接：${shortEngineError(response?.error)}`;
}

function shortEngineError(error) {
  const message = String(error || "");
  if (/timeout|超时/i.test(message)) {
    return "健康检查超时，请确认终端里的 Engine 没有卡住";
  }
  if (/Failed to fetch|ECONNREFUSED|fetch|Could not establish|Native host/i.test(message)) {
    return "请先按说明启动本地 Engine";
  }
  return message.slice(0, 56) || "请先按说明启动本地 Engine";
}

function openEngineInstallGuide() {
  sendRuntimeMessage({ type: "localtube.openInstallGuide" }).catch((error) => {
    setStatus(friendlyErrorMessage(error), "error");
  });
}

async function startEngineFromWidget() {
  setStatus("正在启动本地 Engine...", "working");
  const response = await sendRuntimeMessage({
    type: "localtube.startEngine",
    settings: state.settings
  }).catch((error) => ({
    ok: false,
    error: friendlyErrorMessage(error)
  }));

  if (!response?.ok) {
    setStatus(response?.error || "Engine 启动失败，请打开说明手动启动。", "error");
    return;
  }

  await refreshEngineStatus();
  await refreshAvailableVoiceOptions();
  setStatus(response.payload?.alreadyRunning ? "Engine 已经在运行" : "Engine 已启动", "");
}

async function restartEngineFromWidget() {
  setStatus("正在重启本地 Engine...", "working");
  const response = await sendRuntimeMessage({
    type: "localtube.restartEngine",
    settings: state.settings
  }).catch((error) => ({
    ok: false,
    error: friendlyErrorMessage(error)
  }));

  if (!response?.ok) {
    setStatus(response?.error || "Engine 重启失败，请打开说明手动重启。", "error");
    return;
  }

  setStatus("Engine 正在重启，稍后自动检查...", "working");
  await delay(1600);
  await refreshEngineStatus();
  await refreshAvailableVoiceOptions();
  setStatus("Engine 已重启", "");
}

async function saveSettingsFromWidget() {
  clearTimeout(state.widgetVolumeSaveTimer);
  const previousSettings = state.settings;
  const nextSettings = readSettingsFromWidget();
  const translationPipelineChanged =
    (state.running || state.busy) &&
    (previousSettings.targetLanguage !== nextSettings.targetLanguage || previousSettings.provider !== nextSettings.provider);
  const dubTrackSettingsChanged =
    previousSettings.ttsEngine !== nextSettings.ttsEngine ||
    previousSettings.voiceId !== nextSettings.voiceId ||
    previousSettings.dubTrackMode !== nextSettings.dubTrackMode ||
    previousSettings.dubTrackFormat !== nextSettings.dubTrackFormat;
  state.settings = nextSettings;
  if (translationPipelineChanged) {
    stopDubbing({ silent: true });
  } else if (dubTrackSettingsChanged && state.dubTrackRendering) {
    cancelDubTrackRendering();
  } else if (dubTrackSettingsChanged && state.dubTrackDownloadUrl) {
    resetDubTrackState();
  }
  updateOriginalVolumeLabel();
  activateAudioControl();
  applyAudioMixSettings();
  if (translationPipelineChanged) {
    setStatus("翻译语言或提供商已更改，请重新开始翻译。", "");
  }
  const response = await sendRuntimeMessage({ type: "localtube.setSettings", settings: state.settings }).catch((error) => {
    if (isExtensionContextInvalidated(error)) {
      setStatus(friendlyErrorMessage(error), "error");
    }
    return null;
  });
  updateProviderOptionsFromResponse(response);
  if (response?.settings) {
    state.settings = { ...state.settings, ...response.settings };
  }
  updateControlsFromSettings();
  activateAudioControl();
  applyAudioMixSettings();
}

function readSettingsFromWidget() {
  return {
    ...state.settings,
    targetLanguage: state.root.querySelector("[data-field='targetLanguage']").value,
    provider: state.root.querySelector("[data-field='provider']").value,
    voiceEnabled: state.root.querySelector("[data-field='voiceEnabled']").checked,
    muteOriginal: state.root.querySelector("[data-field='muteOriginal']").checked,
    ttsEngine: state.root.querySelector("[data-field='ttsEngine']")?.value === "edge" ? "edge" : "system",
    voiceId: state.root.querySelector("[data-field='voiceId']")?.value || "auto",
    originalVolume: Number(state.root.querySelector("[data-field='originalVolume']").value || 0) / 100,
    dubTrackMode: state.root.querySelector("[data-field='dubTrackMode']")?.value === "mixed" ? "mixed" : "voice-only",
    dubTrackFormat: state.root.querySelector("[data-field='dubTrackFormat']")?.value === "wav" ? "wav" : "m4a"
  };
}

function handleWidgetVolumeInput() {
  const previousVolume = state.settings.originalVolume;
  const nextSettings = readSettingsFromWidget();
  state.settings = nextSettings;
  if (
    nextSettings.dubTrackMode === "mixed" &&
    Math.abs(Number(previousVolume || 0) - Number(nextSettings.originalVolume || 0)) > 0.001
  ) {
    if (state.dubTrackRendering) {
      cancelDubTrackRendering();
    } else if (state.dubTrackDownloadUrl) {
      resetDubTrackState();
    }
  }
  updateOriginalVolumeLabel();
  activateAudioControl();
  applyAudioMixSettings();
  clearTimeout(state.widgetVolumeSaveTimer);
  state.widgetVolumeSaveTimer = setTimeout(() => {
    saveSettingsFromWidget();
  }, 140);
}

function handleDubTrackModeChange() {
  saveSettingsFromWidget();
}

function updateOriginalVolumeLabel() {
  const label = state.root?.querySelector("[data-original-volume-label]");
  if (label) {
    label.textContent = `${Math.round(clampNumber(state.settings.originalVolume, 0, 1, DEFAULT_SETTINGS.originalVolume) * 100)}%`;
  }
}

function selectHasOption(select, value) {
  return Array.from(select?.options || []).some((option) => option.value === value);
}

function applyAudioMixSettings() {
  refreshActiveVideoReference();
  const mix = computeAudioMixState(state.settings, {
    mutedByLocalTube: state.mutedByLocalTube,
    running: state.running,
    activeCueIndex: state.activeCueIndex,
    spokenCueIndex: state.spokenCueIndex
  });
  updateOriginalVolumeLabel();
  if (!state.video || !mix.shouldApply) {
    return;
  }
  if (state.dubTrackPreviewActive) {
    state.video.muted = state.dubTrackMixOriginal ? true : mix.muted;
    state.video.volume = mix.volume;
    return;
  }
  if (mix.shouldCancelSpeech) {
    invalidateVoicePlayback();
    stopActiveBrowserSpeech();
    stopActiveVoiceAudio();
    state.speechActive = false;
  }
  state.video.muted = mix.muted;
  state.video.volume = mix.volume;
  if (mix.shouldSpeakCurrentCue) {
    maybeSpeakVoiceSegment(findVoiceSegmentForPlayback(state.video.currentTime));
  }
}

function activateAudioControl() {
  refreshActiveVideoReference();
  if (!state.video || state.mutedByLocalTube) {
    return;
  }
  state.originalMuted = state.video.muted;
  state.originalVolumeBeforeDubbing = state.video.volume;
  state.mutedByLocalTube = true;
}

async function startDubbing(options = {}) {
  if (state.running || state.busy) {
    return;
  }

  const autoRetry = Boolean(options?.autoRetry);
  const resumeOnSuccess = Boolean(options?.resumeOnSuccess);
  cancelCaptionAutoRetry();
  const operationId = ++state.operationId;
  state.settings = readSettingsFromWidget();
  beginChromeTranslationWarmupFromUserGesture();
  state.busy = true;
  let pausedVideoForPreparation = false;
  let shouldResumeWhenReady = false;
  setWidgetPhase("preparing");
  setStatus("正在读取 YouTube 字幕...", "working");

  try {
    state.settings = await loadSettings();
    updateControlsFromSettings();
    assertOperationActive(operationId);

    state.video = getPrimaryVideoElement();
    if (!state.video) {
      throw new Error("当前页面没有找到视频播放器");
    }

    bindVideoEvents(state.video);
    shouldResumeWhenReady = resumeOnSuccess || !state.video.paused;
    if (shouldResumeWhenReady) {
      state.video.pause();
      pausedVideoForPreparation = true;
    }

    attachCaptionOverlay();
    const videoId = getCurrentVideoId();
    state.timelineCacheProvider = state.settings.provider;
    const cachedTimeline = await loadCachedTimeline(videoId, operationId, "youtube-captions");
    assertOperationActive(operationId);

    let originalCues = [];
    let translatedCues = [];
    let usedAudioTranscription = false;
    let detectedSourceLanguage = "auto";
    let targetCaptionsReady = false;
    let translationBatches = [];
    let cacheHit = false;

    if (cachedTimeline?.cues?.length) {
      cacheHit = true;
      state.timelineCacheProvider = cachedTimeline.provider || state.settings.provider;
      translatedCues = normalizeRollingCaptionCues(cachedTimeline.cues);
      originalCues = translatedCues.map(({ translatedText, ...cue }) => cue);
      detectedSourceLanguage = cachedTimeline.sourceLanguage || "auto";
      setStatus(`已从本机缓存读取 ${translatedCues.length} 条字幕`, "");
    } else {
      beginVoiceEngineWarmup(operationId);
      const providerCachedTimeline = await loadCachedTimeline(videoId, operationId, state.settings.provider);
      assertOperationActive(operationId);

      if (providerCachedTimeline?.cues?.length) {
        cacheHit = true;
        state.timelineCacheProvider = providerCachedTimeline.provider || state.settings.provider;
        translatedCues = normalizeRollingCaptionCues(providerCachedTimeline.cues);
        originalCues = translatedCues.map(({ translatedText, ...cue }) => cue);
        detectedSourceLanguage = providerCachedTimeline.sourceLanguage || "auto";
        setStatus(`已从本机缓存读取 ${translatedCues.length} 条字幕`, "");
      } else {
        const sourceCachedTimeline = await loadCachedTimeline(videoId, operationId, "youtube-source");
        assertOperationActive(operationId);
        if (sourceCachedTimeline?.cues?.length) {
          originalCues = restoreSourceCaptionCache(sourceCachedTimeline);
          detectedSourceLanguage = sourceCachedTimeline.sourceLanguage || "auto";
          state.timelineCacheProvider = state.settings.provider;
          setStatus(`已从本机缓存读取 ${originalCues.length} 条原字幕`, "");
        }

        if (!originalCues.length) {
          const captionResult = await resolveVideoCaptions(operationId);
          assertOperationActive(operationId);

          originalCues = normalizeRollingCaptionCues(captionResult.cues || []);
          if (!originalCues.length && captionResult.status === "no_captions") {
            if (!state.settings.allowAudioTranscription) {
              throw new Error("已确认这个视频没有可读取的 YouTube 字幕。需要翻译无字幕视频时，请在扩展弹窗开启“无字幕时自动转写”。");
            }
            usedAudioTranscription = true;
            originalCues = await transcribeCurrentAudioWindow(operationId);
          }

          assertOperationActive(operationId);
          if (!originalCues.length) {
            const captionError = new Error(captionResult.error || "没有读取到可翻译的 YouTube 字幕。");
            captionError.code = captionResult.code || classifyCaptionErrorCode(captionResult.error);
            captionError.retryAfterSeconds = Number(captionResult.retryAfterSeconds || 0) || 0;
            throw captionError;
          }

          detectedSourceLanguage = usedAudioTranscription
            ? state.detectedSourceLanguage || "auto"
            : captionResult.track?.languageCode || "auto";
          targetCaptionsReady = isTargetLanguageTrack(captionResult.track, state.settings.targetLanguage);
          state.timelineCacheProvider = targetCaptionsReady ? "youtube-captions" : state.settings.provider;
          if (!usedAudioTranscription && !targetCaptionsReady) {
            await saveSourceCaptionCache(videoId, operationId, originalCues, detectedSourceLanguage).catch(() => false);
            assertOperationActive(operationId);
          }
        }

        translationBatches = makePlaybackTranslationBatches(originalCues, state.video.currentTime, {
          firstBatchSize: usedAudioTranscription ? 12 : 10,
          batchSize: 12
        });
        const firstBatch = translationBatches.shift() || originalCues.slice(0, 12);

        if (targetCaptionsReady) {
          translatedCues = originalCues.map(useCueTextAsTranslation);
          translationBatches = [];
          setStatus("已读取目标语言字幕，直接同步配音", "");
        } else {
          setWidgetPhase("translating");
          setStatus(`正在使用 ${providerName(state.settings.provider)} 翻译当前片段...`, "working");
          translatedCues = await translateCues(firstBatch, detectedSourceLanguage);
        }
      }
    }

    assertOperationActive(operationId);
    state.originalCues = originalCues;
    state.detectedSourceLanguage = detectedSourceLanguage;
    state.translatedCues = mergeTranslatedCues([], translatedCues);
    refreshVoiceSegments();
    state.activeCueIndex = -1;
    state.spokenCueIndex = -1;
    state.spokenVoiceSegmentKey = "";
    state.spokenVoiceSegmentKeys.clear();
    state.spokenVoiceTextWindows.clear();
    state.running = true;
    state.busy = false;
    state.partialTranscription = usedAudioTranscription;
    state.skipTranslation = targetCaptionsReady || cacheHit;
    setWidgetPhase(translationBatches.length ? "caching" : "running");

    activateAudioControl();
    applyAudioMixSettings();
    if (state.settings.voiceEnabled) {
      setStatus("正在预热首段配音...", "working");
      await prewarmVoiceAroundTime(state.video.currentTime, operationId);
      assertOperationActive(operationId);
    }

    setStatus(cacheHit
      ? `已从本机缓存同步 ${state.translatedCues.length} 条字幕`
      : translationBatches.length
        ? `已同步首段 ${state.translatedCues.length}/${originalCues.length} 条，继续后台翻译`
        : `已同步 ${state.translatedCues.length} 条字幕`, "");
    runSyncLoop();
    if (shouldResumeWhenReady) {
      await state.video.play().catch(() => {});
    }
    translateQueuedCues(operationId, translationBatches, detectedSourceLanguage, originalCues.length, {
      skipTranslation: targetCaptionsReady || cacheHit,
      cacheWhenComplete: !cacheHit && !usedAudioTranscription
    }).catch((error) => {
      if (error?.name !== "OperationStaleError" && state.operationId === operationId && state.running) {
        setStatus(`后续字幕翻译失败：${error.message || String(error)}`, "error");
      }
    });
    if (!cacheHit && !usedAudioTranscription && !translationBatches.length) {
      saveTimelineCacheIfComplete(operationId).catch(() => {});
    }
  } catch (error) {
    if (error?.name === "OperationStaleError" || state.operationId !== operationId) {
      return;
    }

    const isRateLimited = error?.code === "YOUTUBE_RATE_LIMITED";
    const message = isRateLimited && autoRetry
      ? "YouTube 字幕服务仍在繁忙，本次自动重试已停止。请稍后再点开始翻译。"
      : friendlyErrorMessage(error);
    const pauseHint = !isRateLimited && pausedVideoForPreparation && state.video?.paused
      ? " 视频已暂停，可修复设置后重试。"
      : "";
    setStatus(`${message}${pauseHint}`, "error");
    const retryRequest = isRateLimited && !autoRetry
      ? {
        videoId: getCurrentVideoId(),
        retryAfterSeconds: Number(error?.retryAfterSeconds || 0) || 0,
        resumeOnSuccess: shouldResumeWhenReady
      }
      : null;
    stopDubbing({ silent: true });
    await resumeVideoAfterCaptionDelay(isRateLimited && shouldResumeWhenReady);
    if (retryRequest?.videoId) {
      scheduleCaptionAutoRetry(retryRequest.videoId, retryRequest.retryAfterSeconds, retryRequest.resumeOnSuccess);
    }
  } finally {
    if (state.operationId === operationId) {
      state.busy = false;
      updateWidgetState();
    }
  }
}

async function transcribeCurrentAudioWindow(operationId) {
  if (!state.settings.allowAudioTranscription) {
    throw new Error(
      "未检测到 YouTube 字幕。为避免消耗转写额度，已停止；如果确认这个视频没有字幕，请在扩展弹窗开启“无字幕时自动转写”。"
    );
  }

  if (!state.settings.hasTranscriptionApiKey) {
    throw new Error(
      `无字幕视频需要先在扩展弹窗保存 ${state.settings.transcriptionProviderLabel || "转写服务"} Key，再回到视频页开始翻译。`
    );
  }

  const startTime = state.video.currentTime;
  const remainingSeconds = Number.isFinite(state.video.duration) ? Math.max(6, state.video.duration - startTime) : 12;
  const configuredSeconds = Number(state.settings.transcriptionWindowSeconds || 12);
  const durationSeconds = Math.min(clampNumber(configuredSeconds, 6, 12, 12), remainingSeconds);
  state.transcriptionCoverageEnd = startTime;

  if (state.settings.transcriptionProvider === "native") {
    const directDuration = Math.min(LOCAL_VIDEO_INITIAL_WINDOW_SECONDS, remainingSeconds);
    try {
      setWidgetPhase("transcribing");
      startStatusPulse((elapsedSeconds) => `正在用本地 Engine 准备首段配音字幕 ${elapsedSeconds} 秒...`, "working");
      const directWindow = await transcribeVideoWindowFromEngine(operationId, startTime, directDuration);
      if (!directWindow.cues.length) {
        throw new Error("首个视频音频窗口没有识别到人声");
      }
      state.detectedSourceLanguage = directWindow.sourceLanguage || state.detectedSourceLanguage || "auto";
      state.transcriptionCoverageEnd = directWindow.windowEnd;
      setStatus(`已提前转写 ${Math.round(directWindow.windowEnd - directWindow.windowStart)} 秒视频音频`, "working");
      return directWindow.cues;
    } catch (error) {
      assertOperationActive(operationId);
      setStatus(`Engine 音频直取暂不可用，改用播放器录音：${friendlyErrorMessage(error)}`, "working");
    } finally {
      clearStatusPulse();
    }
  }

  const requestId = `tab-audio-${operationId}-${Date.now()}`;
  state.activeTranscriptionRequestId = requestId;

  try {
    const localRecording = await recordVideoElementAudio(durationSeconds, operationId, startTime, requestId);
    assertOperationActive(operationId);
    if (localRecording?.ok) {
      const cues = await transcribeCapturedRecording(localRecording, requestId, startTime, durationSeconds, operationId);
      state.transcriptionCoverageEnd = startTime + durationSeconds;
      return cues;
    }

    setStatus(
      localRecording?.error
        ? `页面录音不可用：${localRecording.error}，改用标签页录音...`
        : "页面录音不可用，改用标签页录音...",
      "working"
    );
    const cues = await transcribeWithTabAudioFallback(requestId, startTime, durationSeconds, operationId);
    state.transcriptionCoverageEnd = startTime + durationSeconds;
    return cues;
  } finally {
    if (state.activeTranscriptionRequestId === requestId) {
      state.activeTranscriptionRequestId = "";
    }
  }
}

async function transcribeVideoWindowFromEngine(operationId, startTime, durationSeconds) {
  const requestId = `video-window-${operationId}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  state.activeTranscriptionRequestId = requestId;
  try {
    const response = await sendRuntimeMessageWithTimeout(
      {
        type: "localtube.transcribeVideoWindow",
        settings: state.settings,
        payload: {
          videoId: getCurrentVideoId(),
          videoUrl: location.href,
          startTime,
          durationSeconds,
          requestId
        }
      },
      95000,
      "本地 Engine 视频窗口转写超时"
    ).catch(async (error) => {
      await cancelTabAudioRecording(requestId);
      return { ok: false, error: friendlyErrorMessage(error) };
    });
    assertOperationActive(operationId);
    if (!response?.ok) {
      throw new Error(response?.error || "本地 Engine 视频窗口转写失败");
    }
    const cues = normalizeResolvedCues(response.payload?.cues);
    return {
      cues,
      sourceLanguage: response.payload?.sourceLanguage || "auto",
      windowStart: Number(response.payload?.windowStart ?? startTime),
      windowEnd: Number(response.payload?.windowEnd ?? startTime + durationSeconds)
    };
  } finally {
    if (state.activeTranscriptionRequestId === requestId) {
      state.activeTranscriptionRequestId = "";
    }
  }
}

async function recordVideoElementAudio(durationSeconds, operationId, startTime, requestId) {
  const streamResult = captureVideoElementAudioStream();
  if (!streamResult.ok) {
    return streamResult;
  }

  setWidgetPhase("recording");
  startStatusPulse(
    (elapsedSeconds) =>
      `视频没有字幕，需要短暂播放录音；正在从播放器录制 ${Math.min(elapsedSeconds, Math.round(durationSeconds))}/${Math.round(
        durationSeconds
      )} 秒，录完会回到原进度并暂停...`,
    "working"
  );

  try {
    await state.video.play().catch(() => {
      throw new Error("需要先播放视频，才能录制当前播放器音频。");
    });
    assertOperationActive(operationId);
    const recording = await collectVideoElementRecording(streamResult.stream, Math.round(durationSeconds * 1000), requestId);
    assertOperationActive(operationId);
    return { ok: true, ...recording };
  } catch (error) {
    if (error?.name === "OperationStaleError") {
      throw error;
    }
    return { ok: false, error: error.message || String(error) };
  } finally {
    clearStatusPulse();
    if (state.operationId === operationId) {
      restoreVideoTime(startTime);
    }
    cleanupCapturedStream(streamResult.stream);
  }
}

function captureVideoElementAudioStream() {
  const video = state.video;
  const captureStream = video?.captureStream || video?.mozCaptureStream;
  if (!video || typeof captureStream !== "function") {
    return { ok: false, error: "当前浏览器不支持从播放器直接录音" };
  }

  let capturedStream;
  try {
    capturedStream = captureStream.call(video);
  } catch (error) {
    return { ok: false, error: error.message || String(error) };
  }

  const audioTracks = capturedStream.getAudioTracks();
  if (!audioTracks.length) {
    cleanupCapturedStream(capturedStream);
    return { ok: false, error: "当前播放器没有可录的音频轨道" };
  }

  capturedStream.getVideoTracks().forEach((track) => track.stop());
  return { ok: true, stream: new MediaStream(audioTracks) };
}

function collectVideoElementRecording(stream, durationMs, requestId) {
  return new Promise((resolve, reject) => {
    const mimeType = pickRecordingMimeType();
    let recorder;
    try {
      recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    } catch (error) {
      reject(new Error(`无法启动播放器录音：${error.message || String(error)}`));
      return;
    }

    const chunks = [];
    const active = {
      requestId,
      recorder,
      stream,
      timer: 0,
      cancelled: false
    };
    state.activeElementRecording = active;
    let settled = false;

    const clearActive = () => {
      clearTimeout(active.timer);
      if (state.activeElementRecording === active) {
        state.activeElementRecording = null;
      }
    };

    const settle = (callback, value) => {
      if (settled) {
        return;
      }
      settled = true;
      clearActive();
      callback(value);
    };

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) {
        chunks.push(event.data);
      }
    });

    recorder.addEventListener("error", () => settle(reject, new Error("播放器录音失败")), { once: true });
    recorder.addEventListener(
      "stop",
      () => {
        if (active.cancelled) {
          settle(reject, new Error("录音已取消"));
          return;
        }
        if (!chunks.length) {
          settle(reject, new Error("播放器录音为空"));
          return;
        }

        const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || "audio/webm" });
        blobToDataUrl(blob)
          .then((dataUrl) => settle(resolve, { dataUrl, mimeType: blob.type || "audio/webm", durationMs }))
          .catch((error) => settle(reject, error));
      },
      { once: true }
    );

    try {
      recorder.start(1000);
      active.timer = setTimeout(() => stopMediaRecorder(recorder), durationMs);
    } catch (error) {
      settle(reject, new Error(`无法开始播放器录音：${error.message || String(error)}`));
    }
  });
}

function pickRecordingMimeType() {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "video/webm;codecs=opus", "video/webm"];
  return candidates.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || "";
}

function stopMediaRecorder(recorder) {
  if (recorder?.state && recorder.state !== "inactive") {
    recorder.stop();
  }
}

function cleanupCapturedStream(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

function cancelElementAudioRecording(requestId) {
  const active = state.activeElementRecording;
  if (!active || (requestId && active.requestId !== requestId)) {
    return false;
  }

  active.cancelled = true;
  clearTimeout(active.timer);
  cleanupCapturedStream(active.stream);
  stopMediaRecorder(active.recorder);
  if (!active.recorder?.state || active.recorder.state === "inactive") {
    state.activeElementRecording = null;
  }
  return true;
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("无法读取播放器录音"));
    reader.readAsDataURL(blob);
  });
}

async function transcribeCapturedRecording(recording, requestId, startTime, durationSeconds, operationId) {
  setWidgetPhase("transcribing");
  startStatusPulse((elapsedSeconds) => `已录制 ${Math.round(durationSeconds)} 秒，正在转写音频 ${elapsedSeconds} 秒...`, "working");
  const response = await sendRuntimeMessageWithTimeout(
    {
      type: "localtube.transcribeCapturedAudio",
      settings: state.settings,
      payload: {
        videoUrl: location.href,
        startTime,
        durationSeconds,
        dataUrl: recording.dataUrl,
        mimeType: recording.mimeType,
        requestId
      }
    },
    70000,
    "音频转写超时：请检查本地 Engine 或转写服务，或换一个有 YouTube 字幕的视频。"
  ).catch(async (error) => {
    if (isExtensionContextInvalidated(error)) {
      throw error;
    }
    await cancelTabAudioRecording(requestId);
    return { ok: false, error: friendlyErrorMessage(error) };
  });
  clearStatusPulse();
  assertOperationActive(operationId);

  if (!response?.ok) {
    throw new Error(response?.error || "音频转写失败");
  }

  const cues = normalizeTranscriptionCues(response.payload?.cues);
  state.detectedSourceLanguage = response.payload?.sourceLanguage || state.detectedSourceLanguage || "auto";
  setStatus(`已从音频转写 ${cues.length} 条字幕，正在翻译...`, "working");
  return cues;
}

async function transcribeWithTabAudioFallback(requestId, startTime, durationSeconds, operationId) {
  let pauseAfterRecordingTimer = 0;

  setWidgetPhase("recording");
  setStatus("正在准备当前标签页录音权限...", "working");
  const preparedCapture = await prepareTabAudioCapture(durationSeconds);
  assertOperationActive(operationId);

  await state.video.play().catch(() => {
    throw new Error("需要先播放视频，才能录制当前标签页音频。");
  });
  assertOperationActive(operationId);
  startStatusPulse(
    (elapsedSeconds) =>
      `视频没有字幕，需要短暂播放录音；正在录制标签页音频 ${Math.min(elapsedSeconds, Math.round(durationSeconds))}/${Math.round(
        durationSeconds
      )} 秒，录完会回到原进度并暂停...`,
    "working"
  );
  pauseAfterRecordingTimer = setTimeout(() => {
    if (state.operationId !== operationId || !state.video) {
      return;
    }
    restoreVideoTime(startTime);
    setWidgetPhase("transcribing");
    startStatusPulse(
      (elapsedSeconds) => `已录制 ${Math.round(durationSeconds)} 秒，正在转写音频 ${elapsedSeconds} 秒...`,
      "working"
    );
  }, Math.round(durationSeconds * 1000) + 350);

  const response = await sendRuntimeMessageWithTimeout(
    {
      type: "localtube.transcribeTabAudio",
      settings: state.settings,
      payload: {
        videoUrl: location.href,
        startTime,
        durationSeconds,
        streamId: preparedCapture.streamId,
        requestId
      }
    },
    Math.round(durationSeconds * 1000) + 70000,
    "音频转写超时：请检查本地 Engine 或转写服务，或换一个有 YouTube 字幕的视频。"
  ).catch(async (error) => {
    if (isExtensionContextInvalidated(error)) {
      throw error;
    }
    await cancelTabAudioRecording(requestId);
    return { ok: false, error: friendlyErrorMessage(error) };
  });
  clearTimeout(pauseAfterRecordingTimer);
  clearStatusPulse();

  if (state.operationId === operationId) {
    restoreVideoTime(startTime);
  }
  assertOperationActive(operationId);

  if (!response?.ok) {
    throw new Error(response?.error || "音频转写失败");
  }

  const cues = normalizeTranscriptionCues(response.payload?.cues);
  state.detectedSourceLanguage = response.payload?.sourceLanguage || state.detectedSourceLanguage || "auto";
  setStatus(`已从音频转写 ${cues.length} 条字幕，正在翻译...`, "working");
  return cues;
}

function normalizeTranscriptionCues(cues) {
  const usableCues = Array.isArray(cues) ? cues.filter((cue) => String(cue?.text || cue?.translatedText || "").trim()) : [];
  if (!usableCues.length) {
    throw new Error("这段音频没有识别到可翻译的人声。请换到有人声的位置再开始，或换一个带 YouTube 字幕的视频。");
  }
  return usableCues;
}

async function prepareTabAudioCapture(durationSeconds) {
  const response = await sendRuntimeMessageWithTimeout(
    {
      type: "localtube.prepareTabAudioCapture",
      settings: state.settings,
      payload: { durationSeconds }
    },
    15000,
    "录音授权超时：请在当前 YouTube 视频页点击浏览器右上角 LocalTube Dub 图标授权。"
  ).catch((error) => {
    if (isExtensionContextInvalidated(error)) {
      throw error;
    }
    return { ok: false, error: friendlyErrorMessage(error) };
  });

  if (!response?.ok) {
    throw new Error(response?.error || "无法准备当前标签页录音");
  }

  if (!response.payload?.streamId) {
    throw new Error("没有拿到当前标签页录音授权，请点击浏览器右上角 LocalTube Dub 图标后重试。");
  }

  return response.payload;
}

async function cancelTabAudioRecording(requestId) {
  await sendRuntimeMessage({ type: "localtube.cancelTabAudioRecording", requestId }).catch(() => {});
}

function cancelActiveProviderDubs() {
  const requestIds = Array.from(state.activeDubRequestIds);
  state.activeDubRequestIds.clear();
  for (const requestId of requestIds) {
    cancelProviderDub(requestId);
  }
}

async function cancelProviderDub(requestId) {
  await sendRuntimeMessage({ type: "localtube.cancelProviderDub", requestId }).catch(() => {});
}

function startStatusPulse(messageFactory, tone, intervalMs = 1000) {
  clearStatusPulse();
  const startedAt = Date.now();
  const render = () => {
    const elapsedSeconds = Math.max(0, Math.round((Date.now() - startedAt) / 1000));
    setStatus(messageFactory(elapsedSeconds), tone);
  };
  render();
  state.statusPulseId = window.setInterval(render, intervalMs);
}

function clearStatusPulse() {
  if (!state.statusPulseId) {
    return;
  }
  clearInterval(state.statusPulseId);
  state.statusPulseId = 0;
}

function timelineCacheRequest(videoId = getCurrentVideoId(), providerOverride = state.timelineCacheProvider || state.settings.provider) {
  const provider = String(providerOverride || state.settings.provider || "");
  return {
    videoId: String(videoId || ""),
    targetLanguage: String(state.settings.targetLanguage || ""),
    provider,
    model: provider.startsWith("youtube-") ? "" : String(state.settings.effectiveModel || state.settings.model || "")
  };
}

async function loadCachedTimeline(videoId, operationId, providerOverride = "") {
  if (!state.settings.cacheTranslations || !videoId) {
    return null;
  }
  const request = timelineCacheRequest(videoId, providerOverride || state.settings.provider);
  const requests = providerOverride ? [request] : makeTimelineCacheLookupRequests(request);
  for (const request of requests) {
    const response = await sendRuntimeMessage({
      type: "localtube.getCachedTimeline",
      payload: request,
      settings: state.settings
    }).catch(() => null);
    assertOperationActive(operationId);
    if (response?.ok && response.payload?.hit) {
      return response.payload.entry;
    }
  }
  return null;
}

function restoreSourceCaptionCache(timeline) {
  const sourceCues = (Array.isArray(timeline?.cues) ? timeline.cues : []).map(
    ({ translatedText, ...cue }) => ({
      ...cue,
      text: String(cue.text || translatedText || "").trim()
    })
  );
  return normalizeRollingCaptionCues(sourceCues);
}

async function saveSourceCaptionCache(videoId, operationId, cues, sourceLanguage) {
  if (!state.settings.cacheTranslations || !videoId || state.operationId !== operationId) {
    return false;
  }
  const cacheCues = normalizeRollingCaptionCues(cues)
    .filter((cue) => String(cue.text || "").trim())
    .map((cue) => ({
      ...cue,
      translatedText: String(cue.text || "").trim()
    }));
  if (!cacheCues.length) {
    return false;
  }
  const response = await sendRuntimeMessage({
    type: "localtube.saveCachedTimeline",
    payload: {
      ...timelineCacheRequest(videoId, YOUTUBE_SOURCE_CACHE_PROVIDER),
      sourceLanguage: sourceLanguage || "auto",
      cues: cacheCues
    },
    settings: state.settings
  }).catch(() => null);
  assertOperationActive(operationId);
  return Boolean(response?.ok && response.payload?.saved);
}

async function saveTimelineCacheIfComplete(operationId) {
  if (!state.settings.cacheTranslations || state.partialTranscription || state.operationId !== operationId) {
    return false;
  }
  const videoId = getCurrentVideoId();
  if (!videoId || !state.originalCues.length || state.translatedCues.length < state.originalCues.length) {
    return false;
  }
  const translatedByKey = new Map(state.translatedCues.map((cue) => [cueKey(cue), cue]));
  const cues = state.originalCues.map((sourceCue) => {
    const translatedCue = translatedByKey.get(cueKey(sourceCue));
    const translatedText = String(translatedCue?.translatedText || translatedCue?.text || "").trim();
    return translatedText ? { ...sourceCue, translatedText } : null;
  });
  if (cues.some((cue) => !cue)) {
    return false;
  }
  const response = await sendRuntimeMessage({
    type: "localtube.saveCachedTimeline",
    payload: {
      ...timelineCacheRequest(videoId),
      sourceLanguage: state.detectedSourceLanguage || "auto",
      cues
    },
    settings: state.settings
  }).catch(() => null);
  return Boolean(response?.ok && response.payload?.saved);
}

async function translateQueuedCues(operationId, batches, detectedSourceLanguage, totalCueCount, options = {}) {
  if (!batches.length) {
    return;
  }

  const queue = batches.slice();
  const workerCount = Math.min(2, queue.length);
  const workers = Array.from({ length: workerCount }, async () => {
    while (queue.length) {
      const batch = queue.shift();
      assertOperationActive(operationId);
      const pendingBatch = reservePendingCues(batch);
      if (!pendingBatch.length) {
        continue;
      }
      try {
        const translatedBatch = options.skipTranslation
          ? pendingBatch.map(useCueTextAsTranslation)
          : await translateCues(pendingBatch, detectedSourceLanguage);
        assertOperationActive(operationId);
        state.translatedCues = mergeTranslatedCues(state.translatedCues, translatedBatch);
        refreshVoiceSegments();
        if (state.running) {
          setStatus(`已缓存 ${state.translatedCues.length}/${totalCueCount} 条字幕`, "");
        }
      } finally {
        releasePendingCues(pendingBatch);
      }
    }
  });

  await Promise.all(workers);

  if (state.operationId === operationId && state.running) {
    setWidgetPhase("running");
    setStatus(`已同步 ${state.translatedCues.length} 条字幕`, "");
    if (options.cacheWhenComplete) {
      await saveTimelineCacheIfComplete(operationId).catch(() => false);
    }
  }
}

function mergeTranslatedCues(existingCues, nextCues) {
  const cuesByKey = new Map();
  for (const cue of [...existingCues, ...nextCues]) {
    cuesByKey.set(cueKey(cue), cue);
  }
  return Array.from(cuesByKey.values()).sort((a, b) => Number(a.start || 0) - Number(b.start || 0));
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, number));
}

function restoreVideoTime(time) {
  if (!state.video) {
    return;
  }

  state.video.pause();
  state.suppressSeeking = true;
  state.video.currentTime = time;
  state.video.pause();
  queueMicrotask(() => state.video?.pause());
  setTimeout(() => {
    state.video?.pause();
    state.suppressSeeking = false;
  }, 300);
}

function stopDubbing(options = {}) {
  cancelCaptionAutoRetry();
  const wasBusy = state.busy;
  const fullTranscriptJobId = state.fullTranscriptJobId;
  const dubTrackJobId = state.dubTrackJobId;
  state.operationId += 1;
  invalidateVoicePlayback();
  state.busy = false;
  state.running = false;
  stopDubTrackPreview({ silent: true, resumeLive: false });
  state.originalCues = [];
  state.detectedSourceLanguage = "auto";
  state.translatedCues = [];
  state.voiceSegments = [];
  state.pendingTranslationTracker.clear();
  state.activeCueIndex = -1;
  state.spokenCueIndex = -1;
  state.spokenVoiceSegmentKey = "";
  state.spokenVoiceSegmentKeys.clear();
  state.spokenVoiceTextWindows.clear();
  state.speechActive = false;
  state.activeVoiceAudio?.pause();
  state.activeVoiceAudio = null;
  state.activeVoiceCueKey = "";
  state.activeVoiceSegment = null;
  state.voicePendingCueKey = "";
  state.voiceSeekAlignmentUntil = 0;
  cancelQueuedVoiceAudio();
  state.partialTranscription = false;
  state.transcriptionCoverageEnd = 0;
  state.rollingTranscriptionInFlight = false;
  state.rollingTranscriptionRetryAfter = 0;
  state.fullTranscriptJobId = "";
  state.fullTranscriptPreparing = false;
  state.fullTranscriptProgress = 0;
  state.dubTrackJobId = "";
  state.dubTrackRendering = false;
  state.dubTrackProgress = 0;
  state.dubTrackDownloadUrl = "";
  state.dubTrackFilename = "";
  state.dubTrackMixOriginal = false;
  state.dubTrackOutputFormat = "";
  state.pausedForTranscriptionBuffer = false;
  state.skipTranslation = false;
  state.timelineCacheProvider = "";
  state.priorityTranslationOperationId = 0;
  const activeTranscriptionRequestId = state.activeTranscriptionRequestId;
  state.activeTranscriptionRequestId = "";
  cancelElementAudioRecording(activeTranscriptionRequestId);
  cancelActiveProviderDubs();
  if (wasBusy && state.video) {
    state.video.pause();
  }
  setWidgetPhase("idle");

  if (state.caption) {
    state.caption.classList.remove("is-visible");
    state.caption.textContent = "";
  }

  if (state.video && state.mutedByLocalTube) {
    state.video.muted = state.originalMuted;
    state.video.volume = state.originalVolumeBeforeDubbing;
  }
  state.mutedByLocalTube = false;

  stopActiveBrowserSpeech();
  state.activeVoiceAudio?.pause();
  state.activeVoiceAudio = null;
  state.activeVoiceCueKey = "";
  state.activeVoiceSegment = null;
  state.activeBrowserVoiceSegment = null;
  state.voicePendingCueKey = "";
  cancelAnimationFrame(state.rafId);
  clearStatusPulse();
  if (activeTranscriptionRequestId) {
    cancelTabAudioRecording(activeTranscriptionRequestId);
  }
  if (fullTranscriptJobId) {
    sendRuntimeMessage({
      type: "localtube.cancelFullTranscript",
      settings: state.settings,
      jobId: fullTranscriptJobId
    }).catch(() => {});
  }
  if (dubTrackJobId) {
    sendRuntimeMessage({
      type: "localtube.cancelDubTrack",
      settings: state.settings,
      jobId: dubTrackJobId
    }).catch(() => {});
  }
  if (!options.silent) {
    setStatus("已停止", "");
  }
}

function bindVideoEvents(video) {
  if (state.boundVideo === video) {
    return;
  }

  if (state.boundVideo) {
    state.boundVideo.removeEventListener("seeking", handleVideoSeeking);
    state.boundVideo.removeEventListener("seeked", handleVideoSeeked);
    state.boundVideo.removeEventListener("waiting", handleVideoWaiting);
    state.boundVideo.removeEventListener("playing", handleVideoPlaying);
    state.boundVideo.removeEventListener("pause", handleVideoPause);
    state.boundVideo.removeEventListener("ended", handleVideoEnded);
    state.boundVideo.removeEventListener("ratechange", handleVideoRateChange);
  }

  state.boundVideo = video;
  state.videoBuffering = false;
  video.addEventListener("seeking", handleVideoSeeking);
  video.addEventListener("seeked", handleVideoSeeked);
  video.addEventListener("waiting", handleVideoWaiting);
  video.addEventListener("playing", handleVideoPlaying);
  video.addEventListener("pause", handleVideoPause);
  video.addEventListener("ended", handleVideoEnded);
  video.addEventListener("ratechange", handleVideoRateChange);
}

function handleVideoSeeked() {
  state.videoBuffering = false;
  if (state.dubTrackPreviewActive) {
    syncDubTrackPreview(state.video?.currentTime || 0, true);
  }
}

function handleVideoWaiting() {
  state.videoBuffering = true;
  if (state.dubTrackPreviewActive) {
    state.dubTrackPreviewAudio?.pause();
  }
}

function handleVideoPlaying() {
  state.videoBuffering = false;
  if (state.dubTrackPreviewActive) {
    syncDubTrackPreview(state.video?.currentTime || 0, true);
  }
}

function handleVideoPause() {
  if (state.dubTrackPreviewActive) {
    state.dubTrackPreviewAudio?.pause();
  }
}

function handleVideoEnded() {
  if (!state.dubTrackPreviewActive) {
    return;
  }
  stopDubTrackPreview({ silent: true, resumeLive: false });
  setStatus("完整音轨播放结束", "");
}

function handleVideoRateChange() {
  if (state.dubTrackPreviewActive) {
    syncDubTrackPreview(state.video?.currentTime || 0);
  }
}

function refreshActiveVideoReference() {
  const video = getPrimaryVideoElement();
  if (!video) {
    return state.video;
  }
  if (video !== state.video) {
    state.video = video;
    bindVideoEvents(video);
  }
  return state.video;
}

function getPrimaryVideoElement() {
  const preferred =
    document.querySelector("#movie_player video.html5-main-video") ||
    document.querySelector("#movie_player video") ||
    document.querySelector("ytd-player video");
  if (preferred && isUsableVideoElement(preferred)) {
    return preferred;
  }

  return Array.from(document.querySelectorAll("video"))
    .filter(isUsableVideoElement)
    .sort((a, b) => videoElementScore(b) - videoElementScore(a))[0] || null;
}

function isUsableVideoElement(video) {
  if (!video || typeof video.getBoundingClientRect !== "function") {
    return false;
  }
  const rect = video.getBoundingClientRect();
  return rect.width >= 120 && rect.height >= 80 && getComputedStyle(video).display !== "none";
}

function videoElementScore(video) {
  const rect = video.getBoundingClientRect();
  const area = Math.max(0, rect.width) * Math.max(0, rect.height);
  const playingBonus = video.paused ? 0 : 1000000;
  const mainClassBonus = video.classList?.contains("html5-main-video") ? 500000 : 0;
  return area + playingBonus + mainClassBonus;
}

function handleVideoSeeking() {
  if (state.suppressSeeking) {
    return;
  }

  if (state.busy) {
    stopDubbing({ silent: true });
    setStatus("已跳转进度，点开始翻译当前片段", "");
    return;
  }

  if (state.running && state.dubTrackPreviewActive) {
    state.videoBuffering = true;
    state.voiceSeekAlignmentUntil = Date.now() + 1200;
    state.activeCueIndex = -1;
    state.spokenCueIndex = -1;
    state.spokenVoiceSegmentKey = "";
    state.spokenVoiceSegmentKeys.clear();
    state.spokenVoiceTextWindows.clear();
    state.voicePendingCueKey = "";
    invalidateVoicePlayback();
    stopActiveBrowserSpeech();
    stopActiveVoiceAudio();
    syncDubTrackPreview(state.video?.currentTime || 0, true);
    setWidgetPhase("running");
    setStatus("完整音轨已同步到新进度", "");
    return;
  }

  if (state.running && state.partialTranscription) {
    stopDubbing({ silent: true });
    setStatus("无字幕视频已跳转，点开始重新转写当前片段", "");
    return;
  }

  if (state.running) {
    state.voiceSeekAlignmentUntil = Date.now() + 1200;
    state.activeCueIndex = -1;
    state.spokenCueIndex = -1;
    state.spokenVoiceSegmentKey = "";
    state.spokenVoiceSegmentKeys.clear();
    state.spokenVoiceTextWindows.clear();
    state.voicePendingCueKey = "";
    invalidateVoicePlayback();
    stopActiveBrowserSpeech();
    stopActiveVoiceAudio();
    setOriginalMutedForDubbing(false);
    setWidgetPhase("running");
    if (!hasTranslatedCueAt(state.video?.currentTime || 0) && hasSourceCueAt(state.video?.currentTime || 0)) {
      const seekingOperationId = state.operationId;
      setStatus("已跳转，正在优先补翻当前进度...", "working");
      translateCurrentPlaybackWindow(seekingOperationId).catch((error) => {
        if (error?.name !== "OperationStaleError" && state.operationId === seekingOperationId && state.running) {
          setStatus(`当前进度补翻失败：${error.message || String(error)}`, "error");
        }
      });
      return;
    }
    setStatus("已同步到新进度", "");
  }
}

function setWidgetPhase(phase) {
  state.phase = phase;
  updateWidgetState();
}

function updateWidgetState() {
  if (!state.root) {
    return;
  }

  state.root.dataset.phase = state.phase;
  const startButton = state.root.querySelector("[data-action='start']");
  const stopButton = state.root.querySelector("[data-action='stop']");
  if (startButton) {
    startButton.disabled = state.busy || state.running;
    startButton.textContent = startButtonLabel(state.phase);
  }
  if (stopButton) {
    stopButton.disabled = !state.busy && !state.running;
  }
  updateExportControl();
}

function updateExportControl() {
  const button = state.root?.querySelector("[data-action='export-subtitles']");
  const format = state.root?.querySelector("[data-field='exportFormat']");
  const fullTranscriptButton = state.root?.querySelector("[data-action='prepare-full-transcript']");
  const dubTrackButton = state.root?.querySelector("[data-action='export-dub-track']");
  const dubTrackPreviewButton = state.root?.querySelector("[data-action='preview-dub-track']");
  const dubTrackMode = state.root?.querySelector("[data-field='dubTrackMode']");
  const dubTrackFormat = state.root?.querySelector("[data-field='dubTrackFormat']");
  if (!button || !format || !fullTranscriptButton || !dubTrackButton || !dubTrackPreviewButton || !dubTrackMode || !dubTrackFormat) {
    return;
  }
  const cueCount = normalizeExportCues(state.translatedCues).length;
  const complete = isSubtitleExportComplete();
  button.disabled = cueCount === 0;
  format.disabled = cueCount === 0;
  button.textContent = complete ? "导出完整字幕" : "导出已缓存字幕";
  button.title = cueCount
    ? complete
      ? `导出全部 ${cueCount} 条字幕`
      : `导出当前已缓存的 ${cueCount} 条字幕`
    : "开始翻译后可导出字幕";

  const duration = Number(state.video?.duration || 0);
  const canPrepareFullTranscript =
    state.running &&
    state.partialTranscription &&
    state.settings.transcriptionProvider === "native" &&
    Number.isFinite(duration) &&
    duration > 0 &&
    duration <= FULL_TRANSCRIPT_MAX_SECONDS;
  fullTranscriptButton.hidden = !canPrepareFullTranscript && !state.fullTranscriptPreparing;
  fullTranscriptButton.disabled = false;
  fullTranscriptButton.textContent = state.fullTranscriptPreparing
    ? `取消完整字幕 ${Math.round(state.fullTranscriptProgress)}%`
    : "准备完整字幕";
  fullTranscriptButton.title = state.fullTranscriptPreparing
    ? "取消本地完整音频转写任务"
    : "后台提取当前视频的完整音频并用本地 Whisper 生成完整字幕";

  const canRenderDubTrack =
    complete && Number.isFinite(duration) && duration > 0 && duration <= FULL_TRANSCRIPT_MAX_SECONDS;
  const mixedTrack = state.settings.dubTrackMode === "mixed";
  const trackFormat = state.settings.dubTrackFormat === "wav" ? "WAV" : "M4A";
  dubTrackMode.disabled = state.dubTrackRendering;
  dubTrackFormat.disabled = state.dubTrackRendering;
  dubTrackButton.disabled = !state.dubTrackRendering && !state.dubTrackDownloadUrl && !canRenderDubTrack;
  dubTrackButton.classList.toggle("is-split", Boolean(state.dubTrackDownloadUrl));
  dubTrackPreviewButton.hidden = !state.dubTrackDownloadUrl;
  dubTrackPreviewButton.disabled = state.dubTrackRendering || !state.running;
  dubTrackPreviewButton.textContent = state.dubTrackPreviewActive ? "停止音轨" : "播放音轨";
  dubTrackPreviewButton.title = state.dubTrackPreviewActive
    ? "停止完整音轨并恢复逐句配音"
    : "在当前 YouTube 页面中按视频进度试听完整音轨";
  if (state.dubTrackRendering) {
    dubTrackButton.textContent = `取消${mixedTrack ? "混合" : "配音"}音轨 ${Math.round(state.dubTrackProgress)}%`;
    dubTrackButton.title = "取消正在后台生成的完整音轨";
  } else if (state.dubTrackDownloadUrl) {
    dubTrackButton.textContent = mixedTrack ? "下载混合音轨" : "下载配音音轨";
    dubTrackButton.title = state.dubTrackFilename || `下载已经生成的 ${trackFormat} 音轨`;
  } else {
    dubTrackButton.textContent = mixedTrack ? "生成混合音轨" : "生成配音音轨";
    dubTrackButton.title = canRenderDubTrack
      ? mixedTrack
        ? `按完整字幕时间轴生成配音，并按原声大小混入视频原音频，导出 ${trackFormat}`
        : `按完整字幕时间轴生成纯配音 ${trackFormat} 音轨`
      : "完整字幕准备完成后才能生成音轨";
  }
}

function isSubtitleExportComplete() {
  return (
    !state.partialTranscription &&
    state.originalCues.length > 0 &&
    normalizeExportCues(state.translatedCues).length >= normalizeExportCues(state.originalCues).length
  );
}

function exportCurrentSubtitles() {
  const format = state.root?.querySelector("[data-field='exportFormat']")?.value === "vtt" ? "vtt" : "srt";
  const cues = normalizeExportCues(state.translatedCues);
  if (!cues.length) {
    setStatus("还没有可导出的字幕，请先开始翻译。", "error");
    return;
  }

  const serialized = serializeSubtitleCues(cues, format);
  const complete = isSubtitleExportComplete();
  const videoId = sanitizeDownloadFilenamePart(getCurrentVideoId() || "youtube-video");
  const language = sanitizeDownloadFilenamePart(state.settings.targetLanguage || "translated");
  const scope = complete ? "complete" : "partial";
  const filename = `LocalTube-Dub_${videoId}_${language}_${scope}.${format}`;
  const mimeType = format === "vtt" ? "text/vtt;charset=utf-8" : "application/x-subrip;charset=utf-8";
  const blob = new Blob([format === "srt" ? "\ufeff" : "", serialized], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.documentElement.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  setStatus(complete ? `已导出完整字幕：${filename}` : `已导出当前缓存字幕：${filename}`, "");
}

function sanitizeDownloadFilenamePart(value) {
  return String(value || "")
    .trim()
    .replace(/[^a-zA-Z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "untitled";
}

function toggleFullTranscriptPreparation() {
  if (state.fullTranscriptPreparing) {
    cancelFullTranscriptPreparation();
    return;
  }
  prepareFullTranscript().catch((error) => {
    if (error?.name === "OperationStaleError") {
      return;
    }
    state.fullTranscriptPreparing = false;
    state.fullTranscriptJobId = "";
    state.fullTranscriptProgress = 0;
    updateExportControl();
    setStatus(`完整字幕准备失败：${friendlyErrorMessage(error)}`, "error");
  });
}

async function prepareFullTranscript() {
  const video = refreshActiveVideoReference();
  const durationSeconds = Number(video?.duration || 0);
  if (!state.running || !state.partialTranscription || state.settings.transcriptionProvider !== "native") {
    throw new Error("完整字幕只用于正在运行的本地无字幕转写。请先开始翻译。");
  }
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0 || durationSeconds > FULL_TRANSCRIPT_MAX_SECONDS) {
    throw new Error(`完整字幕目前支持最长 ${Math.round(FULL_TRANSCRIPT_MAX_SECONDS / 60)} 分钟的视频。`);
  }

  const operationId = state.operationId;
  state.fullTranscriptPreparing = true;
  state.fullTranscriptProgress = 1;
  updateExportControl();
  if (state.activeTranscriptionRequestId) {
    cancelTabAudioRecording(state.activeTranscriptionRequestId);
    state.activeTranscriptionRequestId = "";
  }
  state.rollingTranscriptionInFlight = false;
  releaseRollingTranscriptionBuffer();
  setStatus("正在启动完整本地字幕任务...", "working");

  const response = await sendRuntimeMessageWithTimeout(
    {
      type: "localtube.startFullTranscript",
      settings: state.settings,
      payload: {
        videoId: getCurrentVideoId(),
        videoUrl: location.href,
        durationSeconds
      }
    },
    20000,
    "完整字幕任务启动超时"
  );
  assertOperationActive(operationId);
  if (!response?.ok || !response.payload?.job?.id) {
    throw new Error(response?.error || "本地 Engine 没有创建完整字幕任务");
  }
  state.fullTranscriptJobId = response.payload.job.id;
  await pollFullTranscriptJob(operationId, response.payload.job);
}

async function pollFullTranscriptJob(operationId, initialJob) {
  let job = initialJob;
  while (state.fullTranscriptPreparing && state.fullTranscriptJobId) {
    assertOperationActive(operationId);
    state.fullTranscriptProgress = clampNumber(job?.progress, 0, 100, state.fullTranscriptProgress);
    updateExportControl();
    setStatus(fullTranscriptProgressMessage(job), job?.status === "failed" ? "error" : "working");

    if (job?.status === "completed") {
      await applyCompleteTranscript(job, operationId);
      return;
    }
    if (job?.status === "failed" || job?.status === "cancelled") {
      throw new Error(job.error || (job.status === "cancelled" ? "任务已取消" : "完整字幕任务失败"));
    }

    await delay(FULL_TRANSCRIPT_POLL_MS);
    assertOperationActive(operationId);
    const response = await sendRuntimeMessageWithTimeout(
      {
        type: "localtube.fullTranscriptStatus",
        settings: state.settings,
        jobId: state.fullTranscriptJobId
      },
      12000,
      "完整字幕进度查询超时"
    );
    if (!response?.ok || !response.payload?.job) {
      throw new Error(response?.error || "无法读取完整字幕任务进度");
    }
    job = response.payload.job;
  }
}

function fullTranscriptProgressMessage(job) {
  const progress = Math.round(clampNumber(job?.progress, 0, 100, 0));
  if (job?.stage === "downloading") {
    return `正在读取完整视频音频 ${progress}%...`;
  }
  if (job?.stage === "transcribing") {
    return `正在用本地 Whisper 生成完整字幕 ${progress}%...`;
  }
  if (job?.stage === "completed") {
    return "完整原文字幕已生成，正在翻译全部字幕...";
  }
  return `正在准备完整字幕 ${progress}%...`;
}

async function applyCompleteTranscript(job, operationId) {
  assertOperationActive(operationId);
  const completeCues = normalizeResolvedCues(job.cues);
  if (!completeCues.length) {
    throw new Error("完整转写任务没有返回可用字幕");
  }
  const shouldResume = Boolean(state.video && (!state.video.paused || state.pausedForTranscriptionBuffer));
  state.video?.pause();
  state.pausedForTranscriptionBuffer = false;
  cancelActiveProviderDubs();
  state.pendingTranslationTracker.clear();
  cancelQueuedVoiceAudio();
  invalidateVoicePlayback();
  stopActiveBrowserSpeech();
  stopActiveVoiceAudio();

  state.operationId += 1;
  const completeOperationId = state.operationId;
  state.originalCues = completeCues;
  state.translatedCues = [];
  state.detectedSourceLanguage = job.sourceLanguage || state.detectedSourceLanguage || "auto";
  state.transcriptionCoverageEnd = Number(job.durationSeconds || state.video?.duration || 0);
  state.partialTranscription = true;
  state.rollingTranscriptionInFlight = false;
  state.rollingTranscriptionRetryAfter = 0;
  state.activeCueIndex = -1;
  state.spokenCueIndex = -1;
  state.spokenVoiceSegmentKey = "";
  state.spokenVoiceSegmentKeys.clear();
  state.spokenVoiceTextWindows.clear();
  state.voiceSegments = [];
  setWidgetPhase("translating");
  setStatus(`完整原文字幕 ${completeCues.length} 条，正在翻译...`, "working");

  const batches = makePlaybackTranslationBatches(completeCues, state.video?.currentTime || 0, {
    firstBatchSize: 12,
    batchSize: 12
  });
  try {
    await translateQueuedCues(completeOperationId, batches, state.detectedSourceLanguage, completeCues.length);
  } catch (error) {
    state.fullTranscriptPreparing = false;
    state.fullTranscriptJobId = "";
    updateExportControl();
    if (shouldResume && state.video?.paused) {
      await state.video.play().catch(() => {});
    }
    throw error;
  }
  assertOperationActive(completeOperationId);
  state.partialTranscription = false;
  state.fullTranscriptPreparing = false;
  state.fullTranscriptJobId = "";
  state.fullTranscriptProgress = 100;
  refreshVoiceSegments();
  await saveTimelineCacheIfComplete(completeOperationId).catch(() => false);
  updateExportControl();
  if (state.settings.voiceEnabled) {
    await prewarmVoiceAroundTime(state.video?.currentTime || 0, completeOperationId);
  }
  setStatus(`完整字幕已准备：${state.translatedCues.length} 条，可导出或继续播放`, "");
  if (shouldResume && state.video?.paused) {
    await state.video.play().catch(() => {});
  }
}

function cancelFullTranscriptPreparation() {
  const jobId = state.fullTranscriptJobId;
  state.fullTranscriptPreparing = false;
  state.fullTranscriptJobId = "";
  state.fullTranscriptProgress = 0;
  updateExportControl();
  if (jobId) {
    sendRuntimeMessage({
      type: "localtube.cancelFullTranscript",
      settings: state.settings,
      jobId
    }).catch(() => {});
  }
  releaseRollingTranscriptionBuffer();
  setStatus("已取消完整字幕准备，继续使用滚动转写。", "");
}

function handleDubTrackAction() {
  if (state.dubTrackRendering) {
    cancelDubTrackRendering();
    return;
  }
  if (state.dubTrackDownloadUrl) {
    downloadReadyDubTrack();
    return;
  }
  startDubTrackRendering().catch((error) => {
    if (error?.name === "OperationStaleError") {
      return;
    }
    resetDubTrackState();
    setStatus(`配音音轨生成失败：${friendlyErrorMessage(error)}`, "error");
  });
}

async function startDubTrackRendering() {
  if (!isSubtitleExportComplete()) {
    throw new Error("请等待完整字幕翻译完成后再生成配音音轨。");
  }
  const video = refreshActiveVideoReference();
  const durationSeconds = Number(video?.duration || 0);
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0 || durationSeconds > FULL_TRANSCRIPT_MAX_SECONDS) {
    throw new Error(`配音音轨目前支持最长 ${Math.round(FULL_TRANSCRIPT_MAX_SECONDS / 60)} 分钟的视频。`);
  }
  const sourceCues = normalizeExportCues(state.translatedCues);
  refreshVoiceSegments();
  const cues = makeDubTrackRenderCues(state.voiceSegments, state.translatedCues);
  if (!cues.length) {
    throw new Error("没有可用于音轨生成的翻译字幕。");
  }

  const operationId = state.operationId;
  const mixedTrack = state.settings.dubTrackMode === "mixed";
  const outputFormat = state.settings.dubTrackFormat === "wav" ? "wav" : "m4a";
  const videoId = getCurrentVideoId();
  stopDubTrackPreview({ silent: true, resumeLive: false });
  state.dubTrackRendering = true;
  state.dubTrackProgress = 1;
  state.dubTrackDownloadUrl = "";
  state.dubTrackFilename = "";
  state.dubTrackMixOriginal = false;
  state.dubTrackOutputFormat = "";
  updateExportControl();
  const groupingLabel = cues.length < sourceCues.length ? `（由 ${sourceCues.length} 条字幕合并）` : "";
  setStatus(`正在启动 ${cues.length} 个语义配音段${groupingLabel}...`, "working");
  const response = await sendRuntimeMessageWithTimeout(
    {
      type: "localtube.startDubTrack",
      settings: state.settings,
      payload: {
        videoId,
        videoUrl: `https://www.youtube.com/watch?v=${encodeURIComponent(videoId)}`,
        durationSeconds,
        mixOriginal: mixedTrack,
        originalVolume: clampNumber(state.settings.originalVolume, 0, 1, DEFAULT_SETTINGS.originalVolume),
        outputFormat,
        cues
      }
    },
    25000,
    "配音音轨任务启动超时"
  );
  assertOperationActive(operationId);
  if (!response?.ok || !response.payload?.job?.id) {
    throw new Error(response?.error || "本地 Engine 没有创建配音音轨任务");
  }
  state.dubTrackJobId = response.payload.job.id;
  await pollDubTrackJob(operationId, response.payload.job);
}

async function pollDubTrackJob(operationId, initialJob) {
  let job = initialJob;
  while (state.dubTrackRendering && state.dubTrackJobId) {
    assertOperationActive(operationId);
    state.dubTrackProgress = clampNumber(job?.progress, 0, 100, state.dubTrackProgress);
    updateExportControl();
    setStatus(dubTrackProgressMessage(job), job?.status === "failed" ? "error" : "working");
    if (job?.status === "completed") {
      if (!isSafeDubTrackDownloadUrl(job.downloadUrl)) {
        throw new Error("Engine 返回了无效的音轨下载地址");
      }
      state.dubTrackRendering = false;
      state.dubTrackProgress = 100;
      state.dubTrackDownloadUrl = job.downloadUrl;
      state.dubTrackMixOriginal = Boolean(job.mixOriginal);
      state.dubTrackOutputFormat = job.outputFormat === "m4a" ? "m4a" : "wav";
      const extension = job.outputFormat === "m4a" ? "m4a" : "wav";
      state.dubTrackFilename = job.filename || (job.mixOriginal ? `LocalTube-Dub-mixed.${extension}` : `LocalTube-Dub-dub.${extension}`);
      state.dubTrackJobId = "";
      updateExportControl();
      setStatus(job.mixOriginal ? "混合音轨已生成，可直接播放或下载。" : "完整配音音轨已生成，可直接播放或下载。", "");
      return;
    }
    if (job?.status === "failed" || job?.status === "cancelled") {
      throw new Error(job.error || (job.status === "cancelled" ? "任务已取消" : "配音音轨任务失败"));
    }
    await delay(FULL_TRANSCRIPT_POLL_MS);
    assertOperationActive(operationId);
    const response = await sendRuntimeMessageWithTimeout(
      {
        type: "localtube.dubTrackStatus",
        settings: state.settings,
        jobId: state.dubTrackJobId
      },
      12000,
      "配音音轨进度查询超时"
    );
    if (!response?.ok || !response.payload?.job) {
      throw new Error(response?.error || "无法读取配音音轨任务进度");
    }
    job = response.payload.job;
  }
}

function dubTrackProgressMessage(job) {
  const progress = Math.round(clampNumber(job?.progress, 0, 100, 0));
  if (job?.stage === "downloading-original") {
    return `正在读取视频原音频（${progress}%）...`;
  }
  if (job?.stage === "synthesizing") {
    const rendered = Number(job?.renderedCues || 0);
    const total = Number(job?.cueCount || 0);
    const workers = Math.max(1, Number(job?.synthesisWorkers || 1));
    const workerLabel = workers > 1 ? `，${workers} 路并行` : "";
    return total
      ? `正在生成语义配音段 ${rendered}/${total}${workerLabel}（${progress}%）...`
      : `正在生成语义配音段${workerLabel} ${progress}%...`;
  }
  if (job?.stage === "assembling") {
    return "正在按字幕时间轴合成完整 WAV 音轨...";
  }
  if (job?.stage === "mixing") {
    return "正在按原声大小混合原音频与配音...";
  }
  if (job?.stage === "encoding") {
    return "正在压缩为 M4A 小文件...";
  }
  return `正在准备配音音轨 ${progress}%...`;
}

function cancelDubTrackRendering() {
  const jobId = state.dubTrackJobId;
  resetDubTrackState();
  if (jobId) {
    sendRuntimeMessage({
      type: "localtube.cancelDubTrack",
      settings: state.settings,
      jobId
    }).catch(() => {});
  }
  setStatus("已取消配音音轨生成。", "");
}

function resetDubTrackState() {
  stopDubTrackPreview({ silent: true, resumeLive: false });
  state.dubTrackJobId = "";
  state.dubTrackRendering = false;
  state.dubTrackProgress = 0;
  state.dubTrackDownloadUrl = "";
  state.dubTrackFilename = "";
  state.dubTrackMixOriginal = false;
  state.dubTrackOutputFormat = "";
  updateExportControl();
}

function toggleDubTrackPreview() {
  if (state.dubTrackPreviewActive) {
    stopDubTrackPreview({ resumeLive: true });
    return;
  }
  startDubTrackPreview().catch((error) => {
    if (!state.dubTrackPreviewActive) {
      return;
    }
    stopDubTrackPreview({ silent: true, resumeLive: true });
    setStatus(`完整音轨播放失败：${friendlyErrorMessage(error)}`, "error");
  });
}

async function startDubTrackPreview() {
  if (!state.running || !isSafeDubTrackDownloadUrl(state.dubTrackDownloadUrl)) {
    throw new Error("完整音轨尚未准备好，请先生成音轨。");
  }
  const video = refreshActiveVideoReference();
  if (!video) {
    throw new Error("当前页面没有找到可同步的视频播放器。");
  }

  invalidateVoicePlayback();
  stopActiveBrowserSpeech();
  stopActiveVoiceAudio();
  cancelQueuedVoiceAudio();
  state.voicePendingCueKey = "";
  const previewOperationId = ++state.dubTrackPreviewOperationId;
  const audio = new Audio(dubTrackPreviewUrl(state.dubTrackDownloadUrl));
  audio.preload = "auto";
  audio.muted = true;
  audio.dataset.localtubeFullTrack = "1";
  state.dubTrackPreviewAudio = audio;
  state.dubTrackPreviewActive = true;
  setOriginalMutedForDubbing(false);
  syncDubTrackPreview(video.currentTime, true);
  updateExportControl();

  audio.addEventListener("loadedmetadata", () => {
    if (
      state.dubTrackPreviewAudio === audio &&
      state.dubTrackPreviewActive &&
      state.dubTrackPreviewOperationId === previewOperationId
    ) {
      syncDubTrackPreview(video.currentTime, true);
      audio.muted = false;
    }
  });
  audio.addEventListener("ended", () => {
    if (state.dubTrackPreviewAudio === audio && state.dubTrackPreviewOperationId === previewOperationId) {
      stopDubTrackPreview({ silent: true, resumeLive: false });
      setStatus("完整音轨播放结束", "");
    }
  });
  audio.addEventListener("error", () => {
    if (
      state.dubTrackPreviewAudio === audio &&
      state.dubTrackPreviewActive &&
      state.dubTrackPreviewOperationId === previewOperationId
    ) {
      stopDubTrackPreview({ silent: true, resumeLive: true });
      setStatus("完整音轨加载失败，请确认字幕 Engine 仍在运行。", "error");
    }
  });

  const audioPlayback = requestDubTrackPreviewPlayback(audio, previewOperationId).catch((error) => {
    if (isExpectedDubTrackPlaybackAbort(error)) {
      return;
    }
    throw error;
  });
  const videoPlayback = video.paused ? video.play() : Promise.resolve();
  await Promise.all([audioPlayback, videoPlayback]);
  if (
    state.dubTrackPreviewAudio !== audio ||
    !state.dubTrackPreviewActive ||
    state.dubTrackPreviewOperationId !== previewOperationId
  ) {
    return;
  }
  syncDubTrackPreview(video.currentTime, true);
  setStatus(state.dubTrackMixOriginal ? "正在同步播放完整混合音轨" : "正在同步播放完整配音音轨", "");
}

function stopDubTrackPreview(options = {}) {
  const audio = state.dubTrackPreviewAudio;
  const wasActive = state.dubTrackPreviewActive;
  state.dubTrackPreviewOperationId += 1;
  state.dubTrackPreviewActive = false;
  state.dubTrackPreviewAudio = null;
  state.dubTrackPreviewPlayPromise = null;
  if (audio) {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
  }
  if (options.resumeLive && state.running) {
    state.spokenCueIndex = -1;
    state.spokenVoiceSegmentKey = "";
    state.spokenVoiceSegmentKeys.clear();
    state.spokenVoiceTextWindows.clear();
    state.voicePendingCueKey = "";
    state.activeCueIndex = -1;
  }
  applyAudioMixSettings();
  updateExportControl();
  if (wasActive && !options.silent) {
    setStatus("已停止完整音轨，恢复逐句同步配音。", "");
  }
}

function dubTrackPreviewUrl(value) {
  if (!isSafeDubTrackDownloadUrl(value)) {
    return "";
  }
  const url = new URL(value);
  url.searchParams.set("preview", "1");
  return url.toString();
}

function syncDubTrackPreview(currentTime, forceSeek = false) {
  const audio = state.dubTrackPreviewAudio;
  const video = state.video;
  if (!state.dubTrackPreviewActive || !audio || !video) {
    return false;
  }

  const sync = syncFullTrackMediaElements(video, audio, {
    mixOriginal: state.dubTrackMixOriginal,
    muteOriginal: state.settings.muteOriginal,
    originalVolume: state.settings.originalVolume,
    buffering: state.videoBuffering,
    forceSeek,
    seekThreshold: 0.18
  });
  if (sync.action === "stop") {
    stopDubTrackPreview({ silent: true, resumeLive: false });
    setStatus("完整音轨播放结束", "");
    return true;
  }
  if (sync.action === "play") {
    const previewOperationId = state.dubTrackPreviewOperationId;
    requestDubTrackPreviewPlayback(audio, previewOperationId).catch((error) => {
      if (isExpectedDubTrackPlaybackAbort(error)) {
        return;
      }
      if (
        state.dubTrackPreviewAudio === audio &&
        state.dubTrackPreviewActive &&
        state.dubTrackPreviewOperationId === previewOperationId
      ) {
        stopDubTrackPreview({ silent: true, resumeLive: true });
        setStatus(`完整音轨恢复播放失败：${friendlyErrorMessage(error)}`, "error");
      }
    });
  }
  return true;
}

function requestDubTrackPreviewPlayback(audio, previewOperationId) {
  if (
    state.dubTrackPreviewPlayPromise &&
    state.dubTrackPreviewAudio === audio &&
    state.dubTrackPreviewOperationId === previewOperationId
  ) {
    return state.dubTrackPreviewPlayPromise;
  }
  const playback = audio.play();
  state.dubTrackPreviewPlayPromise = playback;
  const clear = () => {
    if (
      state.dubTrackPreviewPlayPromise === playback &&
      state.dubTrackPreviewAudio === audio &&
      state.dubTrackPreviewOperationId === previewOperationId
    ) {
      state.dubTrackPreviewPlayPromise = null;
    }
  };
  playback.then(clear, clear);
  return playback;
}

function isExpectedDubTrackPlaybackAbort(error) {
  return error?.name === "AbortError";
}

function downloadReadyDubTrack() {
  if (!isSafeDubTrackDownloadUrl(state.dubTrackDownloadUrl)) {
    resetDubTrackState();
    setStatus("音轨下载地址已失效，请重新生成。", "error");
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = state.dubTrackDownloadUrl;
  anchor.rel = "noopener";
  anchor.hidden = true;
  document.documentElement.append(anchor);
  anchor.click();
  anchor.remove();
  setStatus(`已请求下载：${state.dubTrackFilename || "LocalTube Dub 配音音轨"}`, "");
}

function isSafeDubTrackDownloadUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return (
      url.protocol === "http:" &&
      ["127.0.0.1", "localhost"].includes(url.hostname) &&
      url.pathname === "/api/dub-track/download" &&
      Boolean(url.searchParams.get("id"))
    );
  } catch (error) {
    return false;
  }
}

function startButtonLabel(phase) {
  if (["preparing", "recording", "transcribing", "translating"].includes(phase)) {
    return "准备中";
  }
  if (["caching", "running"].includes(phase)) {
    return "运行中";
  }
  return "开始翻译";
}

function assertOperationActive(operationId) {
  if (state.operationId !== operationId) {
    const error = new Error("操作已取消");
    error.name = "OperationStaleError";
    throw error;
  }
}

function sendRuntimeMessageWithTimeout(message, timeoutMs, timeoutMessage) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      reject(new Error(timeoutMessage));
    }, timeoutMs);

    sendRuntimeMessage(message)
      .then((response) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        resolve(response);
      })
      .catch((error) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        reject(error);
      });
  });
}

function withTimeoutResult(promise, timeoutMs, timeoutMessage) {
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      resolve({
        status: "unknown",
        cues: [],
        track: null,
        error: timeoutMessage
      });
    }, timeoutMs);

    Promise.resolve(promise)
      .then((result) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        resolve(result);
      })
      .catch((error) => {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timer);
        resolve({
          status: "unknown",
          cues: [],
          track: null,
          error: error.message || String(error)
        });
      });
  });
}

function runSyncLoop() {
  cancelAnimationFrame(state.rafId);

  const tick = () => {
    refreshActiveVideoReference();
    if (!state.running || !state.video) {
      return;
    }
    enforceOriginalAudioMix();

    const currentTime = state.video.currentTime;
    maybePrefetchRollingTranscription(currentTime);
    maybePauseForRollingTranscription(currentTime);
    const cueIndex = findCueIndex(currentTime);
    if (cueIndex < 0) {
      maybeTranslatePlaybackGap(currentTime);
    }
    if (cueIndex !== state.activeCueIndex) {
      state.activeCueIndex = cueIndex;
      renderCaption(cueIndex);
    }

    if (!syncDubTrackPreview(currentTime)) {
      scheduleVoicePrefetchWindow(currentTime);
      stopVoiceIfOutsideActiveSegment(currentTime);
      syncActiveBrowserSpeech(currentTime);
      syncActiveVoiceAudio(currentTime);
      maybeSpeakVoiceSegment(findVoiceSegmentForPlayback(currentTime));
    }

    state.rafId = requestAnimationFrame(tick);
  };

  tick();
}

function maybePrefetchRollingTranscription(currentTime) {
  if (
    !state.partialTranscription ||
    state.settings.transcriptionProvider !== "native" ||
    state.fullTranscriptPreparing ||
    state.rollingTranscriptionInFlight ||
    Date.now() < state.rollingTranscriptionRetryAfter ||
    !Number.isFinite(state.transcriptionCoverageEnd) ||
    state.transcriptionCoverageEnd <= 0
  ) {
    return;
  }
  const videoEnd = Number.isFinite(state.video?.duration) ? state.video.duration : Infinity;
  if (state.transcriptionCoverageEnd >= videoEnd - 0.25) {
    return;
  }
  if (currentTime < state.transcriptionCoverageEnd - LOCAL_VIDEO_ROLLING_LEAD_SECONDS) {
    return;
  }

  const operationId = state.operationId;
  const previousCoverageEnd = state.transcriptionCoverageEnd;
  const startTime = Math.max(0, previousCoverageEnd - LOCAL_VIDEO_WINDOW_OVERLAP_SECONDS);
  const durationSeconds = Math.min(LOCAL_VIDEO_ROLLING_WINDOW_SECONDS, Math.max(6, videoEnd - startTime));
  state.rollingTranscriptionInFlight = true;
  setStatus(`正在提前准备 ${Math.round(startTime)} 秒后的配音字幕...`, "working");
  loadRollingTranscriptionWindow(operationId, startTime, durationSeconds, previousCoverageEnd)
    .catch((error) => {
      if (error?.name !== "OperationStaleError" && state.operationId === operationId && state.running) {
        state.rollingTranscriptionRetryAfter = Date.now() + 12000;
        setStatus(`下一段本地转写暂时失败，将自动重试：${friendlyErrorMessage(error)}`, "error");
        releaseRollingTranscriptionBuffer();
      }
    })
    .finally(() => {
      if (state.operationId === operationId) {
        state.rollingTranscriptionInFlight = false;
      }
    });
}

function releaseRollingTranscriptionBuffer() {
  if (!state.pausedForTranscriptionBuffer) {
    return;
  }
  state.pausedForTranscriptionBuffer = false;
  if (state.video?.paused) {
    state.video.play().catch(() => {});
  }
}

async function loadRollingTranscriptionWindow(operationId, startTime, durationSeconds, previousCoverageEnd) {
  const windowResult = await transcribeVideoWindowFromEngine(operationId, startTime, durationSeconds);
  assertOperationActive(operationId);
  const nextCues = selectNewRollingCues(
    state.originalCues,
    windowResult.cues,
    previousCoverageEnd,
    LOCAL_VIDEO_WINDOW_OVERLAP_SECONDS
  );
  const nextCoverageEnd = Math.max(previousCoverageEnd, windowResult.windowEnd);
  state.detectedSourceLanguage = windowResult.sourceLanguage || state.detectedSourceLanguage || "auto";

  if (nextCues.length) {
    state.originalCues = mergeCueTimeline(state.originalCues, nextCues);
    const pendingCues = reservePendingCues(nextCues);
    try {
      if (pendingCues.length) {
        const translated = await translateCues(pendingCues, state.detectedSourceLanguage);
        assertOperationActive(operationId);
        state.translatedCues = mergeTranslatedCues(state.translatedCues, translated);
        refreshVoiceSegments();
        if (state.settings.voiceEnabled) {
          await prewarmVoiceAroundTime(state.video?.currentTime || previousCoverageEnd, operationId);
        }
      }
    } finally {
      releasePendingCues(pendingCues);
    }
  }

  state.transcriptionCoverageEnd = nextCoverageEnd;
  state.rollingTranscriptionRetryAfter = 0;
  setStatus(`已提前准备到 ${Math.round(state.transcriptionCoverageEnd)} 秒`, "");
  if (state.pausedForTranscriptionBuffer && state.video?.paused) {
    state.pausedForTranscriptionBuffer = false;
    await state.video.play().catch(() => {});
  }
}

function maybePauseForRollingTranscription(currentTime) {
  const waitingForTranscription = state.rollingTranscriptionInFlight || state.fullTranscriptPreparing;
  if (
    !state.partialTranscription ||
    !waitingForTranscription ||
    state.pausedForTranscriptionBuffer ||
    state.video?.paused ||
    currentTime < state.transcriptionCoverageEnd - LOCAL_VIDEO_BUFFER_EDGE_SECONDS
  ) {
    return;
  }
  state.pausedForTranscriptionBuffer = true;
  state.video.pause();
  setStatus(
    state.fullTranscriptPreparing ? "完整字幕仍在生成，已在缓存边界暂停..." : "下一段配音字幕仍在生成，已短暂缓冲...",
    "working"
  );
}

function enforceOriginalAudioMix() {
  if (!state.video || !state.mutedByLocalTube) {
    return;
  }
  const mix = computeAudioMixState(state.settings, {
    mutedByLocalTube: state.mutedByLocalTube,
    running: state.running,
    activeCueIndex: state.activeCueIndex,
    spokenCueIndex: state.spokenCueIndex
  });
  state.video.muted = state.dubTrackPreviewActive && state.dubTrackMixOriginal ? true : mix.muted;
  state.video.volume = mix.volume;
}

function maybeTranslatePlaybackGap(currentTime) {
  if (!hasSourceCueAt(currentTime) || hasTranslatedCueAt(currentTime) || state.priorityTranslationOperationId) {
    return;
  }

  setStatus("正在补翻当前播放位置...", "working");
  const playbackOperationId = state.operationId;
  translateCurrentPlaybackWindow(playbackOperationId).catch((error) => {
    if (error?.name !== "OperationStaleError" && state.operationId === playbackOperationId && state.running) {
      setStatus(`当前播放位置补翻失败：${error.message || String(error)}`, "error");
    }
  });
}

function findCueIndex(time) {
  return findCueIndexInList(state.translatedCues, time);
}

function findCueIndexAtOrAfter(cues, time) {
  const current = findCueIndexInList(cues, time);
  if (current >= 0) {
    return current;
  }
  let low = 0;
  let high = cues.length - 1;
  let candidate = -1;
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (cues[mid].start >= time) {
      candidate = mid;
      high = mid - 1;
    } else {
      low = mid + 1;
    }
  }
  return candidate;
}

function findCueIndexInList(cues, time) {
  let low = 0;
  let high = cues.length - 1;

  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    const cue = cues[mid];
    if (time < cue.start) {
      high = mid - 1;
    } else if (time > cue.end) {
      low = mid + 1;
    } else {
      return mid;
    }
  }

  return -1;
}

function hasTranslatedCueAt(time) {
  return findCueIndexInList(state.translatedCues, time) >= 0;
}

function hasSourceCueAt(time) {
  return findCueIndexInList(state.originalCues, time) >= 0;
}

function hasTranslatedCue(cue) {
  return state.translatedCues.some((translatedCue) => cueKey(translatedCue) === cueKey(cue));
}

function isCueTranslationPending(cue) {
  return state.pendingTranslationTracker.isPending(cue);
}

function reservePendingCues(cues) {
  return state.pendingTranslationTracker.reserve(cues);
}

function releasePendingCues(cues) {
  state.pendingTranslationTracker.release(cues);
}

async function translateCurrentPlaybackWindow(operationId) {
  if (state.priorityTranslationOperationId === operationId || !state.originalCues.length) {
    return;
  }

  state.priorityTranslationOperationId = operationId;
  let pendingBatch = [];
  try {
    const currentTime = state.video?.currentTime || 0;
    const batches = makePlaybackTranslationBatches(state.originalCues, currentTime, {
      firstBatchSize: 10,
      batchSize: 12
    });
    pendingBatch = reservePendingCues(batches[0] || []);
    if (!pendingBatch.length) {
      setStatus("已同步到新进度", "");
      return;
    }

    assertOperationActive(operationId);
    const translatedBatch = state.skipTranslation
      ? pendingBatch.map(useCueTextAsTranslation)
      : await translateCues(pendingBatch, state.detectedSourceLanguage || "auto");
    assertOperationActive(operationId);
    state.translatedCues = mergeTranslatedCues(state.translatedCues, translatedBatch);
    refreshVoiceSegments();
    state.activeCueIndex = -1;
    setStatus(`已补翻当前进度 ${state.translatedCues.length}/${state.originalCues.length} 条`, "");
  } finally {
    releasePendingCues(pendingBatch);
    if (state.priorityTranslationOperationId === operationId) {
      state.priorityTranslationOperationId = 0;
    }
  }
}

function renderCaption(cueIndex) {
  if (!state.caption) {
    return;
  }

  if (cueIndex < 0) {
    state.caption.classList.remove("is-visible");
    state.caption.textContent = "";
    if (!state.activeVoiceAudio && !state.activeBrowserVoiceSegment) {
      setOriginalMutedForDubbing(false);
    }
    return;
  }

  const cue = state.translatedCues[cueIndex];
  state.caption.textContent = resolveVoiceCaptionText(cue, state.voiceSegments, state.settings.voiceEnabled);
  state.caption.classList.toggle("is-visible", Boolean(state.caption.textContent));
}

function refreshVoiceSegments() {
  state.voiceSegments = extendSemanticVoiceSegments(state.voiceSegments, state.translatedCues, voiceSegmentOptions());
  remapVoiceSegmentCueIndices();
  pruneQueuedVoiceAudioTasks();
  if (state.running && state.settings.voiceEnabled && state.video) {
    scheduleVoicePrefetchWindow(state.video.currentTime || 0);
  }
}

function buildVoiceSegments(cues) {
  return buildSemanticVoiceSegments(cues, voiceSegmentOptions());
}

function voiceSegmentOptions() {
  const naturalOnline = state.settings.ttsEngine === "edge";
  return {
    language: state.settings.targetLanguage,
    minDuration: naturalOnline ? 2.2 : VOICE_SEGMENT_MIN_SECONDS,
    maxDuration: naturalOnline ? 6.2 : VOICE_SEGMENT_MAX_SECONDS,
    maxGap: naturalOnline ? 0.35 : VOICE_SEGMENT_MAX_GAP_SECONDS,
    maxCues: naturalOnline ? 5 : VOICE_SEGMENT_MAX_CUES,
    maxChars: naturalOnline ? 120 : VOICE_SEGMENT_MAX_CHARS,
    silenceSlack: VOICE_TIMEBOX_SILENCE_SLACK_SECONDS
  };
}

function remapVoiceSegmentCueIndices() {
  const cueIndexByKey = new Map(state.translatedCues.map((cue, index) => [cueKey(cue), index]));
  state.voiceSegments = state.voiceSegments.map((segment) => ({
    ...segment,
    startCueIndex: cueIndexByKey.get(segment.cueKeys[0]) ?? segment.startCueIndex,
    endCueIndex: cueIndexByKey.get(segment.cueKeys[segment.cueKeys.length - 1]) ?? segment.endCueIndex
  }));
}

function voiceSegmentPlaybackEnd(segment) {
  return Math.max(Number(segment?.timeboxEnd || segment?.end || 0), Number(segment?.end || 0));
}

function voiceSegmentPlaybackDuration(segment) {
  return Math.max(0.35, voiceSegmentPlaybackEnd(segment) - Number(segment?.start || 0));
}

function findVoiceSegmentForPlayback(currentTime) {
  if (!state.voiceSegments.length) {
    return null;
  }
  const leadTime = currentTime + VOICE_LEAD_SECONDS;
  return (
    state.voiceSegments.find((segment) => segment.start <= leadTime && voiceSegmentPlaybackEnd(segment) >= currentTime - 0.05) ||
    state.voiceSegments.find((segment) => segment.start >= currentTime && segment.start <= leadTime) ||
    null
  );
}

function findVoiceSegmentAtOrAfter(time) {
  return state.voiceSegments.find((segment) => voiceSegmentPlaybackEnd(segment) >= time - 0.05) || null;
}

function maybeSpeakVoiceSegment(segment) {
  if (
    state.dubTrackPreviewActive ||
    !state.settings.voiceEnabled ||
    !segment ||
    state.spokenVoiceSegmentKeys.has(segment.key) ||
    wasVoiceTextRecentlySpoken(segment)
  ) {
    return;
  }
  if (state.video?.paused) {
    return;
  }
  if (state.speechActive && state.activeBrowserVoiceSegment) {
    if (state.video.currentTime < voiceSegmentPlaybackEnd(state.activeBrowserVoiceSegment) - VOICE_TIMEBOX_END_GRACE_SECONDS) {
      return;
    }
    stopActiveBrowserSpeech();
  }
  if (
    state.activeVoiceAudio &&
    state.activeVoiceSegment &&
    state.video.currentTime < voiceSegmentPlaybackEnd(state.activeVoiceSegment) - 0.08
  ) {
    return;
  }
  if (state.voicePendingCueKey === segment.key || state.activeVoiceCueKey === segment.key) {
    return;
  }
  if (!segment.text) {
    setOriginalMutedForDubbing(false);
    return;
  }
  if (shouldSkipLateVoiceSegment(segment, { audioReady: hasVoiceSegmentAudioReady(segment) })) {
    markVoiceSegmentSkipped(segment);
    return;
  }

  const playbackGeneration = beginVoicePlaybackAttempt();
  state.voicePendingCueKey = segment.key;
  scheduleVoicePrefetchWindow(segment.start);
  playVoiceSegment(segment, playbackGeneration).catch((error) => {
    if (
      isVoicePlaybackAttemptCurrent(segment, playbackGeneration) &&
      state.voicePendingCueKey === segment.key &&
      state.running &&
      !state.dubTrackPreviewActive &&
      isVoiceSegmentCurrent(segment)
    ) {
      setStatus(`本地配音播放失败，已回退浏览器朗读：${friendlyErrorMessage(error)}`, "error");
      speakSegmentWithBrowserTts(segment, playbackGeneration);
    }
  }).finally(() => {
    if (state.voicePendingCueKey === segment.key) {
      state.voicePendingCueKey = "";
    }
  });
}

async function playVoiceSegment(segment, playbackGeneration) {
  if (state.dubTrackPreviewActive) {
    return;
  }
  const hadCachedAudio = hasVoiceSegmentAudioReady(segment);
  if (shouldSkipLateVoiceSegment(segment, { audioReady: hadCachedAudio })) {
    markVoiceSegmentSkipped(segment);
    return;
  }
  const audioPayload = await getVoiceSegmentAudio(segment, { priority: true });
  if (!isVoicePlaybackAttemptCurrent(segment, playbackGeneration)) {
    return;
  }
  if (!audioPayload?.dataUrl) {
    throw new Error("本地 TTS 没有返回音频");
  }
  if (state.dubTrackPreviewActive || !state.running || !state.video || state.video.paused || !isVoiceSegmentCurrent(segment)) {
    return;
  }
  if (shouldSkipLateVoiceSegment(segment, { audioReady: true })) {
    markVoiceSegmentSkipped(segment);
    return;
  }
  if (state.video.currentTime > voiceSegmentPlaybackEnd(segment) - VOICE_LATE_SKIP_SECONDS) {
    markVoiceSegmentSkipped(segment);
    return;
  }

  stopActiveBrowserSpeech();
  const audio = new Audio(audioPayload.dataUrl);
  audio.preload = "auto";
  audio.preservesPitch = true;
  if ("webkitPreservesPitch" in audio) {
    audio.webkitPreservesPitch = true;
  }
  audio.dataset.localtubeVoice = "1";
  audio.dataset.localtubePreparedFitRate = String(Math.max(1, Number(audioPayload.fitRate || 1)));
  await waitForAudioMetadata(audio, 900);
  if (state.dubTrackPreviewActive || !isVoicePlaybackAttemptCurrent(segment, playbackGeneration)) {
    return;
  }
  await waitUntilSegmentStart(segment);
  if (
    state.dubTrackPreviewActive ||
    !isVoicePlaybackAttemptCurrent(segment, playbackGeneration) ||
    !state.running ||
    !state.video ||
    state.video.paused ||
    !isVoiceSegmentCurrent(segment)
  ) {
    return;
  }
  if (shouldSkipLateVoiceSegment(segment, { audioReady: true })) {
    markVoiceSegmentSkipped(segment);
    return;
  }
  if (state.video.currentTime > voiceSegmentPlaybackEnd(segment) - VOICE_LATE_SKIP_SECONDS) {
    markVoiceSegmentSkipped(segment);
    return;
  }
  alignVoiceAudioToSegment(audio, segment);
  stopActiveVoiceAudio();
  stopActiveBrowserSpeech();
  state.activeVoiceAudio = audio;
  state.activeVoiceCueKey = segment.key;
  state.activeVoiceSegment = segment;
  audio.addEventListener("play", () => {
    state.spokenCueIndex = segment.startCueIndex;
    state.spokenVoiceSegmentKey = segment.key;
    state.spokenVoiceSegmentKeys.add(segment.key);
    rememberSpokenVoiceText(segment);
    state.speechActive = true;
    setOriginalMutedForDubbing(Boolean(state.settings.muteOriginal));
  });
  audio.addEventListener("ended", () => {
    if (state.activeVoiceAudio === audio) {
      state.speechActive = false;
      state.activeVoiceAudio = null;
      state.activeVoiceCueKey = "";
      state.activeVoiceSegment = null;
      setOriginalMutedForDubbing(false);
    }
  });
  audio.addEventListener("error", () => {
    if (state.activeVoiceAudio === audio) {
      state.speechActive = false;
      state.activeVoiceAudio = null;
      state.activeVoiceCueKey = "";
      state.activeVoiceSegment = null;
      setOriginalMutedForDubbing(false);
    }
  });
  await audio.play();
  resetVoiceAudioSyncPlan(audio);
  syncActiveVoiceAudio(state.video.currentTime);
}

function hasVoiceSegmentAudioReady(segment) {
  return state.voiceAudioCache.has(voiceCacheKey(segment));
}

function shouldSkipLateVoiceSegment(segment, options = {}) {
  const currentTime = state.video?.currentTime || 0;
  const start = Number(segment?.start || 0);
  const end = voiceSegmentPlaybackEnd(segment) || start;
  const remaining = end - currentTime;
  const firstAttempt = !state.spokenVoiceSegmentKey && Number(state.spokenCueIndex) < 0;
  const minRemaining = firstAttempt ? VOICE_FIRST_SEGMENT_MIN_REMAINING_SECONDS : VOICE_MIN_REMAINING_SECONDS;
  if (remaining < minRemaining) {
    return true;
  }
  if (options.audioReady || firstAttempt) {
    return false;
  }
  const lateBy = currentTime - start;
  return lateBy > VOICE_LATE_START_SKIP_SECONDS && remaining < Math.max(0.75, voiceSegmentPlaybackDuration(segment) * 0.3);
}

function markVoiceSegmentSkipped(segment) {
  if (!segment) {
    return;
  }
  state.spokenCueIndex = segment.startCueIndex;
  state.spokenVoiceSegmentKey = segment.key;
  state.spokenVoiceSegmentKeys.add(segment.key);
  rememberSpokenVoiceText(segment);
  if (state.voicePendingCueKey === segment.key) {
    invalidateVoicePlayback();
    state.voicePendingCueKey = "";
  }
  if (state.activeVoiceCueKey === segment.key) {
    stopActiveVoiceAudio();
    if (state.activeBrowserVoiceSegment?.key === segment.key) {
      stopActiveBrowserSpeech();
    }
  }
}

function stopActiveVoiceAudio() {
  if (!state.activeVoiceAudio) {
    return;
  }
  state.activeVoiceAudio.pause();
  state.activeVoiceAudio.currentTime = 0;
  state.activeVoiceAudio = null;
  state.activeVoiceCueKey = "";
  state.activeVoiceSegment = null;
  state.speechActive = false;
}

function stopActiveBrowserSpeech(options = {}) {
  cancelPendingBrowserSpeechStart();
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  const segment = state.activeBrowserVoiceSegment;
  state.activeBrowserVoiceSegment = null;
  state.speechActive = false;
  if (segment && state.activeVoiceCueKey === segment.key) {
    state.activeVoiceCueKey = "";
  }
  if (options.resetSpoken && segment && state.spokenVoiceSegmentKey === segment.key) {
    state.spokenCueIndex = -1;
    state.spokenVoiceSegmentKey = "";
  }
}

function beginVoicePlaybackAttempt() {
  cancelPendingBrowserSpeechStart();
  state.voicePlaybackGeneration += 1;
  return state.voicePlaybackGeneration;
}

function invalidateVoicePlayback() {
  cancelPendingBrowserSpeechStart();
  state.voicePlaybackGeneration += 1;
}

function cancelPendingBrowserSpeechStart() {
  if (!state.browserVoiceStartTimer) {
    return;
  }
  clearTimeout(state.browserVoiceStartTimer);
  state.browserVoiceStartTimer = 0;
}

function isVoicePlaybackAttemptCurrent(segment, playbackGeneration) {
  return Boolean(segment && playbackGeneration === state.voicePlaybackGeneration);
}

function voiceTextFingerprint(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[\s，。！？；：、,.!?;:'"“”‘’()（）\[\]]+/g, "")
    .trim();
}

function wasVoiceTextRecentlySpoken(segment) {
  const fingerprint = voiceTextFingerprint(segment?.text);
  const previous = fingerprint ? state.spokenVoiceTextWindows.get(fingerprint) : null;
  if (!previous) {
    return false;
  }
  return Number(segment.start || 0) <= previous.end + 0.35 && Number(segment.end || 0) >= previous.start - 0.05;
}

function rememberSpokenVoiceText(segment) {
  const fingerprint = voiceTextFingerprint(segment?.text);
  if (!fingerprint) {
    return;
  }
  state.spokenVoiceTextWindows.set(fingerprint, {
    start: Number(segment.start || 0),
    end: voiceSegmentPlaybackEnd(segment)
  });
  while (state.spokenVoiceTextWindows.size > 96) {
    state.spokenVoiceTextWindows.delete(state.spokenVoiceTextWindows.keys().next().value);
  }
}

function stopVoiceIfOutsideActiveSegment(currentTime) {
  if (state.activeBrowserVoiceSegment) {
    const browserSegment = state.activeBrowserVoiceSegment;
    if (
      currentTime >= voiceSegmentPlaybackEnd(browserSegment) + VOICE_TIMEBOX_END_GRACE_SECONDS ||
      currentTime < browserSegment.start - VOICE_LEAD_SECONDS - 0.08
    ) {
      stopActiveBrowserSpeech();
      setOriginalMutedForDubbing(false);
    }
  }
  if (!state.activeVoiceAudio || !state.activeVoiceSegment) {
    return;
  }
  const segment = state.activeVoiceSegment;
  if (
    currentTime >= voiceSegmentPlaybackEnd(segment) + VOICE_TIMEBOX_END_GRACE_SECONDS ||
    currentTime < segment.start - VOICE_LEAD_SECONDS - 0.08
  ) {
    stopActiveVoiceAudio();
    setOriginalMutedForDubbing(false);
  }
}

function isVoiceSegmentCurrent(segment) {
  const currentTime = state.video?.currentTime || 0;
  const leadTime = currentTime + VOICE_LEAD_SECONDS;
  return segment.start <= leadTime && voiceSegmentPlaybackEnd(segment) >= currentTime - 0.08;
}

async function waitForAudioMetadata(audio, timeoutMs) {
  if (Number.isFinite(audio.duration) && audio.duration > 0) {
    return;
  }
  audio.load();
  await Promise.race([
    new Promise((resolve) => {
      audio.addEventListener("loadedmetadata", resolve, { once: true });
      audio.addEventListener("canplaythrough", resolve, { once: true });
      audio.addEventListener("error", resolve, { once: true });
    }),
    delay(timeoutMs)
  ]);
}

async function waitUntilSegmentStart(segment) {
  const currentTime = state.video?.currentTime || 0;
  const videoRate = Math.max(0.25, Number(state.video?.playbackRate || 1));
  const waitMs = Math.max(0, ((segment.start - currentTime - voiceSyncTiming().startEarly) / videoRate) * 1000);
  if (waitMs > 0) {
    await delay(Math.min(waitMs, VOICE_LEAD_SECONDS * 1000));
  }
}

function resetVoiceAudioSyncPlan(audio) {
  delete audio.dataset.localtubePlannedRate;
  delete audio.dataset.localtubePlannedVideoRate;
  delete audio.dataset.localtubePlanVideoTime;
  delete audio.dataset.localtubePlanAudioTime;
}

function alignVoiceAudioToSegment(audio, segment) {
  if (!state.video) {
    return;
  }
  const now = state.video.currentTime;
  const duration = Number(audio.duration || 0);
  if (!Number.isFinite(duration) || duration <= 0.2) {
    return;
  }

  const explicitVideoSeek = Date.now() <= state.voiceSeekAlignmentUntil;
  const currentVideoRate = Math.max(0.25, Number(state.video.playbackRate || 1));
  const plannedVideoRate = Number(audio.dataset.localtubePlannedVideoRate || 0);
  if (plannedVideoRate && Math.abs(plannedVideoRate - currentVideoRate) > 0.01) {
    delete audio.dataset.localtubePlannedRate;
    delete audio.dataset.localtubePlanVideoTime;
    delete audio.dataset.localtubePlanAudioTime;
  }
  const plannedRate = Number(audio.dataset.localtubePlannedRate || 0);
  const timing = voiceSyncTiming();
  const sync = computeLiveVoiceSync(now, state.video.playbackRate, audio.currentTime, duration, segment, {
    explicitSeek: explicitVideoSeek,
    endGrace: VOICE_TIMEBOX_END_GRACE_SECONDS,
    finishGuard: timing.finishGuard,
    startEarly: timing.startEarly,
    seekGrace: VOICE_TIMEBOX_SEEK_GRACE_SECONDS,
    seekThreshold: VOICE_TIMEBOX_SEEK_THRESHOLD_SECONDS,
    maxRateMultiplier: voiceTimeboxMaxRate(segment, Number(audio.dataset.localtubePreparedFitRate || 1)),
    plannedRate,
    anchorVideoTime: Number(audio.dataset.localtubePlanVideoTime),
    anchorAudioTime: Number(audio.dataset.localtubePlanAudioTime),
    videoPaused: state.video.paused,
    videoSeeking: state.video.seeking,
    buffering: state.videoBuffering,
    audioPaused: audio.paused
  });
  if (sync.seekTo !== null) {
    audio.currentTime = sync.seekTo;
    audio.dataset.localtubePlanVideoTime = String(now);
    audio.dataset.localtubePlanAudioTime = String(sync.seekTo);
    state.voiceSeekAlignmentUntil = 0;
  }
  if (!plannedRate || sync.seekTo !== null) {
    audio.dataset.localtubePlannedRate = String(sync.plannedRate);
    audio.dataset.localtubePlannedVideoRate = String(currentVideoRate);
    if (sync.seekTo === null) {
      audio.dataset.localtubePlanVideoTime = String(now);
      audio.dataset.localtubePlanAudioTime = String(audio.currentTime);
    }
  }
  audio.playbackRate = sync.playbackRate;
  return sync;
}

function voiceTotalMaxRate(segment) {
  return computeVoiceRateBudget(segment, state.settings.ttsEngine, 1).comfortTotalRate;
}

function voiceTimeboxMaxRate(segment, preparedFitRate = 1) {
  return computeVoiceRateBudget(segment, state.settings.ttsEngine, preparedFitRate).liveMaxRateMultiplier;
}

function voiceSyncTiming() {
  return computeVoiceSyncTiming(state.settings.ttsEngine);
}

function syncActiveVoiceAudio(currentTime) {
  if (!state.activeVoiceAudio || !state.activeVoiceSegment || !state.video) {
    return;
  }
  if (state.video.paused) {
    state.activeVoiceAudio.pause();
    setOriginalMutedForDubbing(false);
    return;
  }
  const sync = alignVoiceAudioToSegment(state.activeVoiceAudio, state.activeVoiceSegment);
  if (sync?.action === "stop") {
    stopActiveVoiceAudio();
    setOriginalMutedForDubbing(false);
    return;
  }
  if (sync?.action === "pause") {
    state.activeVoiceAudio.pause();
    setOriginalMutedForDubbing(false);
    return;
  }
  if (state.activeVoiceAudio.paused && sync?.action === "play") {
    state.activeVoiceAudio.play().catch(() => {});
  }
}

function syncActiveBrowserSpeech(currentTime) {
  const segment = state.activeBrowserVoiceSegment;
  if (!segment || !window.speechSynthesis || !state.video) {
    return;
  }
  if (state.video.paused || state.videoBuffering) {
    if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
      window.speechSynthesis.pause();
    }
    setOriginalMutedForDubbing(false);
    return;
  }
  if (window.speechSynthesis.paused) {
    window.speechSynthesis.resume();
    setOriginalMutedForDubbing(Boolean(state.settings.muteOriginal));
  }
  if (currentTime >= voiceSegmentPlaybackEnd(segment) + VOICE_TIMEBOX_END_GRACE_SECONDS) {
    stopActiveBrowserSpeech();
    setOriginalMutedForDubbing(false);
  }
}

async function getVoiceSegmentAudio(segment, options = {}) {
  if (Date.now() < state.localTtsUnavailableUntil) {
    throw new Error("本地 TTS 暂不可用");
  }
  const key = voiceCacheKey(segment);
  const cached = state.voiceAudioCache.get(key);
  if (cached) {
    return cached;
  }
  const pending = state.voiceAudioPending.get(key);
  if (pending) {
    return pending;
  }

  const promise = new Promise((resolve, reject) => {
    const task = async () => {
      state.voiceAudioActiveCount += 1;
      try {
        const payload = await requestVoiceSegmentAudio(segment);
        rememberVoiceAudio(key, payload);
        resolve(payload);
      } catch (error) {
        reject(error);
      } finally {
        state.voiceAudioActiveCount = Math.max(0, state.voiceAudioActiveCount - 1);
        state.voiceAudioPending.delete(key);
        drainVoiceAudioQueue();
      }
    };
    task.key = key;
    task.cancel = () => {
      state.voiceAudioPending.delete(key);
      reject(new Error("配音请求已取消"));
    };
    if (options.priority) {
      state.voiceAudioQueue.unshift(task);
    } else {
      state.voiceAudioQueue.push(task);
    }
    drainVoiceAudioQueue();
  });
  state.voiceAudioPending.set(key, promise);
  return promise;
}

function drainVoiceAudioQueue() {
  while (state.voiceAudioActiveCount < VOICE_AUDIO_MAX_CONCURRENCY && state.voiceAudioQueue.length) {
    const task = state.voiceAudioQueue.shift();
    task();
  }
}

function cancelQueuedVoiceAudio() {
  const queued = state.voiceAudioQueue.splice(0);
  for (const task of queued) {
    task.cancel?.();
  }
}

function pruneQueuedVoiceAudioTasks() {
  if (!state.voiceAudioQueue.length) {
    return;
  }
  const validKeys = new Set(state.voiceSegments.map((segment) => voiceCacheKey(segment)));
  const queued = state.voiceAudioQueue.splice(0);
  for (const task of queued) {
    if (validKeys.has(task.key)) {
      state.voiceAudioQueue.push(task);
    } else {
      task.cancel?.();
    }
  }
}

async function requestVoiceSegmentAudio(segment) {
  let response;
  try {
    response = await sendRuntimeMessageWithTimeout(
      {
        type: "localtube.synthesizeSpeech",
        settings: state.settings,
        payload: {
          text: segment.text,
          language: state.settings.targetLanguage,
          ttsEngine: state.settings.ttsEngine || DEFAULT_SETTINGS.ttsEngine,
          voice: state.settings.voiceId || "auto",
          rate: computeVoiceRequestRate(segment),
          targetDuration: computeVoiceSynthesisDuration(segment),
          maxFitRate: voiceTotalMaxRate(segment)
        }
      },
      35000,
      "本地 TTS 生成超时"
    );
  } catch (error) {
    state.localTtsUnavailableUntil = Date.now() + 60000;
    throw error;
  }
  if (!response?.ok || !response.payload?.dataUrl) {
    state.localTtsUnavailableUntil = Date.now() + 60000;
    throw new Error(response?.error || "本地 TTS 没有返回音频");
  }
  return response.payload;
}

function computeVoiceRequestRate(segment) {
  return clampNumber(state.settings.voiceRate, 0.6, 1.2, 1);
}

function estimateSpeechSeconds(text, language) {
  const value = String(text || "").trim();
  if (!value) {
    return 0.8;
  }
  const cjkChars = (value.match(/[\u3400-\u9fff]/g) || []).length;
  const punctuationPauses = (value.match(/[，。！？；：,.!?;:]/g) || []).length * 0.08;
  if (cjkChars >= Math.max(4, value.length * 0.35) || normalizeLanguagePrefixLocal(language) === "zh") {
    return Math.max(0.8, cjkChars / 4.4 + punctuationPauses);
  }
  const words = value.split(/\s+/).filter(Boolean).length || Math.max(1, Math.ceil(value.length / 7));
  return Math.max(0.8, words / 2.7 + punctuationPauses);
}

function rememberVoiceAudio(key, payload) {
  state.voiceAudioCache.set(key, payload);
  const maxItems = 48;
  while (state.voiceAudioCache.size > maxItems) {
    const oldestKey = state.voiceAudioCache.keys().next().value;
    state.voiceAudioCache.delete(oldestKey);
  }
}

function scheduleVoicePrefetchWindow(currentTime) {
  if (!state.settings.voiceEnabled || !state.voiceSegments.length) {
    return;
  }
  let count = 0;
  const windowEnd = currentTime + VOICE_PREFETCH_WINDOW_SECONDS;
  for (const segment of state.voiceSegments) {
    if (voiceSegmentPlaybackEnd(segment) < currentTime - 0.1) {
      continue;
    }
    if (segment.start > windowEnd || count >= VOICE_PREFETCH_MAX_SEGMENTS) {
      break;
    }
    getVoiceSegmentAudio(segment).catch(() => {});
    count += 1;
  }
}

async function prewarmVoiceAroundTime(time, operationId) {
  if (!state.settings.voiceEnabled || !state.voiceSegments.length) {
    return;
  }
  const firstSegment = findVoiceSegmentAtOrAfter(time);
  if (!firstSegment) {
    return;
  }
  const firstAudio = getVoiceSegmentAudio(firstSegment, { priority: true }).catch(() => null);
  const rollingSegments = state.voiceSegments
    .filter((segment) => segment.key !== firstSegment.key && voiceSegmentPlaybackEnd(segment) >= time - 0.05 && segment.start <= time + 6)
    .slice(0, Math.max(0, VOICE_PREFETCH_MAX_SEGMENTS - 1));
  for (const segment of rollingSegments) {
    getVoiceSegmentAudio(segment).catch(() => null);
  }
  scheduleVoicePrefetchWindow(time);
  await Promise.race([firstAudio, delay(VOICE_FIRST_CUE_WAIT_MS)]);
  assertOperationActive(operationId);
}

function voiceWarmupText(language) {
  const prefix = normalizeLanguagePrefixLocal(language);
  return {
    zh: "准备",
    ja: "準備",
    ko: "준비",
    es: "Listo",
    fr: "Prêt",
    de: "Bereit",
    it: "Pronto",
    pt: "Pronto",
    ru: "Готово",
    ar: "جاهز"
  }[prefix] || "Ready";
}

function beginVoiceEngineWarmup(operationId) {
  if (
    state.operationId !== operationId ||
    !state.settings.voiceEnabled ||
    Date.now() < state.localTtsUnavailableUntil
  ) {
    return null;
  }
  const key = `${state.settings.ttsEngine || DEFAULT_SETTINGS.ttsEngine}|${state.settings.targetLanguage}|${state.settings.voiceId || "auto"}`;
  if (state.voiceWarmupKey === key && state.voiceWarmupPromise) {
    return state.voiceWarmupPromise;
  }
  if (state.voiceWarmupKey === key && Date.now() - state.voiceWarmupAt < VOICE_WARMUP_TTL_MS) {
    return null;
  }

  const settings = { ...state.settings };
  state.voiceWarmupKey = key;
  state.voiceWarmupAt = 0;
  const promise = sendRuntimeMessageWithTimeout(
    {
      type: "localtube.synthesizeSpeech",
      settings,
      payload: {
        text: voiceWarmupText(settings.targetLanguage),
        language: settings.targetLanguage,
        ttsEngine: settings.ttsEngine || DEFAULT_SETTINGS.ttsEngine,
        voice: settings.voiceId || "auto",
        rate: clampNumber(settings.voiceRate, 0.6, 1.4, 1),
        targetDuration: 0.55
      }
    },
    12000,
    "本地 TTS 预热超时"
  )
    .then((response) => {
      if (response?.ok && response.payload?.dataUrl && state.voiceWarmupKey === key) {
        state.voiceWarmupAt = Date.now();
      }
      return null;
    })
    .catch(() => null)
    .finally(() => {
      if (state.voiceWarmupPromise === promise) {
        state.voiceWarmupPromise = null;
      }
    });
  state.voiceWarmupPromise = promise;
  return promise;
}

function voiceCacheKey(segment) {
  return [
    state.settings.targetLanguage,
    state.settings.ttsEngine || DEFAULT_SETTINGS.ttsEngine,
    state.settings.voiceId || "auto",
    computeVoiceRequestRate(segment).toFixed(2),
    Number(segment.start || 0).toFixed(3),
    computeVoiceSynthesisDuration(segment).toFixed(3),
    segment.key,
    segment.text
  ].join("|");
}

function speakSegmentWithBrowserTts(segment, playbackGeneration = beginVoicePlaybackAttempt()) {
  if (state.dubTrackPreviewActive || !window.speechSynthesis || !segment?.text || !state.running || state.video?.paused) {
    return;
  }
  if (!isVoicePlaybackAttemptCurrent(segment, playbackGeneration)) {
    return;
  }
  stopActiveVoiceAudio();
  stopActiveBrowserSpeech();
  state.activeVoiceCueKey = segment.key;
  state.activeBrowserVoiceSegment = segment;
  const utterance = new SpeechSynthesisUtterance(segment.text);
  utterance.lang = state.settings.targetLanguage;
  utterance.rate = computeBrowserVoiceRate(segment);
  utterance.pitch = state.settings.voicePitch;
  const voice = pickBrowserVoice(state.settings.targetLanguage, state.settings.voiceId);
  if (voice) {
    utterance.voice = voice;
  }
  utterance.onstart = () => {
    if (!isVoicePlaybackAttemptCurrent(segment, playbackGeneration)) {
      window.speechSynthesis.cancel();
      return;
    }
    state.spokenCueIndex = segment.startCueIndex;
    state.spokenVoiceSegmentKey = segment.key;
    state.spokenVoiceSegmentKeys.add(segment.key);
    rememberSpokenVoiceText(segment);
    state.speechActive = true;
    setOriginalMutedForDubbing(Boolean(state.settings.muteOriginal));
  };
  utterance.onend = () => {
    if (!isVoicePlaybackAttemptCurrent(segment, playbackGeneration) || state.activeBrowserVoiceSegment?.key !== segment.key) {
      return;
    }
    state.speechActive = false;
    state.activeBrowserVoiceSegment = null;
    if (state.activeVoiceCueKey === segment.key) {
      state.activeVoiceCueKey = "";
    }
    setOriginalMutedForDubbing(false);
  };
  utterance.onerror = () => {
    if (!isVoicePlaybackAttemptCurrent(segment, playbackGeneration) || state.activeBrowserVoiceSegment?.key !== segment.key) {
      return;
    }
    state.speechActive = false;
    state.activeBrowserVoiceSegment = null;
    if (state.activeVoiceCueKey === segment.key) {
      state.activeVoiceCueKey = "";
    }
    if (state.spokenVoiceSegmentKey === segment.key) {
      state.spokenCueIndex = -1;
      state.spokenVoiceSegmentKey = "";
      state.spokenVoiceSegmentKeys.delete(segment.key);
    }
    setOriginalMutedForDubbing(false);
  };
  const speak = () => {
    state.browserVoiceStartTimer = 0;
    if (
      isVoicePlaybackAttemptCurrent(segment, playbackGeneration) &&
      state.activeBrowserVoiceSegment?.key === segment.key &&
      state.activeVoiceCueKey === segment.key &&
      state.running &&
      !state.dubTrackPreviewActive &&
      !state.video?.paused &&
      isVoiceSegmentCurrent(segment)
    ) {
      window.speechSynthesis.speak(utterance);
    } else if (state.activeVoiceCueKey === segment.key) {
      state.activeVoiceCueKey = "";
      if (state.activeBrowserVoiceSegment?.key === segment.key) {
        state.activeBrowserVoiceSegment = null;
      }
    }
  };
  const waitMs = state.video ? Math.max(0, ((segment.start - state.video.currentTime - voiceSyncTiming().startEarly) / Math.max(0.25, state.video.playbackRate || 1)) * 1000) : 0;
  if (waitMs > 0) {
    state.browserVoiceStartTimer = setTimeout(speak, Math.min(waitMs, VOICE_LEAD_SECONDS * 1000));
  } else {
    speak();
  }
}

function computeBrowserVoiceRate(segment) {
  const now = Math.max(Number(segment?.start || 0), Number(state.video?.currentTime || 0));
  const naturalEnd = Math.max(Number(segment?.start || 0) + 0.35, Number(segment?.end || voiceSegmentPlaybackEnd(segment)));
  const remainingSeconds = Math.max(0.35, naturalEnd - now);
  const baseRate = clampNumber(state.settings.voiceRate, 0.6, 1.4, 1);
  const estimatedSeconds = estimateSpeechSeconds(segment.text, state.settings.targetLanguage);
  return clampNumber(baseRate * (estimatedSeconds / remainingSeconds), baseRate, 1.3, baseRate);
}

function pickBrowserVoice(language, voiceId = "auto") {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  const prefix = normalizeLanguagePrefixLocal(language);
  if (voiceId && voiceId !== "auto") {
    const selected =
      voices.find((voice) => voice.name === voiceId) ||
      voices.find((voice) => voice.name.toLowerCase().includes(String(voiceId).toLowerCase()));
    if (selected) {
      return selected;
    }
  }
  return (
    voices.find((voice) => normalizeLanguagePrefixLocal(voice.lang) === prefix && voice.localService) ||
    voices.find((voice) => normalizeLanguagePrefixLocal(voice.lang) === prefix) ||
    null
  );
}

function setOriginalMutedForDubbing(shouldMute) {
  if (!state.video || !state.mutedByLocalTube) {
    return;
  }
  state.video.muted = state.dubTrackPreviewActive && state.dubTrackMixOriginal
    ? true
    : shouldMute
      ? true
      : Boolean(state.settings.muteOriginal);
  state.video.volume = clampNumber(state.settings.originalVolume, 0, 1, DEFAULT_SETTINGS.originalVolume);
}

function attachCaptionOverlay() {
  const player = document.querySelector("#movie_player .html5-video-container") || document.querySelector("#movie_player") || document.body;
  if (player && state.caption && state.caption.parentElement !== player) {
    const style = getComputedStyle(player);
    if (style.position === "static") {
      player.style.position = "relative";
    }
    player.append(state.caption);
  }
}

async function resolveVideoCaptions(operationId) {
  const videoId = getCurrentVideoId();
  if (!videoId) {
    return {
      status: "unknown",
      cues: [],
      track: null,
      error: "当前页面没有找到 YouTube 视频 ID。"
    };
  }

  setStatus("正在读取 YouTube 字幕...", "working");
  const pageResultPromise = resolveVideoCaptionsFromPage(videoId).catch((error) => ({
    status: "unknown",
    cues: [],
    track: null,
    error: `页面字幕读取失败：${error.message || String(error)}`
  }));
  const backoff = getCaptionFailureBackoff(videoId);

  const pageFastResult = await withTimeoutResult(pageResultPromise, CAPTION_FAST_TIMEOUT_MS, "页面字幕快速读取超时");
  assertOperationActive(operationId);

  if (pageFastResult?.status === "captions" && pageFastResult?.cues?.length) {
    return pageFastResult;
  }

  let engineResult = null;
  if (backoff) {
    engineResult = captionBackoffResult(backoff);
  } else {
    setStatus("正在通过本地 Engine 读取字幕...", "working");
    const engineResultPromise = fetchEngineCaptions(videoId).catch((error) => ({
      status: "unknown",
      cues: [],
      track: null,
      code: classifyCaptionErrorCode(error?.code || error?.message || error),
      retryAfterSeconds: Number(error?.retryAfterSeconds || 0) || 0,
      error: friendlyErrorMessage(error)
    }));
    const engineTimeoutMs = captionEngineWaitTimeout(
      pageFastResult,
      CAPTION_ENGINE_PAGE_FALLBACK_TIMEOUT_MS,
      CAPTION_TOTAL_TIMEOUT_MS
    );
    engineResult = await withTimeoutResult(engineResultPromise, engineTimeoutMs, "本地字幕 Engine 读取超时");
    assertOperationActive(operationId);
    rememberCaptionFailure(videoId, engineResult);
  }
  if (
    engineResult?.status === "captions" &&
    engineResult.cues?.length &&
    isTargetLanguageTrack(engineResult.track, state.settings.targetLanguage)
  ) {
    return engineResult;
  }

  const pageResult = pageFastResult?.error === "页面字幕快速读取超时"
    ? await withTimeoutResult(pageResultPromise, 1000, "页面字幕读取超时")
    : pageFastResult;
  const bestCaptionResult = pickBestResolvedCaptionResult([engineResult, pageResult], state.settings.targetLanguage);
  if (bestCaptionResult) {
    return bestCaptionResult;
  }
  if (engineResult?.code === "YOUTUBE_RATE_LIMITED") {
    return {
      status: "unknown",
      cues: [],
      track: null,
      code: engineResult.code,
      retryAfterSeconds: Number(engineResult.retryAfterSeconds || 0) || 0,
      error: buildCaptionReadFailureMessage(pageResult, engineResult)
    };
  }
  if (pageResult.status === "no_captions" && pageResult.confirmedNoCaptions) {
    return pageResult;
  }
  if (engineResult.status === "no_captions" && pageResult.status !== "captions") {
    return engineResult;
  }
  if (pageResult.status === "no_captions" && engineResult.status === "no_captions") {
    return engineResult;
  }

  return {
    status: "unknown",
    cues: [],
    track: null,
    code: engineResult?.code || classifyCaptionErrorCode(engineResult?.error || pageResult?.error),
    retryAfterSeconds: Number(engineResult?.retryAfterSeconds || 0) || 0,
    error: buildCaptionReadFailureMessage(pageResult, engineResult)
  };
}

function captionFailureKey(videoId) {
  return [
    String(videoId || ""),
    String(state.settings.targetLanguage || DEFAULT_SETTINGS.targetLanguage)
  ].join("|");
}

function getCaptionFailureBackoff(videoId) {
  const key = captionFailureKey(videoId);
  const item = state.captionFailureBackoff.get(key);
  if (!item) {
    return null;
  }
  if (Date.now() >= item.until) {
    state.captionFailureBackoff.delete(key);
    return null;
  }
  return {
    ...item,
    remainingSeconds: Math.max(1, Math.ceil((item.until - Date.now()) / 1000))
  };
}

function rememberCaptionFailure(videoId, result) {
  const code = result?.code || classifyCaptionErrorCode(result?.error);
  const reportedBackoffMs = Math.max(0, Number(result?.retryAfterSeconds || 0) || 0) * 1000;
  const backoffMs = reportedBackoffMs || CAPTION_FAILURE_BACKOFF_MS[code];
  if (!backoffMs) {
    return;
  }
  state.captionFailureBackoff.set(captionFailureKey(videoId), {
    code,
    error: result?.error || "",
    retryAfterSeconds: Math.ceil(backoffMs / 1000),
    until: Date.now() + backoffMs
  });
}

function captionBackoffResult(backoff) {
  return {
    status: backoff.code === "NO_PUBLIC_CAPTIONS" ? "no_captions" : "unknown",
    cues: [],
    track: null,
    code: backoff.code,
    retryAfterSeconds: backoff.remainingSeconds,
    error: captionBackoffMessage(backoff)
  };
}

function captionBackoffMessage(backoff) {
  if (backoff.code === "YOUTUBE_RATE_LIMITED") {
    return `YouTube 字幕服务正在限流，已暂停当前视频字幕请求约 ${backoff.remainingSeconds} 秒，稍后会自动再试。`;
  }
  if (backoff.code === "NO_PUBLIC_CAPTIONS") {
    return `当前视频暂时没有公开可读取字幕，约 ${backoff.remainingSeconds} 秒后可再次检查。`;
  }
  if (backoff.code === "VIDEO_UNAVAILABLE") {
    return `当前视频不可用或受访问限制，约 ${backoff.remainingSeconds} 秒后可再次检查。`;
  }
  if (backoff.code === "CAPTION_EMPTY") {
    return `字幕轨道返回空内容，约 ${backoff.remainingSeconds} 秒后可再次检查。`;
  }
  return backoff.error || "字幕暂时不可用，稍后会自动再试。";
}

function cancelCaptionAutoRetry() {
  if (state.captionRetryTimer) {
    clearInterval(state.captionRetryTimer);
  }
  state.captionRetryTimer = 0;
  state.captionRetryVideoId = "";
  state.captionRetryUntil = 0;
}

async function resumeVideoAfterCaptionDelay(shouldResume) {
  if (!shouldResume || !state.video || !state.video.paused) {
    return false;
  }
  await state.video.play().catch(() => {});
  return !state.video.paused;
}

function scheduleCaptionAutoRetry(videoId, retryAfterSeconds, resumeOnSuccess) {
  cancelCaptionAutoRetry();
  const delaySeconds = Math.max(3, Math.ceil(Number(retryAfterSeconds || 0) || 300));
  state.captionRetryVideoId = String(videoId || "");
  state.captionRetryUntil = Date.now() + delaySeconds * 1000;

  const tick = async () => {
    if (!state.captionRetryTimer || getCurrentVideoId() !== state.captionRetryVideoId || state.running || state.busy) {
      cancelCaptionAutoRetry();
      return;
    }
    const remainingSeconds = Math.max(0, Math.ceil((state.captionRetryUntil - Date.now()) / 1000));
    if (remainingSeconds > 0) {
      setStatus(`YouTube 字幕服务暂时繁忙，${remainingSeconds} 秒后自动重试一次。`, "working");
      return;
    }

    const retryVideoId = state.captionRetryVideoId;
    cancelCaptionAutoRetry();
    state.captionFailureBackoff.delete(captionFailureKey(retryVideoId));
    await startDubbing({ autoRetry: true, resumeOnSuccess });
  };

  state.captionRetryTimer = window.setInterval(tick, 1000);
  tick();
}

function pickBestResolvedCaptionResult(results, targetLanguage) {
  const captions = (Array.isArray(results) ? results : []).filter((result) => result?.status === "captions" && result.cues?.length);
  if (!captions.length) {
    return null;
  }

  return captions
    .map((result, index) => ({
      result,
      index,
      score: resolvedCaptionResultScore(result, targetLanguage)
    }))
    .sort((a, b) => b.score - a.score || a.index - b.index)[0].result;
}

function resolvedCaptionResultScore(result, targetLanguage) {
  let score = 0;
  if (isTargetLanguageTrack(result.track, targetLanguage)) {
    score += 1000;
  }
  if (result.track?.translatedByYouTube) {
    score += 120;
  }
  if (result.source === "page-main-world" || result.track?.source === "page-main-world") {
    score += 40;
  } else if (result.source === "page-innertube-player" || result.track?.source === "page-innertube-player") {
    score += 38;
  } else if (result.source === "page-player-response" || result.track?.source === "page-player-response") {
    score += 35;
  } else if (result.source === "caption-engine" || result.track?.source === "caption-engine") {
    score += 30;
  }
  if (result.track?.kind !== "asr") {
    score += 10;
  }
  score += Math.min(20, Array.isArray(result.cues) ? result.cues.length / 50 : 0);
  return score;
}

async function fetchEngineCaptions(videoId) {
  const response = await sendRuntimeMessage({
      type: "localtube.resolveCaptions",
      settings: state.settings,
      payload: {
        videoId,
        videoUrl: location.href,
        sourceLanguage: state.settings.sourceLanguage || "auto",
        targetLanguage: state.settings.targetLanguage || "zh-CN"
      }
    })
    .catch((error) => {
      if (isExtensionContextInvalidated(error)) {
        throw error;
      }
      return { ok: false, error: friendlyErrorMessage(error) };
    });

  const payload = response?.payload || {};
  const cues = normalizeResolvedCues(payload.cues || []);
  if (response?.ok && cues.length) {
    return {
      status: "captions",
      cues,
      track: {
        source: payload.source || "caption-engine",
        languageCode: payload.translatedByYouTube
          ? state.settings.targetLanguage || payload.sourceLanguage || "auto"
          : payload.sourceLanguage || "auto",
        kind: payload.engine || "captions",
        translatedByYouTube: Boolean(payload.translatedByYouTube)
      },
      tracks: [],
      source: payload.transport || "caption-engine"
    };
  }

  const code = response?.code || payload.code || classifyCaptionErrorCode(response?.error);
  const retryAfterSeconds = Math.max(0, Number(response?.retryAfterSeconds || payload.retryAfterSeconds || 0) || 0);
  return {
    status: code === "NO_PUBLIC_CAPTIONS" || isEngineNoCaptionError(response?.error) ? "no_captions" : "unknown",
    cues: [],
    track: null,
    code,
    retryAfterSeconds,
    error: response?.error ? engineCaptionErrorMessage(response.error, code, retryAfterSeconds) : ""
  };
}

function isEngineNoCaptionError(error) {
  return /没有检测到可读取字幕|no captions|no subtitles|字幕.*不可读取/i.test(String(error || ""));
}

function classifyCaptionErrorCode(value) {
  const text = String(value || "");
  const directCode = text.match(/\b(YOUTUBE_RATE_LIMITED|NO_PUBLIC_CAPTIONS|VIDEO_UNAVAILABLE|CAPTION_EMPTY|ENGINE_TIMEOUT|CAPTION_ENGINE_UNAVAILABLE|CAPTION_FETCH_FAILED|CAPTION_ENGINE_REJECTED|CAPTION_ENGINE_HTTP_ERROR|CAPTION_ENGINE_ERROR)\b/);
  if (directCode) {
    return directCode[1];
  }
  if (/429|too many requests|rate.?limit|限流/i.test(text)) {
    return "YOUTUBE_RATE_LIMITED";
  }
  if (/video unavailable|private video|members.?only|age.?restricted|requested format is not available|视频不可用|访问受限/i.test(text)) {
    return "VIDEO_UNAVAILABLE";
  }
  if (/没有读取到可用字幕|没有检测到可读取字幕|no captions|no subtitles|subtitles are disabled|字幕.*不可读取/i.test(text)) {
    return "NO_PUBLIC_CAPTIONS";
  }
  if (/返回空内容|empty/i.test(text)) {
    return "CAPTION_EMPTY";
  }
  if (/扩展网络请求超时|timeout|timed out|超时/i.test(text)) {
    return "ENGINE_TIMEOUT";
  }
  if (/Failed to fetch|Could not establish connection|ECONNREFUSED|native.*host|host has exited|Extension context invalidated/i.test(text)) {
    return "CAPTION_ENGINE_UNAVAILABLE";
  }
  return "CAPTION_ENGINE_ERROR";
}

function engineCaptionErrorMessage(error, code = "", retryAfterSeconds = 0) {
  const message = String(error || "");
  const normalizedCode = code || classifyCaptionErrorCode(message);
  if (normalizedCode === "YOUTUBE_RATE_LIMITED") {
    const waitSeconds = Math.max(1, Number(retryAfterSeconds || 0) || 300);
    return `YouTube 字幕服务暂时繁忙，已暂停重复请求；约 ${Math.ceil(waitSeconds)} 秒后自动重试一次。`;
  }
  if (normalizedCode === "VIDEO_UNAVAILABLE") {
    return "当前视频不可用、受访问限制，或 YouTube 没有向字幕 Engine 提供可读取的视频信息。";
  }
  if (normalizedCode === "NO_PUBLIC_CAPTIONS" || isEngineNoCaptionError(message)) {
    return "当前视频没有公开可读取字幕。需要配音时请开启“无字幕时自动转写”。";
  }
  if (normalizedCode === "CAPTION_EMPTY") {
    return "字幕轨道返回空内容，暂时无法生成配音。请稍后重试，或开启“无字幕时自动转写”。";
  }
  if (normalizedCode === "ENGINE_TIMEOUT") {
    return "本地字幕 Engine 读取超时。";
  }
  if (normalizedCode === "CAPTION_ENGINE_UNAVAILABLE") {
    return "本地字幕服务暂时未连接，正在尝试自动恢复。";
  }
  return `yt-dlp Engine 字幕读取失败：${message}`;
}

function buildCaptionReadFailureMessage(pageResult, engineResult) {
  const errors = [pageResult?.error, engineResult?.error].filter(Boolean).join("；");
  const code = engineResult?.code || classifyCaptionErrorCode(errors);
  console.warn("[LocalTube Dub] caption read failure", { pageResult, engineResult, code });
  if (code === "YOUTUBE_RATE_LIMITED") {
    return engineResult?.error || "YouTube 字幕服务暂时繁忙，已暂停重复请求，稍后自动重试一次。";
  }
  if (code === "VIDEO_UNAVAILABLE") {
    return "当前视频不可用或受访问限制，无法读取字幕，也不能据此判断为无字幕视频。";
  }
  if (code === "NO_PUBLIC_CAPTIONS") {
    return "当前视频没有公开可读取字幕。请开启“无字幕时自动转写”，或换一个带公开字幕的视频重试。";
  }
  if (code === "CAPTION_EMPTY") {
    return "字幕轨道返回空内容，暂时无法生成配音。请稍后重试，或开启“无字幕时自动转写”。";
  }
  if (code === "CAPTION_ENGINE_UNAVAILABLE") {
    return "本地字幕服务暂时未就绪，已自动尝试恢复。请重新点击开始翻译；如仍失败，请打开“启动说明”完成一次安装。";
  }
  if (/需要先启动本地 yt-dlp Engine/i.test(errors)) {
    return errors;
  }
  if (code === "ENGINE_TIMEOUT" || /超时|timeout/i.test(errors)) {
    return "字幕读取耗时较长，本次已自动停止等待。请稍后重试，或开启“无字幕时自动转写”。";
  }
  if (/yt-dlp Engine|HTTP Engine|Native Engine|yt-dlp 没有读取到可用字幕/i.test(errors)) {
    return "字幕 Engine 暂时没有返回可用字幕，页面字幕也没有读到。请稍后重试，或开启“无字幕时自动转写”。";
  }
  return "没有读取到可翻译字幕。请开启“无字幕时自动转写”，或换一个带公开字幕的视频重试。";
}

function normalizeResolvedCues(rawCues) {
  return (Array.isArray(rawCues) ? rawCues : [])
    .map((cue, index) => {
      const start = Number(cue?.start || 0);
      const end = Number(cue?.end || start + 1.8);
      return {
        id: String(cue?.id || index),
        start,
        end: Math.max(end, start + 0.8),
        text: String(cue?.text || "").replace(/\s+/g, " ").trim()
      };
    })
    .filter((cue) => cue.text);
}

async function resolveVideoCaptionsFromPage(videoId) {
  const sourceResult = await collectCaptionTracks(videoId);
  const errors = [...sourceResult.errors];
  if (!sourceResult.tracks.length) {
    return {
      status: sourceResult.hadUsableSource ? "no_captions" : "unknown",
      cues: [],
      track: null,
      confirmedNoCaptions: sourceResult.hadUsableSource,
      error: sourceResult.hadUsableSource
        ? "已确认这个视频没有可读取的 YouTube 字幕。"
        : `字幕源读取失败：${errors.join("；") || "YouTube 没有返回字幕源"}`
    };
  }

  const tracksToTry = limitCaptionTrackAttempts(
    rankCaptionTracks(sourceResult.tracks, preferredCaptionLanguage()),
    state.settings.targetLanguage
  );
  for (const track of tracksToTry) {
    try {
      const cues = await loadCaptionCues(track);
      if (cues.length) {
        return {
          status: "captions",
          cues,
          track,
          tracks: sourceResult.tracks,
          source: track.source || "unknown"
        };
      }
    } catch (error) {
      errors.push(`${track.languageCode || "unknown"}:${error.message || String(error)}`);
    }
  }

  return {
    status: "unreadable",
    cues: [],
    track: null,
    tracks: sourceResult.tracks,
    error: `检测到 ${sourceResult.tracks.length} 个字幕轨道，但都没有读取到字幕内容：${errors.join("；") || "未知错误"}`
  };
}

async function collectCaptionTracks(videoId) {
  const collected = [];
  const errors = [];
  let hadUsableSource = false;

  const addSourceTracks = (source, tracks) => {
    hadUsableSource = true;
    const normalizedTracks = normalizeCaptionTracks(tracks, source);
    collected.push(...normalizedTracks, ...createTranslatedCaptionTracks(normalizedTracks, state.settings.targetLanguage));
  };

  const pageSnapshot = await requestPageSnapshot(videoId).catch(() => null);
  if (pageSnapshot?.playerResponse && responseMatchesVideo(pageSnapshot.playerResponse, videoId)) {
    addSourceTracks("page-main-world", pageSnapshot.playerResponse.captions?.playerCaptionsTracklistRenderer?.captionTracks || []);
  } else {
    errors.push("page-main-world 未返回当前视频字幕数据");
  }

  const pageResponse = getPlayerResponse(videoId);
  if (pageResponse) {
    addSourceTracks("page-player-response", pageResponse.captions?.playerCaptionsTracklistRenderer?.captionTracks || []);
  } else {
    errors.push("page-player-response 未找到当前视频响应");
  }

  if (!collected.length && pageSnapshot?.videoId === videoId) {
    const innertubeResponse = await fetchInnertubePlayerResponse(pageSnapshot.innertubeConfig, videoId).catch((error) => {
      errors.push(`page-innertube-player ${error.message || String(error)}`);
      return null;
    });
    if (innertubeResponse && responseMatchesVideo(innertubeResponse, videoId)) {
      addSourceTracks(
        "page-innertube-player",
        innertubeResponse.captions?.playerCaptionsTracklistRenderer?.captionTracks || []
      );
    } else if (pageSnapshot?.innertubeConfig?.apiKey) {
      errors.push("page-innertube-player 未返回当前视频字幕数据");
    }
  }

  return {
    tracks: dedupeCaptionTracks(collected),
    hadUsableSource,
    errors
  };
}

async function fetchInnertubePlayerResponse(config, videoId) {
  const request = makeInnertubePlayerRequest(config, videoId);
  if (!request) {
    return null;
  }
  const response = await youtubeFetch(request.url, {
    method: "POST",
    headers: request.headers,
    body: request.body
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status || 0}`);
  }
  try {
    return JSON.parse(response.text || "{}");
  } catch (error) {
    throw new Error("返回了无效播放器数据");
  }
}

function normalizeCaptionTracks(tracks, source) {
  return (Array.isArray(tracks) ? tracks : [])
    .map((track) => ({
      ...track,
      source,
      baseUrl: String(track.baseUrl || ""),
      languageCode: String(track.languageCode || track.lang || ""),
      kind: String(track.kind || "")
    }))
    .filter((track) => track.baseUrl && track.languageCode);
}

function createTranslatedCaptionTracks(tracks, targetLanguage) {
  const tlangCandidates = youtubeTranslationLanguages(targetLanguage);
  if (!tlangCandidates.length) {
    return [];
  }

  const sourceTracks = (Array.isArray(tracks) ? tracks : []).filter(
    (track) => track?.baseUrl && !isTargetLanguageTrack(track, targetLanguage)
  );
  const sourceTrack = pickCaptionTrack(sourceTracks, state.settings.sourceLanguage) || sourceTracks[0];
  if (!sourceTrack) {
    return [];
  }
  return tlangCandidates.map((tlang) => ({
    ...sourceTrack,
    source: `${sourceTrack.source || "caption"}-youtube-translate`,
    baseUrl: addQuery(sourceTrack.baseUrl, { tlang }),
    languageCode: targetLanguage,
    originalLanguageCode: sourceTrack.languageCode,
    translationLanguage: tlang,
    translatedByYouTube: true,
    kind: sourceTrack.kind || ""
  }));
}

function youtubeTranslationLanguage(language) {
  return youtubeTranslationLanguages(language)[0] || "";
}

function youtubeTranslationLanguages(language) {
  const value = String(language || "").trim();
  if (!value || value === "auto") {
    return [];
  }
  const lower = value.toLowerCase();
  if (lower === "zh-cn" || lower === "zh-hans") {
    return ["zh", "zh-Hans", "zh-CN"];
  }
  if (lower === "zh-tw" || lower === "zh-hant") {
    return ["zh-TW", "zh-Hant"];
  }
  if (lower === "pt-br") {
    return ["pt", "pt-BR"];
  }
  return Array.from(new Set([lower.split(/[-_]/)[0] || lower, value]));
}

function preferredCaptionLanguage() {
  return state.settings.targetLanguage || state.settings.sourceLanguage || "auto";
}

function isTargetLanguageTrack(track, targetLanguage) {
  if (!track || !targetLanguage) {
    return false;
  }
  return normalizeCaptionLanguageLocal(track.languageCode) === normalizeCaptionLanguageLocal(targetLanguage);
}

function normalizeCaptionLanguageLocal(language) {
  return normalizeCaptionLanguage(language);
}

function useCueTextAsTranslation(cue) {
  return {
    ...cue,
    translatedText: cue.translatedText || cue.text || ""
  };
}

function dedupeCaptionTracks(tracks) {
  const seen = new Set();
  const unique = [];
  for (const track of tracks) {
    const key = captionTrackKey(track);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    unique.push(track);
  }
  return unique;
}

function captionTrackKey(track) {
  try {
    const url = new URL(track.baseUrl);
    return [
      url.origin,
      url.pathname,
      url.searchParams.get("v") || "",
      url.searchParams.get("lang") || track.languageCode || "",
      url.searchParams.get("name") || track.name?.simpleText || "",
      url.searchParams.get("kind") || track.kind || "",
      normalizeCaptionBaseUrl(track.baseUrl)
    ].join("|");
  } catch (error) {
    return [track.languageCode || "", track.kind || "", track.baseUrl || ""].join("|");
  }
}

function normalizeCaptionBaseUrl(baseUrl) {
  try {
    const url = new URL(baseUrl);
    url.searchParams.sort();
    return url.toString();
  } catch (error) {
    return String(baseUrl || "");
  }
}

function rankCaptionTracks(tracks, preferredLanguage) {
  const reliableFirst = [...tracks].sort((a, b) => captionTrackReliability(b) - captionTrackReliability(a));
  const preferred = pickCaptionTrack(reliableFirst, preferredLanguage);
  const scored = tracks.map((track, index) => ({
    track,
    index,
    score: captionTrackScore(track, preferred, preferredLanguage)
  }));
  return scored.sort((a, b) => b.score - a.score || a.index - b.index).map((item) => item.track);
}

function captionTrackScore(track, preferredTrack, preferredLanguage) {
  let score = 0;
  if (track === preferredTrack) {
    score += 100;
  }
  const language = normalizeLanguagePrefixLocal(track.languageCode);
  const preferred = normalizeLanguagePrefixLocal(preferredLanguage);
  if (preferred && language === preferred) {
    score += 80;
  }
  if (track.kind !== "asr") {
    score += 30;
  }
  if (language === "en") {
    score += 10;
  }
  if (track.source === "page-main-world") {
    score += 6;
  } else if (track.source === "page-innertube-player") {
    score += 5.5;
  } else if (track.source === "page-player-response") {
    score += 5;
  }
  score += Math.min(8, captionBaseUrlParamCount(track.baseUrl || "") / 2);
  return score;
}

function captionTrackReliability(track) {
  const sourceScore =
    track.source === "page-main-world"
      ? 40
      : track.source === "page-innertube-player"
        ? 38
        : track.source === "page-player-response"
          ? 35
          : 10;
  return sourceScore + Math.min(20, captionBaseUrlParamCount(track.baseUrl || ""));
}

function captionBaseUrlParamCount(baseUrl) {
  try {
    return Array.from(new URL(baseUrl).searchParams.keys()).length;
  } catch (error) {
    return 0;
  }
}

function normalizeLanguagePrefixLocal(language) {
  const value = String(language || "").trim().toLowerCase();
  if (!value || value === "auto") {
    return "";
  }
  return value.split(/[-_]/)[0] || "";
}

async function requestPageSnapshot(videoId = getCurrentVideoId(), timeoutMs = 700) {
  const cached = state.pageSnapshotCache;
  if (cached?.videoId === videoId && Date.now() - cached.time < 1200) {
    return cached.snapshot;
  }

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const snapshot = await requestPageSnapshotOnce(videoId, timeoutMs);
    if (snapshot?.playerResponse && responseMatchesVideo(snapshot.playerResponse, videoId)) {
      return snapshot;
    }
    if (snapshot?.videoId === videoId && snapshot?.innertubeConfig?.apiKey) {
      state.pageSnapshotCache = {
        videoId,
        time: Date.now(),
        snapshot
      };
      return snapshot;
    }
    await delay(250 + attempt * 250);
  }

  return null;
}

function requestPageSnapshotOnce(videoId, timeoutMs) {
  return new Promise((resolve) => {
    const requestId = `page-state-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    const cleanup = () => {
      clearTimeout(timer);
      document.removeEventListener("localtube-dub:page-state", onDomResponse);
      window.removeEventListener("message", onWindowResponse);
    };
    const timer = setTimeout(() => {
      cleanup();
      resolve(null);
    }, timeoutMs);

    const acceptSnapshot = (payload) => {
      if (payload?.requestId !== requestId) {
        return;
      }
      cleanup();

      let snapshot = null;
      try {
        snapshot = JSON.parse(payload.snapshot || "{}");
      } catch (error) {
        snapshot = null;
      }

      if (snapshot?.videoId === videoId) {
        state.pageSnapshotCache = {
          videoId,
          time: Date.now(),
          snapshot
        };
        resolve(snapshot);
        return;
      }

      resolve(null);
    };

    const onDomResponse = (event) => acceptSnapshot(event?.detail);
    const onWindowResponse = (event) => {
      if (event.source !== window || event.origin !== location.origin || event.data?.source !== "localtube-dub:page-state") {
        return;
      }
      acceptSnapshot(event.data);
    };

    document.addEventListener("localtube-dub:page-state", onDomResponse);
    window.addEventListener("message", onWindowResponse);
    document.dispatchEvent(
      new CustomEvent("localtube-dub:request-page-state", {
        detail: { requestId, videoId }
      })
    );
    window.postMessage(
      {
        source: "localtube-dub:request-page-state",
        requestId,
        videoId
      },
      location.origin
    );
  });
}

function getPlayerResponse(videoId = getCurrentVideoId()) {
  const responses = [];
  const scripts = Array.from(document.scripts, (script) => script.textContent || "");
  for (const script of scripts) {
    let markerIndex = script.indexOf("ytInitialPlayerResponse");
    while (markerIndex >= 0) {
      const start = script.indexOf("{", markerIndex);
      if (start < 0) {
        break;
      }

      const json = extractBalancedJson(script, start);
      if (!json) {
        break;
      }

      try {
        const response = JSON.parse(json);
        responses.push(response);
        if (responseMatchesVideo(response, videoId)) {
          return response;
        }
      } catch (error) {
        // Keep scanning; YouTube can embed several JSON-shaped objects.
      }
      markerIndex = script.indexOf("ytInitialPlayerResponse", start + json.length);
    }
  }

  if (videoId) {
    return null;
  }

  return responses.find((response) => response?.captions?.playerCaptionsTracklistRenderer?.captionTracks?.length) || responses[0] || null;
}

function getCurrentVideoId() {
  if (location.pathname !== "/watch") {
    return "";
  }
  return new URLSearchParams(location.search).get("v") || "";
}

async function loadCaptionCues(track) {
  const candidates = makeCaptionFetchCandidates(track.baseUrl);
  const errors = [];

  for (const url of candidates) {
    const response = await youtubeFetch(url);
    if (!response.ok) {
      errors.push(`${captionFetchLabel(url)} HTTP ${response.status || 0}${response.error ? ` ${response.error}` : ""}`);
      continue;
    }

    const cues = parseCaptionPayload(response.text);
    if (cues.length) {
      console.debug("[LocalTube Dub] caption loaded", {
        source: track.source,
        languageCode: track.languageCode,
        kind: track.kind,
        format: captionFetchLabel(url),
        cues: cues.length
      });
      return cues;
    }
    errors.push(`${captionFetchLabel(url)} empty:${String(response.text || "").slice(0, 80).replace(/\s+/g, " ")}`);
  }

  throw new Error(`字幕轨道存在，但没有读取到字幕内容（${errors.join(" / ") || "unknown"}）。`);
}

function captionFetchLabel(url) {
  try {
    return new URL(url).searchParams.get("fmt") || "raw";
  } catch (error) {
    return "raw";
  }
}

function isYouTubeAdShowing() {
  return Boolean(
    document.querySelector(".ad-showing") ||
      document.querySelector(".ytp-ad-player-overlay") ||
      document.querySelector(".ytp-ad-preview-container") ||
      document.querySelector(".ytp-ad-text")
  );
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function beginChromeTranslationWarmupFromUserGesture() {
  const targetLanguage = normalizeChromeTranslatorLanguage(state.settings.targetLanguage);
  if (!targetLanguage) {
    return;
  }

  if (targetLanguage !== "en") {
    const sourceLanguage = normalizeChromeTranslatorLanguage(state.settings.sourceLanguage) || "en";
    prepareChromeTranslator(sourceLanguage, targetLanguage, {
      silent: state.settings.provider !== "chrome-translator"
    }).catch(() => null);
  }
  prepareChromeLanguageDetector().catch(() => null);
}

function prepareChromeTranslator(sourceLanguage, targetLanguage, options = {}) {
  const source = normalizeChromeTranslatorLanguage(sourceLanguage);
  const target = normalizeChromeTranslatorLanguage(targetLanguage);
  if (!source || !target) {
    return Promise.reject(new Error("Chrome 本地翻译需要明确的源语言和目标语言。"));
  }
  if (source === target) {
    return Promise.resolve(null);
  }
  if (!("Translator" in globalThis) || typeof globalThis.Translator?.create !== "function") {
    return Promise.reject(new Error("当前 Chrome 版本不支持内置本地翻译，请升级桌面版 Chrome 或换用其他翻译服务。"));
  }

  const cacheKey = `${source}->${target}`;
  const cached = state.chromeTranslatorCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  if (!options.silent) {
    setStatus(`正在准备 Chrome 本地语言包 ${source} → ${target}...`, "working");
  }
  let creation;
  try {
    creation = globalThis.Translator.create({
      sourceLanguage: source,
      targetLanguage: target,
      monitor(monitor) {
        monitor.addEventListener("downloadprogress", (event) => {
          const percent = Math.round(clampNumber(Number(event.loaded || 0), 0, 1, 0) * 100);
          if (!options.silent) {
            setStatus(`正在下载 Chrome 本地语言包 ${percent}%`, "working");
          }
        });
      }
    });
  } catch (error) {
    return Promise.reject(normalizeChromeTranslatorError(error));
  }

  const promise = Promise.resolve(creation)
    .then((translator) => {
      if (!options.silent) {
        setStatus("Chrome 本地语言包已就绪", "");
      }
      return translator;
    })
    .catch((error) => {
      state.chromeTranslatorCache.delete(cacheKey);
      throw normalizeChromeTranslatorError(error);
    });
  state.chromeTranslatorCache.set(cacheKey, promise);
  return promise;
}

function prepareChromeLanguageDetector() {
  if (state.chromeLanguageDetectorPromise) {
    return state.chromeLanguageDetectorPromise;
  }
  if (!("LanguageDetector" in globalThis) || typeof globalThis.LanguageDetector?.create !== "function") {
    return Promise.resolve(null);
  }

  let creation;
  try {
    creation = globalThis.LanguageDetector.create();
  } catch (error) {
    return Promise.resolve(null);
  }
  state.chromeLanguageDetectorPromise = Promise.resolve(creation).catch(() => null);
  return state.chromeLanguageDetectorPromise;
}

async function translateCuesWithChromeTranslator(cues, detectedSourceLanguage) {
  const operationId = state.operationId;
  const targetLanguage = normalizeChromeTranslatorLanguage(state.settings.targetLanguage);
  let sourceLanguage = normalizeChromeTranslatorLanguage(
    state.settings.sourceLanguage === "auto" ? detectedSourceLanguage : state.settings.sourceLanguage
  );
  if (!sourceLanguage) {
    sourceLanguage = await detectChromeSourceLanguage(cues);
  }
  sourceLanguage ||= "en";

  if (sourceLanguage === targetLanguage) {
    return cues.map(useCueTextAsTranslation);
  }

  const translator = await prepareChromeTranslator(sourceLanguage, targetLanguage);
  assertOperationActive(operationId);
  if (!translator) {
    return cues.map(useCueTextAsTranslation);
  }

  const translated = [];
  for (const [index, cue] of cues.entries()) {
    assertOperationActive(operationId);
    if (index === 0 || index % 3 === 0) {
      setStatus(`Chrome 本地翻译 ${index + 1}/${cues.length}...`, "working");
    }
    const translatedText = String(await translator.translate(String(cue.text || ""))).replace(/\s+/g, " ").trim();
    translated.push({
      ...cue,
      translatedText: translatedText || cue.text || ""
    });
  }
  return translated;
}

async function detectChromeSourceLanguage(cues) {
  const detector = await prepareChromeLanguageDetector();
  if (!detector || typeof detector.detect !== "function") {
    return "";
  }
  const sample = (Array.isArray(cues) ? cues : [])
    .slice(0, 8)
    .map((cue) => String(cue?.text || ""))
    .join(" ")
    .slice(0, 1200);
  if (!sample) {
    return "";
  }
  const results = await detector.detect(sample);
  return normalizeChromeTranslatorLanguage(results?.[0]?.detectedLanguage || "");
}

function normalizeChromeTranslatorLanguage(language) {
  const value = String(language || "").trim().toLowerCase().replace(/_/g, "-");
  if (!value || value === "auto") {
    return "";
  }
  if (["zh-tw", "zh-hant", "zh-cht", "zh-hk", "zh-mo"].includes(value)) {
    return "zh-Hant";
  }
  if (["zh-cn", "zh-hans", "zh-chs"].includes(value)) {
    return "zh";
  }
  if (value === "he") {
    return "iw";
  }
  return value.split("-")[0] || "";
}

function normalizeChromeTranslatorError(error) {
  const message = String(error?.message || error || "");
  if (/user activation|notallowed|not allowed|gesture/i.test(message)) {
    return new Error("Chrome 需要一次点击来准备本地语言包，请再次点击“开始翻译”。");
  }
  if (/not supported|unsupported|unavailable|language/i.test(message)) {
    return new Error("Chrome 当前不支持这组语言的本地翻译，请换用其他翻译服务。");
  }
  return new Error(message || "Chrome 本地翻译暂时不可用。");
}

async function translateCues(cues, detectedSourceLanguage) {
  if (state.settings.provider === "chrome-translator") {
    return translateCuesWithChromeTranslator(cues, detectedSourceLanguage);
  }
  const requestId = `dub-${state.operationId}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  state.activeDubRequestIds.add(requestId);
  const response = await sendRuntimeMessageWithTimeout(
    {
      type: "localtube.providerDub",
      requestId,
      settings: state.settings,
      payload: {
        requestId,
        videoUrl: location.href,
        targetLanguage: state.settings.targetLanguage,
        sourceLanguage: state.settings.sourceLanguage === "auto" ? detectedSourceLanguage : state.settings.sourceLanguage,
        cues
      }
    },
    90000,
    "AI 翻译超时：请确认当前 Provider 和模型可用，或换一个服务商重试。"
  )
    .catch(async (error) => {
      if (isExtensionContextInvalidated(error)) {
        throw error;
      }
      await cancelProviderDub(requestId);
      return { ok: false, error: friendlyErrorMessage(error) };
    })
    .finally(() => {
      state.activeDubRequestIds.delete(requestId);
    });

  if (!response.ok) {
    if (/取消/.test(response.error || "")) {
      const error = new Error(response.error || "翻译已取消");
      error.name = "OperationStaleError";
      throw error;
    }
    if ((state.settings.provider || "openai") === "native") {
      if (response.code === "OLLAMA_UNAVAILABLE" || /Ollama/i.test(response.error || "")) {
        throw new Error(response.error || "Ollama 本地翻译不可用，请启动 Ollama 或改用 Chrome 本地翻译。");
      }
      throw new Error(`本地 Engine 翻译失败：${response.error || "请打开扩展弹窗检查 Engine"}`);
    }
    return fallbackToChromeTranslator(cues, detectedSourceLanguage, response);
  }

  const payload = response.payload || {};
  if (payload.warning) {
    setStatus(payload.warning, "error");
  }

  return (payload.cues || []).map((cue, index) => ({
    ...cues[index],
    ...cue,
    translatedText: cue.translatedText || cue.text || cues[index]?.text || ""
  }));
}

async function fallbackToChromeTranslator(cues, detectedSourceLanguage, response = {}) {
  const providerLabel = providerName(state.settings.provider);
  const providerMessage = response.error || `${providerLabel} 暂时不可用。`;
  setStatus(`${providerMessage} 正在自动改用 Chrome 本地免费翻译...`, "working");
  try {
    const translated = await translateCuesWithChromeTranslator(cues, detectedSourceLanguage);
    state.timelineCacheProvider = "chrome-translator";
    setStatus(`${providerLabel} 暂时不可用，已自动改用 Chrome 本地免费翻译`, "");
    return translated;
  } catch (fallbackError) {
    throw new Error(
      `${providerMessage} Chrome 本地免费翻译也未能启动：${fallbackError.message || String(fallbackError)}`
    );
  }
}

function providerName(provider) {
  return ((state.providerOptions || PROVIDER_OPTIONS).find(([value]) => value === provider) || PROVIDER_OPTIONS[0])[1];
}

function providerHint(provider, settings) {
  if (provider === "chrome-translator") {
    return "Chrome 桌面版免费本地翻译；首次使用会准备对应语言包。";
  }
  if (provider === "native") {
    return "本地 Engine 需要先安装伴侣程序；安装说明在扩展弹窗。";
  }
  if (provider === "local-http") {
    return "localhost 调试模式需要手动启动本地 server。";
  }
  if (!settings.hasTranscriptionApiKey) {
    return `无字幕视频需要配置 ${settings.transcriptionProviderLabel || "转写服务"} Key；翻译 Provider 可另选。`;
  }
  if (settings.hasApiKey) {
    return `${providerName(provider)} Key 已配置；模型和 Key 可在扩展弹窗修改。`;
  }
  return `请先在扩展弹窗填写 ${providerName(provider)} API Key。`;
}

async function extensionFetch(url, options = {}) {
  const response = await sendRuntimeMessage({
    type: "localtube.fetch",
    request: {
      url,
      method: options.method || "GET",
      headers: options.headers || {},
      body: options.body || undefined,
      credentials: options.credentials || undefined
    }
  });

  if (!response) {
    return { ok: false, status: 0, text: "", error: "No response" };
  }

  return response;
}

async function youtubeFetch(url, options = {}) {
  const requestUrl = String(url || "");
  if (canFetchDirectlyFromYouTube(requestUrl)) {
    try {
      const response = await fetch(requestUrl, {
        method: options.method || "GET",
        headers: options.headers || {},
        body: options.body || undefined,
        credentials: "include",
        cache: "no-store"
      });
      return {
        ok: response.ok,
        status: response.status,
        url: response.url,
        text: await response.text()
      };
    } catch (error) {
      console.debug("[LocalTube Dub] direct YouTube fetch failed, falling back to background fetch", {
        url: requestUrl.slice(0, 120),
        error: error.message || String(error)
      });
    }
  }

  return extensionFetch(requestUrl, { ...options, credentials: "include" });
}

function canFetchDirectlyFromYouTube(url) {
  try {
    const target = new URL(url, location.href);
    return target.origin === location.origin && /\.youtube\.com$/.test(target.hostname);
  } catch (error) {
    return false;
  }
}

function setStatus(message, tone) {
  if (!state.root) {
    return;
  }

  const status = state.root.querySelector(".ltd-status");
  status.textContent = message;
  status.classList.toggle("working", tone === "working");
  status.classList.toggle("error", tone === "error");
  updateExportControl();
}

function installNavigationWatcher() {
  setInterval(() => {
    if (state.lastUrl === location.href) {
      return;
    }

    state.lastUrl = location.href;
    stopDubbing();

    if (isWatchPage() && state.settings.enabled) {
      mountWidget();
      setStatus("等待视频字幕", "");
    } else {
      unmountWidget();
    }
  }, 800);
}

function isWatchPage() {
  return location.hostname.includes("youtube.com") && location.pathname === "/watch";
}
