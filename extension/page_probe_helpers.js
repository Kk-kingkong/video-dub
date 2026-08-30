(function installLocalTubePageProbeHelpers(globalScope) {
  function safeJsonParse(value) {
    if (typeof value !== "string") {
      return value && typeof value === "object" ? value : null;
    }
    try {
      return JSON.parse(value);
    } catch (error) {
      return null;
    }
  }

  function normalizeTrack(track) {
    return {
      baseUrl: typeof track?.baseUrl === "string" ? track.baseUrl : "",
      languageCode: typeof track?.languageCode === "string" ? track.languageCode : "",
      kind: typeof track?.kind === "string" ? track.kind : "",
      name: track?.name || null,
      vssId: typeof track?.vssId === "string" ? track.vssId : "",
      isTranslatable: Boolean(track?.isTranslatable)
    };
  }

  function normalizePlayerResponse(rawResponse) {
    const response = safeJsonParse(rawResponse) || {};
    const tracks = response?.captions?.playerCaptionsTracklistRenderer?.captionTracks || [];
    return {
      videoDetails: {
        videoId: typeof response?.videoDetails?.videoId === "string" ? response.videoDetails.videoId : ""
      },
      captions: {
        playerCaptionsTracklistRenderer: {
          captionTracks: Array.isArray(tracks) ? tracks.map(normalizeTrack) : []
        }
      }
    };
  }

  function selectCurrentPlayerResponse(candidates, videoId) {
    const normalized = (Array.isArray(candidates) ? candidates : [])
      .map(normalizePlayerResponse)
      .filter((response) => response.videoDetails.videoId || response.captions.playerCaptionsTracklistRenderer.captionTracks.length);
    const current = normalized.filter((response) => response.videoDetails.videoId === String(videoId || ""));
    return (
      current.find((response) => response.captions.playerCaptionsTracklistRenderer.captionTracks.length) ||
      current[0] ||
      normalized.find((response) => response.captions.playerCaptionsTracklistRenderer.captionTracks.length) ||
      normalized[0] ||
      normalizePlayerResponse(null)
    );
  }

  function isCaptionPayloadUrl(value) {
    try {
      const url = new URL(String(value || ""), "https://www.youtube.com/");
      return url.protocol === "https:" &&
        (url.hostname === "youtube.com" || url.hostname.endsWith(".youtube.com")) &&
        url.pathname === "/api/timedtext";
    } catch (error) {
      return false;
    }
  }

  function pickPlayerCaptionTrack(tracks, preferredLanguage = "") {
    const list = (Array.isArray(tracks) ? tracks : []).filter((track) => track?.languageCode);
    const preferred = String(preferredLanguage || "").toLowerCase().split(/[-_]/)[0];
    const languageMatches = (track) => String(track.languageCode || "").toLowerCase().split(/[-_]/)[0] === preferred;
    return (
      list.find((track) => preferred && languageMatches(track) && track.kind !== "asr") ||
      list.find((track) => preferred && languageMatches(track)) ||
      list.find((track) => String(track.languageCode || "").toLowerCase().startsWith("en") && track.kind !== "asr") ||
      list.find((track) => track.kind !== "asr") ||
      list[0] ||
      null
    );
  }

  const api = {
    isCaptionPayloadUrl,
    normalizePlayerResponse,
    normalizeTrack,
    pickPlayerCaptionTrack,
    safeJsonParse,
    selectCurrentPlayerResponse
  };
  globalScope.LocalTubeDubPageProbeHelpers = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this);
