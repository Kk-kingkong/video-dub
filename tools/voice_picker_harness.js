(() => {
  const { mergeVoiceOptions, selectVoiceOptions } = globalThis.LocalTubeDubVoiceHelpers;
  const language = document.querySelector("[data-target-language]");
  const voice = document.querySelector("[data-voice]");
  const status = document.querySelector("[data-status]");
  let voices = [];

  async function load() {
    try {
      const response = await fetch("http://127.0.0.1:8787/api/voices");
      const payload = await response.json();
      if (!response.ok || !payload.ok || !Array.isArray(payload.voices)) {
        throw new Error(payload.error || `HTTP ${response.status}`);
      }
      voices = mergeVoiceOptions(payload.voices);
      render();
    } catch (error) {
      status.textContent = JSON.stringify({ ok: false, error: error.message || String(error) }, null, 2);
    }
  }

  function render() {
    const options = selectVoiceOptions(voices, language.value, voice.value || "auto");
    voice.replaceChildren(new Option("自动匹配（推荐）", "auto"));
    for (const item of options) {
      voice.add(new Option(`${item.name} · ${item.language}`, item.id));
    }
    status.textContent = JSON.stringify(
      {
        ok: true,
        discovered: voices.length,
        targetLanguage: language.value,
        visible: options.length,
        allMatchTarget: options.every((item) => item.language.toLowerCase().startsWith(language.value.slice(0, 2).toLowerCase())),
        hasSpacedVoiceName: voices.some((item) => item.id === "Bad News")
      },
      null,
      2
    );
  }

  language.addEventListener("change", render);
  load();
})();
