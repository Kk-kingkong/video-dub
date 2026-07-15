(function installLocalTubePageProbe() {
  const REQUEST_EVENT = "localtube-dub:request-page-state";
  const RESPONSE_EVENT = "localtube-dub:page-state";
  const REQUEST_MESSAGE = "localtube-dub:request-page-state";
  const RESPONSE_MESSAGE = "localtube-dub:page-state";
  const { selectCurrentPlayerResponse } = globalThis.LocalTubeDubPageProbeHelpers;

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

  document.addEventListener(REQUEST_EVENT, (event) => {
    respond(event?.detail?.requestId || "");
  });

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.origin !== location.origin || event.data?.source !== REQUEST_MESSAGE) {
      return;
    }
    respond(event.data.requestId || "");
  });
})();
