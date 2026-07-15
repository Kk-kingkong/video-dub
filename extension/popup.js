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

const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const { mergeVoiceOptions, selectVoiceOptions } = globalThis.LocalTubeDubVoiceHelpers;
const { collectOptionalOrigins, optionalCapturePermissions } = globalThis.LocalTubeDubPermissionHelpers;

const PROVIDER_DEFAULTS = {
  deepseek: {
    label: "DeepSeek",
    endpoint: "https://api.deepseek.com/chat/completions",
    model: "deepseek-chat",
    requiresApiKey: true,
    note: "适合低成本翻译，接口兼容 OpenAI Chat Completions。"
  },
  microsoft: {
    label: "Microsoft Translator",
    endpoint: "https://api.cognitive.microsofttranslator.com/translate",
    model: "",
    requiresApiKey: true,
    note: "使用 Azure AI Translator。模型栏可填 Azure Region（如 eastasia），单服务 Translator 资源通常可留空。"
  },
  "google-translate": {
    label: "Google Cloud Translation",
    endpoint: "https://translation.googleapis.com/language/translate/v2",
    model: "",
    requiresApiKey: true,
    note: "使用 Google Cloud Translation Basic。需要 Google Cloud API Key；有目标语言字幕时不会消耗翻译额度。"
  },
  "chrome-translator": {
    label: "Chrome 本地翻译（免费）",
    endpoint: "",
    model: "",
    requiresApiKey: false,
    kind: "browser-translator",
    note: "使用 Chrome 桌面版内置 Translator API。本地语言包首次使用时由 Chrome 下载，字幕文本不需要发送到第三方翻译 API。"
  },
  openai: {
    label: "OpenAI",
    endpoint: "https://api.openai.com/v1/chat/completions",
    model: "gpt-4.1-mini",
    requiresApiKey: true,
    note: "使用你的 OpenAI API Key 翻译字幕。"
  },
  gemini: {
    label: "Gemini",
    endpoint: "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    model: "gemini-2.5-flash",
    requiresApiKey: true,
    note: "使用你的 Google Gemini API Key。Endpoint 会根据模型自动生成。"
  },
  anthropic: {
    label: "Claude",
    endpoint: "https://api.anthropic.com/v1/messages",
    model: "claude-3-5-haiku-latest",
    requiresApiKey: true,
    note: "使用你的 Anthropic API Key 翻译字幕。"
  },
  openrouter: {
    label: "OpenRouter",
    endpoint: "https://openrouter.ai/api/v1/chat/completions",
    model: "openai/gpt-4o-mini",
    requiresApiKey: true,
    note: "使用你的 OpenRouter Key，可在模型栏填任意 OpenRouter 模型 ID。"
  },
  custom: {
    label: "自定义 OpenAI-compatible",
    endpoint: "https://api.openai.com/v1/chat/completions",
    model: "gpt-4.1-mini",
    requiresApiKey: false,
    note: "适合 LM Studio、LocalAI、自建网关或任何 OpenAI-compatible 服务。"
  },
  native: {
    label: "Ollama（本地 Engine）",
    endpoint: "",
    model: "",
    requiresApiKey: false,
    note: "高级本地翻译选项，需要你另外安装并启动 Ollama；字幕读取、Whisper 和本地 TTS 仍由 Engine 提供。"
  },
  "local-http": {
    label: "localhost 调试",
    endpoint: "http://127.0.0.1:8787",
    model: "",
    requiresApiKey: false,
    note: "开发调试模式，需要手动启动 server/local_dub_server.py。"
  }
};

