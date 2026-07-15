(function installLocalTubeVoiceHelpers(globalScope) {
  function voiceLanguagePrefix(language) {
    return String(language || "").trim().toLowerCase().replace(/_/g, "-").split("-")[0] || "";
  }

  function mergeVoiceOptions(...sources) {
    const merged = new Map();
    for (const source of sources) {
      for (const voice of Array.isArray(source) ? source : []) {
        const id = String(voice?.id || voice?.name || "").trim();
        if (!id || id === "auto" || merged.has(id)) {
          continue;
        }
        merged.set(id, {
          id,
          name: String(voice?.name || id),
          language: String(voice?.language || voice?.lang || "").replace(/_/g, "-"),
          localService: voice?.localService !== false,
          provider: String(
            voice?.provider || (voice?.localService === false ? "browser" : "system")
          ).toLowerCase(),
          available: voice?.available !== false
        });
      }
    }
    return Array.from(merged.values());
  }

  function selectVoiceOptions(availableVoices, targetLanguage, selectedVoice, fallbackVoices = [], options = {}) {
    const available = mergeVoiceOptions(availableVoices);
    const fallback = mergeVoiceOptions(fallbackVoices);
    const targetPrefix = voiceLanguagePrefix(targetLanguage);
    const requestedProvider = String(options.provider || "").toLowerCase();
    const providerMatches = (voice) =>
      !requestedProvider ||
      voice.provider === requestedProvider ||
      (requestedProvider === "system" && voice.provider === "browser");
    const filteredAvailable = available.filter(providerMatches);
    const filteredFallback = fallback.filter(providerMatches);
    const source = filteredAvailable.length ? filteredAvailable : filteredFallback;
    let matching = source.filter(
      (voice) => !filteredAvailable.length || voiceLanguagePrefix(voice.language) === targetPrefix
    );
    if (!matching.length && filteredAvailable.length) {
      matching = [...filteredAvailable];
    }
    matching.sort((left, right) => {
      if (left.localService !== right.localService) {
        return left.localService ? -1 : 1;
      }
      return left.name.localeCompare(right.name, targetLanguage || undefined);
    });
    const current = String(selectedVoice || "auto");
    if (current !== "auto" && !matching.some((voice) => voice.id === current)) {
      matching.unshift({
        id: current,
        name: `${current}（当前设置）`,
        language: "",
        localService: requestedProvider !== "edge",
        provider: requestedProvider || "system",
        available: true
      });
    }
    return matching;
  }

  const api = { mergeVoiceOptions, selectVoiceOptions, voiceLanguagePrefix };
  globalScope.LocalTubeDubVoiceHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
