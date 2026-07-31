(function installLocalTubeBackgroundHelpers(globalScope) {
  function createTranscriptionRequestRegistry(AbortControllerImpl = globalScope.AbortController) {
    const requests = new Map();
    const cancelledBeforeBegin = new Map();
    const tombstoneTtlMs = 60000;

    function purgeOldTombstones(now = Date.now()) {
      for (const [requestId, cancelledAt] of cancelledBeforeBegin.entries()) {
        if (now - cancelledAt > tombstoneTtlMs) {
          cancelledBeforeBegin.delete(requestId);
        }
      }
    }

    function begin(requestId) {
      const safeRequestId = String(requestId || `request:${Date.now()}`);
      purgeOldTombstones();
      const previous = requests.get(safeRequestId);
      if (previous) {
        previous.abort();
      }

      const controller = new AbortControllerImpl();
      if (cancelledBeforeBegin.delete(safeRequestId)) {
        controller.abort();
      }
      requests.set(safeRequestId, controller);
      return {
        requestId: safeRequestId,
        controller,
        signal: controller.signal
      };
    }

    function complete(requestId, controller) {
      if (requests.get(requestId) === controller) {
        requests.delete(requestId);
        return true;
      }
      return false;
    }

    function cancel(requestId) {
      if (!requestId) {
        let cancelled = false;
        for (const controller of requests.values()) {
          controller.abort();
          cancelled = true;
        }
        requests.clear();
        return cancelled;
      }

      const controller = requests.get(requestId);
      if (!controller) {
        cancelledBeforeBegin.set(String(requestId), Date.now());
        purgeOldTombstones();
        return true;
      }

      controller.abort();
      requests.delete(requestId);
      return true;
    }

    function size() {
      return requests.size;
    }

    return {
      begin,
      cancel,
      complete,
      size
    };
  }

  function assessEngineCompatibility(payload = {}, expectedProtocol = 1, expectedVersion = "") {
    const service = String(payload?.service || "");
    const engineVersion = String(payload?.engineVersion || "unknown");
    const protocolVersion = Number(payload?.protocolVersion || 0);
    const requiredProtocol = Math.max(1, Number(expectedProtocol) || 1);
    const serviceMatches = service === "localtube-dub";
    const compatible = serviceMatches && protocolVersion >= requiredProtocol;
    return {
      compatible,
      upgradeRequired: !compatible,
      versionMismatch:
        compatible &&
        Boolean(expectedVersion) &&
        engineVersion !== "unknown" &&
        engineVersion !== "development" &&
        engineVersion !== String(expectedVersion),
      engineVersion,
      protocolVersion,
      expectedVersion: String(expectedVersion || ""),
      requiredProtocol,
      serviceMatches
    };
  }

  function shouldAutoStartCaptionEngine(result = {}) {
    const status = Number(result?.status || 0);
    const code = String(result?.code || "");
    const error = String(result?.error || "");
    if (status > 0 || code === "ENGINE_TIMEOUT" || /timeout|timed out|超时/i.test(error)) {
      return false;
    }
    return (
      code === "CAPTION_ENGINE_UNAVAILABLE" ||
      /Failed to fetch|Could not establish connection|ECONNREFUSED|connection refused|network error|网络请求失败/i.test(error)
    );
  }

  function classifyProviderFailure(status = 0, message = "") {
    const safeStatus = Number(status || 0);
    const text = String(message || "");
    if (
      safeStatus === 401 ||
      /authentication\s+fails?|invalid\s+(api\s*)?key|incorrect\s+(api\s*)?key|unauthori[sz]ed|invalid[_\s-]?auth/i.test(text)
    ) {
      return "PROVIDER_AUTH_FAILED";
    }
    if (
      safeStatus === 402 ||
      /insufficient\s+(balance|quota|credits?)|quota\s+exceeded|exceeded.*quota|余额不足|额度不足|配额不足/i.test(text)
    ) {
      return "PROVIDER_QUOTA_EXCEEDED";
    }
    if (safeStatus === 429 || /too many requests|rate.?limit|限流|请求过于频繁/i.test(text)) {
      return "PROVIDER_RATE_LIMITED";
    }
    if (
      (safeStatus === 404 && /model/i.test(text)) ||
      /model.*(not found|does not exist|invalid|unavailable)|模型.*(不存在|不可用|无效)/i.test(text)
    ) {
      return "PROVIDER_MODEL_INVALID";
    }
    if (safeStatus === 403 || /permission denied|forbidden|没有权限|权限不足/i.test(text)) {
      return "PROVIDER_PERMISSION_DENIED";
    }
    if (/timeout|timed out|超时/i.test(text)) {
      return "PROVIDER_TIMEOUT";
    }
    return "PROVIDER_ERROR";
  }

  function providerFailureMessage(providerLabel = "AI 服务", code = "PROVIDER_ERROR", status = 0) {
    const label = String(providerLabel || "AI 服务");
    const messages = {
      PROVIDER_AUTH_FAILED: `${label} API Key 无效、已失效或不属于该服务。`,
      PROVIDER_QUOTA_EXCEEDED: `${label} 账户余额或可用额度不足。`,
      PROVIDER_RATE_LIMITED: `${label} 当前请求过于频繁，请稍后再试。`,
      PROVIDER_MODEL_INVALID: `${label} 当前模型名称无效或该账户无权使用。`,
      PROVIDER_PERMISSION_DENIED: `${label} 拒绝了当前请求，请检查 Key 权限和账户状态。`,
      PROVIDER_TIMEOUT: `${label} 请求超时。`
    };
    if (messages[code]) {
      return messages[code];
    }
    const safeStatus = Number(status || 0);
    return safeStatus > 0 ? `${label} 暂时不可用（HTTP ${safeStatus}）。` : `${label} 暂时不可用。`;
  }

  const TTS_ENGINE_FAILURE_CODES = new Set([
    "EDGE_TTS_UNAVAILABLE",
    "ENGINE_TIMEOUT",
    "ENGINE_UPGRADE_REQUIRED",
    "KOKORO_TTS_UNAVAILABLE",
    "TTS_ENGINE_UNAVAILABLE"
  ]);

  function classifyTtsEngineFailure(result = {}, options = {}) {
    const code = String(result?.code || "").trim().toUpperCase();
    if (code) {
      return {
        code,
        activateLightweight: TTS_ENGINE_FAILURE_CODES.has(code)
      };
    }

    const status = Number(result?.status || 0);
    const error = String(result?.error || result?.message || "");
    if (/missing tts text|invalid tts rate|invalid.*target duration|missing tts payload/i.test(error)) {
      return { code: "TTS_REQUEST_INVALID", activateLightweight: false };
    }
    if (/invalid.*voice|voice.*(?:invalid|not found|unavailable)|音色.*(?:无效|不存在|不可用)/i.test(error)) {
      return { code: "TTS_VOICE_UNAVAILABLE", activateLightweight: false };
    }
    if (/no audio (?:was )?received|verify.*parameters|没有生成音频|没有返回音频|生成失败/i.test(error)) {
      return { code: "TTS_SYNTHESIS_FAILED", activateLightweight: false };
    }
    if (
      options.transportFailure ||
      status === 404 ||
      /尚未安装|需要 ffmpeg|not installed|missing dependency|kokoro.*不可用/i.test(error)
    ) {
      return { code: "TTS_ENGINE_UNAVAILABLE", activateLightweight: true };
    }
    return { code: "TTS_SYNTHESIS_FAILED", activateLightweight: false };
  }

  function resolveTtsEngineFailure(failures = []) {
    const classified = Array.isArray(failures) ? failures.filter(Boolean) : [];
    const semanticFailure = classified.find((failure) => !failure.activateLightweight);
    if (semanticFailure) {
      const messages = {
        TTS_REQUEST_INVALID: "配音请求无效。",
        TTS_VOICE_UNAVAILABLE: "当前音色无法生成这个片段。"
      };
      return {
        ok: false,
        code: semanticFailure.code || "TTS_SYNTHESIS_FAILED",
        error: messages[semanticFailure.code] || "当前片段未能生成配音。"
      };
    }
    if (classified.some((failure) => failure.activateLightweight)) {
      return {
        ok: false,
        code: "TTS_ENGINE_UNAVAILABLE",
        error: "配音 Engine 暂不可用。"
      };
    }
    return {
      ok: false,
      code: "TTS_SYNTHESIS_FAILED",
      error: "当前片段未能生成配音。"
    };
  }

  function timelineCacheKey(request = {}) {
    return [request.videoId, request.targetLanguage, request.provider, request.model]
      .map((value) => encodeURIComponent(String(value || "").trim().toLowerCase()))
      .join("|");
  }

  function normalizeTimelineCues(cues, maxCues = 5000) {
    return (Array.isArray(cues) ? cues : [])
      .slice(0, Math.max(1, Number(maxCues) || 5000))
      .map((cue, index) => {
        const text = String(cue?.text || "").slice(0, 4000).trim();
        const translatedText = String(cue?.translatedText || "").slice(0, 4000).trim();
        const start = Math.max(0, Number(cue?.start || 0));
        const end = Math.max(start + 0.05, Number(cue?.end || start + 1));
        if (!text || !translatedText || !Number.isFinite(start) || !Number.isFinite(end)) {
          return null;
        }
        return {
          id: String(cue?.id || index),
          start,
          end,
          text,
          translatedText
        };
      })
      .filter(Boolean);
  }

  function pruneTimelineCache(cache, options = {}) {
    const now = Number(options.now || Date.now());
    const ttlMs = Math.max(60000, Number(options.ttlMs || 7 * 24 * 60 * 60 * 1000));
    const maxEntries = Math.max(1, Number(options.maxEntries || 12));
    const maxBytes = Math.max(1024, Number(options.maxBytes || 4 * 1024 * 1024));
    const entries = (Array.isArray(cache?.entries) ? cache.entries : [])
      .filter((entry) => {
        const updatedAt = Number(entry?.updatedAt || 0);
        return entry?.key && Array.isArray(entry?.cues) && entry.cues.length && updatedAt > 0 && now - updatedAt <= ttlMs;
      })
      .sort((left, right) => Number(right.updatedAt || 0) - Number(left.updatedAt || 0))
      .slice(0, maxEntries);
    const byteLength = (value) => {
      const serialized = JSON.stringify(value);
      if (typeof TextEncoder !== "undefined") {
        return new TextEncoder().encode(serialized).byteLength;
      }
      return unescape(encodeURIComponent(serialized)).length;
    };
    while (entries.length && byteLength({ version: 1, entries }) > maxBytes) {
      entries.pop();
    }
    return { version: 1, entries };
  }

  function upsertTimelineCache(cache, request = {}, timeline = {}, options = {}) {
    const key = timelineCacheKey(request);
    const cues = normalizeTimelineCues(timeline.cues, options.maxCues);
    if (!request.videoId || !request.targetLanguage || !request.provider || !cues.length) {
      return pruneTimelineCache(cache, options);
    }
    const now = Number(options.now || Date.now());
    const existing = Array.isArray(cache?.entries) ? cache.entries.filter((entry) => entry?.key !== key) : [];
    existing.unshift({
      key,
      videoId: String(request.videoId),
      targetLanguage: String(request.targetLanguage),
      provider: String(request.provider),
      model: String(request.model || ""),
      sourceLanguage: String(timeline.sourceLanguage || "auto"),
      trackLanguage: String(timeline.trackLanguage || ""),
      updatedAt: now,
      cues
    });
    return pruneTimelineCache({ version: 1, entries: existing }, { ...options, now });
  }

  function findTimelineCache(cache, request = {}, options = {}) {
    const normalized = pruneTimelineCache(cache, options);
    const key = timelineCacheKey(request);
    const entry = normalized.entries.find((item) => item.key === key) || null;
    return { cache: normalized, entry };
  }

  const api = {
    assessEngineCompatibility,
    classifyProviderFailure,
    classifyTtsEngineFailure,
    createTranscriptionRequestRegistry,
    findTimelineCache,
    normalizeTimelineCues,
    pruneTimelineCache,
    providerFailureMessage,
    resolveTtsEngineFailure,
    shouldAutoStartCaptionEngine,
    timelineCacheKey,
    upsertTimelineCache
  };
  globalScope.LocalTubeDubBackgroundHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