const TRANSCRIPTION_PROVIDER_DEFAULTS = {
  groq: {
    label: "Groq Whisper",
    endpoint: "https://api.groq.com/openai/v1/audio/transcriptions",
    model: "whisper-large-v3-turbo",
    requiresApiKey: true,
    note: "推荐作为无字幕视频的快速转写服务。可与 DeepSeek、Gemini 等翻译 Provider 搭配。"
  },
  deepgram: {
    label: "Deepgram Nova",
    endpoint: "https://api.deepgram.com/v1/listen",
    model: "nova-3",
    requiresApiKey: true,
    note: "适合长音频和词级时间戳，转写结果会再交给当前翻译 Provider。"
  },
  openai: {
    label: "OpenAI Whisper",
    endpoint: "https://api.openai.com/v1/audio/transcriptions",
    model: "whisper-1",
    requiresApiKey: true,
    note: "使用 OpenAI Whisper 转写。若已保存 OpenAI 翻译 Key，也可复用。"
  },
  native: {
    label: "本地 Engine",
    model: "",
    requiresApiKey: false,
    note: "使用本机 whisper.cpp 转写，不需要 API Key；第一次使用请在安装说明中一键安装本地转写。"
  }
};

const MODE_COPY = {
  byok: {
    label: "免费 / 自带 Key",
    summary: "Chrome 本地翻译或自己的 Key"
  }
};

const nodes = {
  enabled: document.querySelector("#enabled"),
  appVersion: document.querySelector("#appVersion"),
  modeCards: Array.from(document.querySelectorAll("[data-mode]")),
  panels: Array.from(document.querySelectorAll("[data-panel]")),
  provider: document.querySelector("#provider"),
  endpoint: document.querySelector("#endpoint"),
  endpointField: document.querySelector("#endpointField"),
  endpointLabel: document.querySelector("#endpointLabel"),
  providerPreview: document.querySelector("#providerPreview"),
  providerNote: document.querySelector("#providerNote"),
  model: document.querySelector("#model"),
  modelField: document.querySelector("#modelField"),
  apiKey: document.querySelector("#apiKey"),
  apiKeyField: document.querySelector("#apiKeyField"),
  transcriptionProvider: document.querySelector("#transcriptionProvider"),
  allowAudioTranscription: document.querySelector("#allowAudioTranscription"),
  cacheTranslations: document.querySelector("#cacheTranslations"),
  transcriptionModel: document.querySelector("#transcriptionModel"),
  transcriptionApiKey: document.querySelector("#transcriptionApiKey"),
  transcriptionApiKeyField: document.querySelector("#transcriptionApiKeyField"),
  transcriptionNote: document.querySelector("#transcriptionNote"),
  targetLanguage: document.querySelector("#targetLanguage"),
  ttsEngine: document.querySelector("#ttsEngine"),
  voiceId: document.querySelector("#voiceId"),
  voiceEnabled: document.querySelector("#voiceEnabled"),
  muteOriginal: document.querySelector("#muteOriginal"),
  originalVolume: document.querySelector("#originalVolume"),
  originalVolumeValue: document.querySelector("#originalVolumeValue"),
  engineStatus: document.querySelector("#engineStatus"),
  engineStatusText: document.querySelector("#engineStatusText"),
  engineStatusMeta: document.querySelector("#engineStatusMeta"),
  engineInstallInline: document.querySelector("#engineInstallInline"),
  testProvider: document.querySelector("#testProvider"),
  clearApiKey: document.querySelector("#clearApiKey"),
  clearTranscriptionApiKey: document.querySelector("#clearTranscriptionApiKey"),
  clearTranslationCache: document.querySelector("#clearTranslationCache"),
  status: document.querySelector("#status")
};

let currentSettings = { ...DEFAULT_SETTINGS };
let engineStatusTimer = 0;
let volumeSaveTimer = 0;
let availableVoiceOptions = [];
const fallbackVoiceOptions = Array.from(nodes.voiceId.options).map((option) => ({
  id: option.value,
  name: option.textContent,
  language: "",
  localService: true
}));

init();

