(function installLocalTubePageProbe() {
  const REQUEST_EVENT = "localtube-dub:request-page-state";
  const RESPONSE_EVENT = "localtube-dub:page-state";
  const REQUEST_MESSAGE = "localtube-dub:request-page-state";
  const RESPONSE_MESSAGE = "localtube-dub:page-state";
  const CAPTION_REQUEST_EVENT = "localtube-dub:request-player-captions";
  const CAPTION_RESPONSE_EVENT = "localtube-dub:player-captions";
  const { isCaptionPayloadUrl, pickPlayerCaptionTrack, selectCurrentPlayerResponse } = globalThis.LocalTubeDubPageProbeHelpers;
  const captionPayloads = new Map();
  const captionWaiters = new Map();

  function currentVideoId() {
    try {
      return new URL(location.href).searchParams.get("v") || "";
    } catch (error) {
      return "";
    }
  }

  function safeString(value) {
    return typeof value === "string" ? value : "";
  }

  function readYtcfgValue(key) {
    try {
      if (window.ytcfg?.get) {
        return window.ytcfg.get(key);
      }
      return window.ytcfg?.data_?.[key];
    } catch (error) {
      return undefined;
    }
  }

  function readPlayerResponse() {
    const args = window.ytplayer?.config?.args || {};
    const playerVars = readYtcfgValue("PLAYER_VARS") || {};
    const moviePlayer = document.getElementById("movie_player");
    const watchFlexy = document.querySelector("ytd-watch-flexy");
    const candidates = [
      safelyCall(() => moviePlayer?.getPlayerResponse?.()),
      watchFlexy?.playerData,
      watchFlexy?.data?.playerResponse,
      watchFlexy?.__data?.data?.playerResponse,
      args.raw_player_response,
      args.player_response,
      playerVars.raw_player_response,
      playerVars.player_response,
      window.ytInitialPlayerResponse
    ];
    return selectCurrentPlayerResponse(candidates, currentVideoId());
  }

  function safelyCall(callback) {
    try {
      return callback();
    } catch (error) {
      return null;
    }
  }

  function readInnertubeConfig() {
    const context = readYtcfgValue("INNERTUBE_CONTEXT") || {};
    const client = context.client || {};
    return {
      apiKey: safeString(readYtcfgValue("INNERTUBE_API_KEY")),
      clientName: safeString(readYtcfgValue("INNERTUBE_CLIENT_NAME") || client.clientName),
      clientNameId: Number(readYtcfgValue("INNERTUBE_CLIENT_NAME") || 0),
      clientVersion: safeString(readYtcfgValue("INNERTUBE_CLIENT_VERSION") || client.clientVersion),
      visitorData: safeString(readYtcfgValue("VISITOR_DATA") || client.visitorData),
      context
    };
  }

  function readTranscriptEndpoint() {
    const data = window.ytInitialData;
    let found = null;
    walk(data, 0, (node) => {
      if (!found && node?.getTranscriptEndpoint?.params) {
        found = { params: node.getTranscriptEndpoint.params };
      }
    });
    return found;
  }

  function walk(value, depth, visit) {
    if (!value || typeof value !== "object" || depth > 14) {
      return;
    }
    visit(value);
    if (value?.getTranscriptEndpoint?.params) {
      return;
    }
    const values = Array.isArray(value) ? value : Object.values(value);
    for (const item of values) {
      if (item && typeof item === "object") {
        walk(item, depth + 1, visit);
      }
    }
  }

  function buildSnapshot() {
    return {
      href: location.href,
      videoId: currentVideoId(),
      playerResponse: readPlayerResponse(),
      innertubeConfig: readInnertubeConfig(),
      transcriptEndpoint: readTranscriptEndpoint()
    };
  }

  function respond(requestId) {
    let snapshot = {};
    let error = "";
    try {
      snapshot = buildSnapshot();
    } catch (caught) {
      error = caught?.message || String(caught);
    }
    document.dispatchEvent(
      new CustomEvent(RESPONSE_EVENT, {
        detail: {
          requestId,
          snapshot: JSON.stringify(snapshot),
          error
        }
      })
    );
    window.postMessage(
      {
        source: RESPONSE_MESSAGE,
        requestId,
        snapshot: JSON.stringify(snapshot),
        error
      },
      location.origin
    );
  }

  function respondWithCaption(requestId, payload = null) {
    document.dispatchEvent(
      new CustomEvent(CAPTION_RESPONSE_EVENT, {
        detail: { requestId, payload: JSON.stringify(payload || {}) }
      })
    );
  }

  function rememberCaptionPayload(url, text) {
    if (!isCaptionPayloadUrl(url) || !String(text || "").trim()) {
      return;
    }
    let videoId = currentVideoId();
    try {
      videoId = new URL(url, location.href).searchParams.get("v") || videoId;
    } catch (error) {
      // Keep the active video id.
    }
    if (!videoId) {
      return;
    }
    const payload = { videoId, url: String(url), text: String(text) };
    captionPayloads.set(videoId, payload);
    for (const [requestId, waiter] of captionWaiters) {
      if (waiter.videoId !== videoId) {
        continue;
      }
      clearTimeout(waiter.timer);
      captionWaiters.delete(requestId);
      respondWithCaption(requestId, payload);
    }
  }

  function installCaptionResponseCapture() {
    const originalFetch = window.fetch;
    if (typeof originalFetch === "function") {
      window.fetch = async function localTubeCaptionFetch(...args) {
        const response = await originalFetch.apply(this, args);
        const url = response?.url || String(args[0]?.url || args[0] || "");
        if (isCaptionPayloadUrl(url)) {
          response.clone().text().then((text) => rememberCaptionPayload(url, text)).catch(() => {});
        }
        return response;
      };
    }

    const xhr = window.XMLHttpRequest;
    if (!xhr?.prototype) {
      return;
    }
    const urls = new WeakMap();
    const originalOpen = xhr.prototype.open;
    const originalSend = xhr.prototype.send;
    xhr.prototype.open = function localTubeCaptionOpen(method, url, ...args) {
      urls.set(this, String(url || ""));
      return originalOpen.call(this, method, url, ...args);
    };
    xhr.prototype.send = function localTubeCaptionSend(...args) {
      const url = urls.get(this) || "";
      if (isCaptionPayloadUrl(url)) {
        this.addEventListener("load", () => {
          try {
            const text = this.responseType === "json" ? JSON.stringify(this.response) : this.responseText;
            rememberCaptionPayload(this.responseURL || url, text);
          } catch (error) {
            // Ignore non-text subtitle transports.
          }
        }, { once: true });
      }
      return originalSend.apply(this, args);
    };
  }

  function requestPlayerCaptionPayload(event) {
    const requestId = String(event?.detail?.requestId || "");
    const videoId = String(event?.detail?.videoId || currentVideoId());
    if (!requestId || !videoId) {
      return;
    }
    const cached = captionPayloads.get(videoId);
    if (cached) {
      respondWithCaption(requestId, cached);
      return;
    }

    const timer = setTimeout(() => {
      captionWaiters.delete(requestId);
      respondWithCaption(requestId);
    }, 3500);
    captionWaiters.set(requestId, { videoId, timer });

    const activateCaptions = (attempt = 0) => {
      if (!captionWaiters.has(requestId)) {
        return;
      }
      const player = document.getElementById("movie_player");
      try {
        player?.loadModule?.("captions");
        const options = player?.getOptions?.() || [];
        const moduleName = options.includes("captions") ? "captions" : options.includes("cc") ? "cc" : "captions";
        const tracks = player?.getOption?.(moduleName, "tracklist") || [];
        const track = pickPlayerCaptionTrack(tracks, event?.detail?.preferredLanguage);
        if (track) {
          player.setOption(moduleName, "track", track);
          return;
        }
      } catch (error) {
        // The player caption module may still be loading.
      }
      if (attempt < 11) {
        setTimeout(() => activateCaptions(attempt + 1), 150);
      }
    };
    activateCaptions();
  }

  installCaptionResponseCapture();
  document.addEventListener(REQUEST_EVENT, (event) => {
    respond(event?.detail?.requestId || "");
  });
  document.addEventListener(CAPTION_REQUEST_EVENT, requestPlayerCaptionPayload);

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin || event.data?.source !== REQUEST_MESSAGE) {
      return;
    }
    respond(event.data.requestId || "");
  });
})();
