(function installLocalTubePermissionHelpers(globalScope) {
  function optionalOriginForEndpoint(endpoint) {
    const value = String(endpoint || "").trim();
    if (!value) {
      return "";
    }
    const url = new URL(value);
    if (url.protocol === "http:" && ["localhost", "127.0.0.1"].includes(url.hostname)) {
      return "";
    }
    if (url.protocol !== "https:") {
      throw new Error("非本机 API Endpoint 必须使用 https");
    }
    if (/^(www\.)?youtube\.com$/i.test(url.hostname)) {
      return "";
    }
    return `${url.origin}/*`;
  }

  function collectOptionalOrigins(endpoints) {
    return Array.from(
      new Set((Array.isArray(endpoints) ? endpoints : []).map(optionalOriginForEndpoint).filter(Boolean))
    );
  }

  function optionalCapturePermissions(enabled) {
    return enabled ? ["tabCapture", "offscreen"] : [];
  }

  const api = {
    collectOptionalOrigins,
    optionalCapturePermissions,
    optionalOriginForEndpoint
  };
  globalScope.LocalTubeDubPermissionHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
