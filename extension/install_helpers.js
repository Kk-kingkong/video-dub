(function installHelpers(globalScope) {
  const SUPPORTED_ENGINE_TARGETS = new Map([
    ["macos:arm64", "macOS Apple Silicon"],
    ["macos:x64", "macOS Intel"],
    ["windows:x64", "Windows 10/11 x64"]
  ]);

  function normalizeReleaseInfo(rawInfo, runtimeVersion) {
    const info = rawInfo && typeof rawInfo === "object" ? rawInfo : {};
    const channel = info.channel === "private-beta" || info.channel === "store" ? info.channel : "development";
    const version = String(info.version || runtimeVersion || "").trim();
    const enginePackages = normalizeEnginePackages(info.enginePackages, version);
    return {
      channel,
      version,
      extensionId: String(info.extensionId || "").trim(),
      enginePackages,
      engineDownloadUrl: safeDownloadIndexUrl(info.engineDownloadUrl),
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

  function safeDownloadIndexUrl(value) {
    const safeUrl = safeHttpsUrl(value);
    if (!safeUrl) {
      return "";
    }
    return new URL(safeUrl).pathname.toLowerCase().endsWith(".zip") ? "" : safeUrl;
  }

  function normalizeEnginePackages(value, version) {
    const packages = Array.isArray(value)
      ? value.map(normalizeEnginePackage).filter(Boolean)
      : [];
    return packages.length ? packages : defaultEnginePackages(version);
  }

  function normalizeEnginePackage(value) {
    if (!value || typeof value !== "object") {
      return null;
    }
    const platform = String(value.platform || "").trim().toLowerCase();
    const architecture = String(value.architecture || "").trim().toLowerCase();
    const target = `${platform}:${architecture}`;
    if (!SUPPORTED_ENGINE_TARGETS.has(target)) {
      return null;
    }
    const bundleName = String(value.bundleName || "").trim();
    if (!/^[A-Za-z0-9][A-Za-z0-9._ -]*\.zip$/.test(bundleName)) {
      return null;
    }
    return {
      platform,
      architecture,
      label: String(value.label || SUPPORTED_ENGINE_TARGETS.get(target)).trim(),
      bundleName,
      downloadUrl: safeHttpsUrl(value.downloadUrl)
    };
  }

  function defaultEnginePackages(version) {
    return [
      {
        platform: "macos",
        architecture: "arm64",
        label: "macOS Apple Silicon",
        bundleName: `LocalTube-Dub-Engine-v${version}-macOS-arm64.zip`,
        downloadUrl: ""
      },
      {
        platform: "macos",
        architecture: "x64",
        label: "macOS Intel",
        bundleName: `LocalTube-Dub-Engine-v${version}-macOS-x64.zip`,
        downloadUrl: ""
      },
      {
        platform: "windows",
        architecture: "x64",
        label: "Windows 10/11 x64",
        bundleName: `LocalTube-Dub-Engine-v${version}-Windows-x64.zip`,
        downloadUrl: ""
      }
    ];
  }

  const api = { normalizeReleaseInfo, safeHttpsUrl, safeDownloadIndexUrl, normalizeEnginePackages };
  globalScope.LocalTubeDubInstallHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