function applyProviderRegistry(response) {
  let changed = false;
  if (Array.isArray(response?.providers)) {
    for (const provider of response.providers) {
      if (!provider?.id || !provider?.label) {
        continue;
      }
      const existing = PROVIDER_DEFAULTS[provider.id] || {};
      PROVIDER_DEFAULTS[provider.id] = {
        ...existing,
        label: provider.label,
        endpoint: provider.endpoint ?? existing.endpoint ?? "",
        model: provider.defaultModel ?? existing.model ?? "",
        requiresApiKey: Boolean(provider.requiresApiKey),
        kind: provider.kind || existing.kind || "openai-compatible",
        note: existing.note || genericProviderNote(provider)
      };
      changed = true;
    }
  }

  if (Array.isArray(response?.transcriptionProviders)) {
    for (const provider of response.transcriptionProviders) {
      if (!provider?.id || !provider?.label) {
        continue;
      }
      const existing = TRANSCRIPTION_PROVIDER_DEFAULTS[provider.id] || {};
      TRANSCRIPTION_PROVIDER_DEFAULTS[provider.id] = {
        ...existing,
        label: provider.label,
        endpoint: provider.endpoint ?? existing.endpoint ?? "",
        model: provider.defaultModel ?? existing.model ?? "",
        requiresApiKey: Boolean(provider.requiresApiKey),
        note: existing.note || genericTranscriptionProviderNote(provider)
      };
      changed = true;
    }
  }

  if (changed) {
    renderProviderOptions();
  }
}

function renderProviderOptions() {
  const selectedProvider = nodes.provider.value || currentSettings.provider;
  nodes.provider.innerHTML = Object.entries(PROVIDER_DEFAULTS)
    .filter(([id]) => isByokProvider(id))
    .map(([id, provider]) => `<option value="${escapeHtml(id)}">${escapeHtml(provider.label)}</option>`)
    .join("");
  nodes.provider.value = selectHasValue(nodes.provider, selectedProvider) ? selectedProvider : "chrome-translator";

  const selectedTranscriptionProvider = nodes.transcriptionProvider.value || currentSettings.transcriptionProvider;
  nodes.transcriptionProvider.innerHTML = Object.entries(TRANSCRIPTION_PROVIDER_DEFAULTS)
    .map(([id, provider]) => `<option value="${escapeHtml(id)}">${escapeHtml(provider.label)}</option>`)
    .join("");
  nodes.transcriptionProvider.value = selectHasValue(nodes.transcriptionProvider, selectedTranscriptionProvider)
    ? selectedTranscriptionProvider
    : "native";
}

function selectHasValue(select, value) {
  return Array.from(select.options).some((option) => option.value === value);
}

