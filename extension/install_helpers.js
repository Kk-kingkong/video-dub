(function installHelpers(globalScope) {
  function normalizeReleaseInfo(rawInfo, runtimeVersion) {
    const info = rawInfo && typeof rawInfo === "object" ? rawInfo : {};
    const channel = info.channel === "private-beta" || info.channel === "store" ? info.channel : "development";
    const version = String(info.version || runtimeVersion || "").trim();
    return {
      channel,
      version,
      extensionId: String(info.extensionId || "").trim(),
      engineBundleName: String(info.engineBundleName || `LocalTube-Dub-Engine-v${version}-macOS.zip`).trim(),
      engineDownloadUrl: safeHttpsUrl(info.engineDownloadUrl),
      supportUrl: safeHttpsUrl(info.supportUrl),
      signed: info.signed === true,
      notarized: info.notarized === true
    };
  }

  function safeHttpsUrl(value) {
    try {
      const url = new URL(String(value || ""));
      return url.protocol === "https:" ? url.toString() : "";
    } catch (error) {
      return "";
    }
  }

  const api = { normalizeReleaseInfo, safeHttpsUrl };
  globalScope.LocalTubeDubInstallHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