function escapeHtml(value) {
  return String(value || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function genericProviderNote(provider) {
  if (provider.kind === "local-http") {
    return "开发调试模式，需要手动启动本地服务。";
  }
  return provider.requiresApiKey
    ? `使用你的 ${provider.label} API Key 翻译字幕。`
    : `${provider.label} 不需要在此处填写翻译 API Key。`;
}

function genericTranscriptionProviderNote(provider) {
  return provider.requiresApiKey
    ? `用于无字幕视频的音频转写，需要填写 ${provider.label} API Key。`
    : `${provider.label} 不需要额外转写 API Key。`;
}

async function init() {
  const settings = await getSettings();
  render(settings);
  refreshVoiceOptions();
  window.speechSynthesis?.addEventListener?.("voiceschanged", refreshVoiceOptions, { once: true });
  notifyActiveTab(currentSettings);
  announceCurrentTabGrant();

  for (const card of nodes.modeCards) {
    card.addEventListener("click", () => selectMode(card.dataset.mode));
  }

  for (const key of [
    "enabled",
    "endpoint",
    "model",
    "allowAudioTranscription",
    "cacheTranslations",
    "transcriptionModel",
    "transcriptionApiKey",
    "voiceId",
    "voiceEnabled",
    "muteOriginal",
    "originalVolume"
  ]) {
    nodes[key].addEventListener("change", saveFromForm);
  }
  nodes.apiKey.addEventListener("change", saveAndValidateApiKey);
  nodes.originalVolume.addEventListener("input", handleOriginalVolumeInput);
  nodes.targetLanguage.addEventListener("change", async () => {
    renderVoiceOptions("auto");
    nodes.voiceId.value = "auto";
    await saveFromForm();
  });
  nodes.ttsEngine.addEventListener("change", async () => {
    renderVoiceOptions("auto");
    nodes.voiceId.value = "auto";
    await saveFromForm();
    await refreshVoiceOptions();
  });

  nodes.provider.addEventListener("change", handleProviderChange);
  nodes.transcriptionProvider.addEventListener("change", handleTranscriptionProviderChange);
  nodes.testProvider.addEventListener("click", testProvider);
  nodes.clearApiKey.addEventListener("click", clearApiKey);
  nodes.clearTranscriptionApiKey.addEventListener("click", clearTranscriptionApiKey);
  nodes.clearTranslationCache.addEventListener("click", clearTranslationCache);
  nodes.engineInstallInline.addEventListener("click", openInstallGuide);
  refreshEngineStatus();
  engineStatusTimer = setInterval(refreshEngineStatus, 5000);
}

async function refreshVoiceOptions() {
  const response = await chrome.runtime
    .sendMessage({ type: "localtube.listVoices", settings: currentSettings })
    .catch(() => null);
  const engineVoices = Array.isArray(response?.payload?.voices) ? response.payload.voices : [];
  const browserVoices = window.speechSynthesis?.getVoices?.() || [];
  const merged = mergeVoiceOptions(engineVoices, browserVoices);
  if (merged.length) {
    availableVoiceOptions = merged;
  }
  renderVoiceOptions(currentSettings.voiceId || nodes.voiceId.value || "auto");
}

function renderVoiceOptions(selectedVoice = "auto") {
  const targetLanguage = nodes.targetLanguage.value || currentSettings.targetLanguage || "zh-CN";
  const current = String(selectedVoice || "auto");
  const matching = selectVoiceOptions(
    availableVoiceOptions,
    targetLanguage,
    current,
    fallbackVoiceOptions,
    { provider: nodes.ttsEngine.value || currentSettings.ttsEngine || DEFAULT_SETTINGS.ttsEngine }
  );
  nodes.voiceId.innerHTML = [
    '<option value="auto">自动匹配（推荐）</option>',
    ...matching.map((voice) => {
      const locale = voice.language ? ` · ${voice.language}` : "";
      return `<option value="${escapeHtml(voice.id)}">${escapeHtml(voice.name)}${escapeHtml(locale)}</option>`;
    })
  ].join("");
  nodes.voiceId.value = selectHasValue(nodes.voiceId, current) ? current : "auto";
}

function render(settings) {
  currentSettings = normalizeMode({ ...DEFAULT_SETTINGS, ...settings });
  nodes.appVersion.textContent = EXTENSION_VERSION;
  const setupMode = currentSettings.setupMode;
  const provider = getProvider(currentSettings.provider);
  const transcriptionProvider = getTranscriptionProvider(currentSettings.transcriptionProvider);
  const effectiveEndpoint = resolveEndpoint(currentSettings);
  const effectiveModel = currentSettings.model || provider.model || "";

  nodes.enabled.checked = currentSettings.enabled;
  nodes.providerPreview.textContent = `${MODE_COPY[setupMode].label} · ${MODE_COPY[setupMode].summary}`;
  nodes.providerPreview.href = effectiveEndpoint || "#";

  for (const card of nodes.modeCards) {
    const active = card.dataset.mode === setupMode;
    card.classList.toggle("is-active", active);
    card.setAttribute("aria-pressed", String(active));
  }

  for (const panel of nodes.panels) {
    panel.hidden = panel.dataset.panel !== setupMode;
  }

  const providerValue = isByokProvider(currentSettings.provider) ? currentSettings.provider : "chrome-translator";
  nodes.provider.value = providerValue;
  nodes.endpoint.value =
    currentSettings.provider === "custom"
      ? currentSettings.customEndpoint || provider.endpoint
      : currentSettings.endpoint || provider.endpoint;
  nodes.model.value = currentSettings.model || "";
  nodes.model.placeholder = provider.model ? `默认：${provider.model}` : "此模式不需要模型";
  nodes.modelField.hidden = provider.kind === "browser-translator";
  nodes.apiKey.value = "";
  nodes.apiKey.placeholder = currentSettings.hasApiKey ? "已保存，留空继续使用" : "输入翻译 API Key";
  nodes.apiKeyField.hidden = !provider.requiresApiKey && currentSettings.provider !== "custom";
  nodes.endpointField.hidden = currentSettings.provider !== "custom" && currentSettings.provider !== "local-http";
  nodes.endpoint.disabled = !["custom", "local-http"].includes(currentSettings.provider);
  nodes.endpointLabel.textContent = currentSettings.provider === "local-http" ? "本地端点" : "API Endpoint";
  nodes.providerNote.textContent = provider.note;
  nodes.testProvider.textContent = provider.requiresApiKey ? "验证翻译 Key" : "检查当前模式";

  nodes.transcriptionProvider.value = currentSettings.transcriptionProvider || "native";
  nodes.allowAudioTranscription.checked = Boolean(currentSettings.allowAudioTranscription);
  nodes.cacheTranslations.checked = Boolean(currentSettings.cacheTranslations);
  nodes.transcriptionModel.value = currentSettings.transcriptionModel || "";
  nodes.transcriptionModel.placeholder = transcriptionProvider.model ? `默认：${transcriptionProvider.model}` : "此模式不需要模型";
  nodes.transcriptionApiKey.value = "";
  nodes.transcriptionApiKey.placeholder = currentSettings.hasTranscriptionApiKey ? "已保存，留空继续使用" : "输入转写 API Key";
  nodes.transcriptionApiKeyField.hidden = !transcriptionProvider.requiresApiKey;
  nodes.transcriptionNote.textContent = transcriptionProvider.note;

  nodes.targetLanguage.value = currentSettings.targetLanguage;
  nodes.ttsEngine.value = currentSettings.ttsEngine === "edge" ? "edge" : "system";
  nodes.voiceId.value = selectHasValue(nodes.voiceId, currentSettings.voiceId) ? currentSettings.voiceId : "auto";
  nodes.voiceEnabled.checked = currentSettings.voiceEnabled;
  nodes.muteOriginal.checked = currentSettings.muteOriginal;
  nodes.originalVolume.value = String(Math.round(clampNumber(currentSettings.originalVolume, 0, 1, DEFAULT_SETTINGS.originalVolume) * 100));
  nodes.originalVolumeValue.textContent = `${nodes.originalVolume.value}%`;

  nodes.clearApiKey.hidden = setupMode !== "byok";
  nodes.clearTranscriptionApiKey.hidden = setupMode !== "byok";
  refreshEngineStatus();
}

async function refreshEngineStatus() {
  if (!nodes.engineStatus) {
    return;
  }
  setEngineStatus("checking", "正在检查字幕 Engine...", "优先读取目标语言字幕；没有目标字幕才调用翻译 API。");
  const response = await chrome.runtime
    .sendMessage({ type: "localtube.captionEngineHealth", settings: currentSettings })
    .catch((error) => ({ ok: false, error: error.message || String(error) }));

  if (response?.ok) {
    const payload = response.payload || {};
    const transport = payload.transport === "native" ? "Native" : "HTTP";
    if (payload.upgradeRequired) {
      setEngineStatus(
        "error",
        "本地 Engine 版本过旧，需要更新",
        `当前 Engine ${payload.engineVersion || "未知"}（协议 ${payload.protocolVersion || 0}），扩展 ${EXTENSION_VERSION} 需要协议 ${payload.requiredProtocol || 2}。请打开安装说明并安装同版本 Engine。`
      );
      return;
    }
    if (currentSettings.ttsEngine === "edge" && !payload.edgeTts) {
      setEngineStatus(
        "warn",
        "自然在线语音尚未安装",
        "打开安装说明并重新运行 Engine 依赖安装，然后重启 Engine。字幕读取仍可继续使用。"
      );
      return;
    }
    if (payload.ytDlp) {
      if (currentSettings.allowAudioTranscription && currentSettings.transcriptionProvider === "native" && !payload.whisper) {
        setEngineStatus(
          "warn",
          "字幕 Engine 已启动，但本地 Whisper 尚未安装",
          "有字幕视频可以使用；无字幕视频请打开安装说明，一键安装本地转写。"
        );
        return;
      }
      const localWhisperReady = currentSettings.transcriptionProvider === "native" && payload.whisper;
      const status = payload.versionMismatch ? "warn" : "ok";
      const versionText = payload.versionMismatch
        ? `Engine ${payload.engineVersion} 与扩展 ${EXTENSION_VERSION} 版本不同，但协议兼容。建议安装匹配 Engine。`
        : `${transport} 已连接，yt-dlp 已就绪。现在可以回到 YouTube 点“开始翻译”。`;
      setEngineStatus(status, payload.versionMismatch ? "Engine 版本不同，当前仍兼容" : "字幕 Engine 已启动", versionText);
      if (localWhisperReady) {
        setEngineStatus(status, payload.versionMismatch ? "Engine 版本不同，当前仍兼容" : "字幕与本地转写 Engine 已启动", payload.versionMismatch ? versionText : `${transport} 已连接，yt-dlp 和 Whisper 均已就绪。`);
      }
      return;
    }
    setEngineStatus("warn", "Engine 已启动，但缺少 yt-dlp", "请打开安装说明，先安装 yt-dlp 依赖，然后重启 Engine。");
    return;
  }

  setEngineStatus("error", "字幕 Engine 未连接", shortEngineHealthError(response?.error));
}

function setEngineStatus(status, title, detail) {
  nodes.engineStatus.classList.remove("is-ok", "is-warn", "is-error");
  if (status !== "checking") {
    nodes.engineStatus.classList.add(`is-${status}`);
  }
  nodes.engineStatusText.textContent = title;
  nodes.engineStatusMeta.textContent = detail;
}

function shortEngineHealthError(error) {
  const message = String(error || "");
  if (/timeout|超时/i.test(message)) {
    return "本地服务响应超时：确认启动 Engine 的终端没有卡住，或关闭后重新运行启动命令。";
  }
  if (/Failed to fetch|ECONNREFUSED|fetch|Could not establish|Native host/i.test(message)) {
    return "没有连接到 127.0.0.1:8787 或 Native host。第一次使用请打开说明安装 yt-dlp，并启动 Engine。";
  }
  return message.slice(0, 120) || "第一次使用请打开说明安装 yt-dlp，并启动 Engine。";
}

async function selectMode(setupMode) {
  const settings = normalizeMode({
    ...buildSettingsFromForm(),
    setupMode
  });

  try {
    await ensureSelectedPermissions(settings);
  } catch (error) {
    nodes.status.textContent = error.message || String(error);
    return;
  }

  const response = await chrome.runtime.sendMessage({ type: "localtube.setSettings", settings });
  if (response?.ok) {
    applyProviderRegistry(response);
    render(response.settings);
    notifyActiveTab(response.settings);
    nodes.status.textContent = `已切换到${MODE_COPY[setupMode].label}`;
  }
}

async function handleProviderChange() {
  const provider = getProvider(nodes.provider.value);
  if (!nodes.model.value && provider.model) {
    nodes.model.placeholder = `默认：${provider.model}`;
  }
  await saveFromForm();
}

async function handleTranscriptionProviderChange() {
  const provider = getTranscriptionProvider(nodes.transcriptionProvider.value);
  nodes.transcriptionModel.placeholder = provider.model ? `默认：${provider.model}` : "此模式不需要模型";
  await saveFromForm();
}

async function saveFromForm(options = {}) {
  clearTimeout(volumeSaveTimer);
  const settings = normalizeMode(buildSettingsFromForm());

  if (options.requestPermissions !== false) {
    try {
      await ensureSelectedPermissions(settings);
    } catch (error) {
      nodes.status.textContent = error.message || String(error);
      return null;
    }
  }

  notifyActiveTab(pageSafeSettings(settings));
  const savedNewKey = Boolean(settings.apiKey);
  const savedNewTranscriptionKey = Boolean(settings.transcriptionApiKey);
  const response = await chrome.runtime.sendMessage({ type: "localtube.setSettings", settings });
  if (response?.ok) {
    applyProviderRegistry(response);
    render(response.settings);
    notifyActiveTab(response.settings);
    nodes.status.textContent =
      savedNewKey || savedNewTranscriptionKey
        ? "设置和 Key 已保存"
        : "设置已保存";
  }
  return response?.ok ? response : null;
}

async function saveAndValidateApiKey() {
  const hasNewKey = Boolean(nodes.apiKey.value.trim());
  const saved = await saveFromForm();
  if (!saved || !hasNewKey) {
    return;
  }
  await testProvider({ skipSave: true });
}

function handleOriginalVolumeInput() {
  nodes.originalVolumeValue.textContent = `${nodes.originalVolume.value}%`;
  currentSettings = {
    ...currentSettings,
    originalVolume: Number(nodes.originalVolume.value || 0) / 100
  };
  notifyActiveTab(pageSafeSettings(normalizeMode(buildSettingsFromForm())));
  clearTimeout(volumeSaveTimer);
  volumeSaveTimer = setTimeout(() => {
    saveFromForm({ requestPermissions: false });
  }, 140);
}

function pageSafeSettings(settings) {
  return {
    ...settings,
    apiKey: "",
    transcriptionApiKey: ""
  };
}

async function getSettings() {
  const response = await chrome.runtime.sendMessage({ type: "localtube.getSettings" });
  applyProviderRegistry(response);
  return response?.settings || DEFAULT_SETTINGS;
}

async function testProvider(options = {}) {
  nodes.status.textContent = "检查中...";
  const settings = normalizeMode(buildSettingsFromForm());

  try {
    await ensureSelectedPermissions(settings);

    if (!options.skipSave) {
      const saveResponse = await chrome.runtime.sendMessage({ type: "localtube.setSettings", settings });
      if (saveResponse?.ok) {
        applyProviderRegistry(saveResponse);
        render(saveResponse.settings);
        notifyActiveTab(saveResponse.settings);
      }
    }

    const response = await chrome.runtime.sendMessage({
      type: "localtube.providerHealth",
      settings
    });

    if (!response?.ok) {
      throw new Error(response?.error || "验证失败");
    }

    const payload = response.payload || {};
    if (payload.transport === "native") {
      nodes.status.textContent = payload.ollama ? "本地 Engine 已连接，Ollama 已就绪" : "本地 Engine 已连接，Ollama 未连接";
      return;
    }

    if (payload.transport === "http") {
      nodes.status.textContent = payload.ollama ? "localhost 已连接，Ollama 已就绪" : "localhost 已连接，Ollama 未连接";
      return;
    }

    if (payload.transport === "chrome-translator") {
      nodes.status.textContent = "Chrome 本地翻译已选择，回到视频页开始后会准备语言包";
      return;
    }

    nodes.status.textContent = `${getProvider(settings.provider).label} 连接成功`;
  } catch (error) {
    nodes.status.textContent = error.message || "连接失败";
  }
}

async function clearApiKey() {
  const provider = nodes.provider.value;
  await chrome.runtime.sendMessage({ type: "localtube.clearApiKey", provider });
  const settings = await getSettings();
  render(settings);
  nodes.status.textContent = "当前翻译服务的 Key 已清除";
}

async function clearTranscriptionApiKey() {
  const provider = nodes.transcriptionProvider.value;
  await chrome.runtime.sendMessage({ type: "localtube.clearTranscriptionApiKey", provider });
  const settings = await getSettings();
  render(settings);
  nodes.status.textContent = "当前转写服务的 Key 已清除";
}

async function clearTranslationCache() {
  const response = await chrome.runtime.sendMessage({ type: "localtube.clearTranslationCache" });
  nodes.status.textContent = response?.ok ? "本机字幕缓存已清除" : response?.error || "清除字幕缓存失败";
}

function buildSettingsFromForm() {
  const providerId = nodes.provider.value;
  return {
    ...currentSettings,
    enabled: nodes.enabled.checked,
    provider: providerId,
    endpoint: providerId === "local-http" ? nodes.endpoint.value.replace(/\/+$/, "") : currentSettings.endpoint,
    customEndpoint: providerId === "custom" ? nodes.endpoint.value.replace(/\/+$/, "") : currentSettings.customEndpoint,
    model: nodes.model.value.trim(),
    apiKey: nodes.apiKey.value.trim(),
    transcriptionProvider: nodes.transcriptionProvider.value,
    allowAudioTranscription: nodes.allowAudioTranscription.checked,
    cacheTranslations: nodes.cacheTranslations.checked,
    transcriptionModel: nodes.transcriptionModel.value.trim(),
    transcriptionApiKey: nodes.transcriptionApiKey.value.trim(),
    targetLanguage: nodes.targetLanguage.value,
    ttsEngine: nodes.ttsEngine.value === "edge" ? "edge" : "system",
    voiceId: nodes.voiceId.value,
    voiceEnabled: nodes.voiceEnabled.checked,
    muteOriginal: nodes.muteOriginal.checked,
    originalVolume: Number(nodes.originalVolume.value || 0) / 100
  };
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, number));
}

function normalizeMode(settings) {
  const legacySetupMode = String(settings.setupMode || "");
  const next = { ...settings, setupMode: "byok" };

  if (legacySetupMode === "local") {
    next.provider = "chrome-translator";
    next.transcriptionProvider = "native";
  } else if (legacySetupMode === "managed" || next.provider === "managed") {
    next.provider = "chrome-translator";
  }

  if (!isByokProvider(next.provider)) {
    next.provider = "chrome-translator";
  }
  return next;
}

function isByokProvider(provider) {
  const providerConfig = PROVIDER_DEFAULTS[provider];
  return Boolean(providerConfig) && provider !== "local-http";
}

async function ensureSelectedPermissions(settings) {
  if (typeof chrome.permissions?.request !== "function") {
    return;
  }
  const endpoints = [];
  if (settings.setupMode === "byok") {
    const provider = getProvider(settings.provider);
    if (!["browser-translator", "native", "local-http"].includes(provider.kind)) {
      endpoints.push(resolveEndpoint(settings));
    }
    const transcriptionProvider = getTranscriptionProvider(settings.transcriptionProvider);
    if (settings.allowAudioTranscription && settings.transcriptionProvider !== "native") {
      endpoints.push(transcriptionProvider.endpoint);
    }
  }
  const origins = collectOptionalOrigins(endpoints);
  const permissions = optionalCapturePermissions(Boolean(settings.allowAudioTranscription));
  if (!origins.length && !permissions.length) {
    return;
  }
  const details = {};
  if (origins.length) {
    details.origins = origins;
  }
  if (permissions.length) {
    details.permissions = permissions;
  }
  const granted = await permissionsRequest(details);
  if (!granted) {
    const labels = origins.map((origin) => new URL(origin).host);
    if (permissions.length) {
      labels.push("无字幕标签页录音");
    }
    throw new Error(`需要授权 ${labels.join("、")} 才能使用当前设置`);
  }
}

function permissionsRequest(details) {
  return new Promise((resolve, reject) => {
    chrome.permissions.request(details, (result) => {
      const error = chrome.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
        return;
      }
      resolve(Boolean(result));
    });
  });
}

function resolveEndpoint(settings) {
  const provider = getProvider(settings.provider);
  if (settings.provider === "custom") {
    return settings.customEndpoint || provider.endpoint;
  }
  if (settings.provider === "local-http") {
    return settings.endpoint || provider.endpoint;
  }
  return provider.endpoint;
}

function getProvider(providerId) {
  return PROVIDER_DEFAULTS[providerId] || PROVIDER_DEFAULTS.deepseek;
}

function getTranscriptionProvider(providerId) {
  return TRANSCRIPTION_PROVIDER_DEFAULTS[providerId] || TRANSCRIPTION_PROVIDER_DEFAULTS.groq;
}

function openInstallGuide() {
  chrome.tabs.create({ url: chrome.runtime.getURL("install.html") });
}

async function notifyActiveTab(settings) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !/youtube\.com/.test(tab.url || "")) {
    return;
  }

  chrome.tabs.sendMessage(tab.id, { type: "localtube.settingsChanged", settings }).catch(() => {});
}

async function announceCurrentTabGrant() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/^https:\/\/(www\.)?youtube\.com\/(watch|shorts)/.test(tab.url)) {
    return;
  }

  nodes.status.textContent = "当前 YouTube 页已授权，回到视频页点开始翻译";
}
