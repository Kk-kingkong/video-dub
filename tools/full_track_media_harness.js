(() => {
  const { syncFullTrackMediaElements } = globalThis.LocalTubeDubHelpers;
  const video = document.querySelector("[data-media='video']");
  const dub = document.querySelector("[data-media='dub']");
  const status = document.querySelector("[data-status]");
  let running = false;
  let buffering = false;
  let playPromise = null;
  let playCalls = 0;
  let rafId = 0;

  const mediaUrl = URL.createObjectURL(createWaveBlob(12));
  video.src = mediaUrl;
  dub.src = mediaUrl;
  video.preload = "auto";
  dub.preload = "auto";
  video.muted = true;
  dub.muted = true;

  function requestDubPlayback() {
    if (playPromise) {
      return playPromise;
    }
    playCalls += 1;
    const playback = dub.play();
    playPromise = playback;
    const clear = () => {
      if (playPromise === playback) {
        playPromise = null;
      }
    };
    playback.then(clear, clear);
    return playback;
  }

  function sync(forceSeek = false) {
    const result = syncFullTrackMediaElements(video, dub, {
      mixOriginal: true,
      originalVolume: 0.2,
      buffering,
      forceSeek,
      seekThreshold: 0.18
    });
    if (result.action === "play") {
      requestDubPlayback().catch(() => {});
    } else if (result.action === "stop") {
      running = false;
    }
    render(result.action);
    return result;
  }

  function tick() {
    if (!running) {
      return;
    }
    sync();
    rafId = requestAnimationFrame(tick);
  }

  function render(action = "none") {
    const snapshot = readSnapshot(action);
    status.textContent = JSON.stringify(snapshot, null, 2);
    status.dataset.action = snapshot.action;
    status.dataset.running = String(snapshot.running);
  }

  function readSnapshot(action = status.dataset.action || "none") {
    return {
      ready: video.readyState >= 2 && dub.readyState >= 2,
      running,
      action,
      buffering,
      videoPaused: video.paused,
      dubPaused: dub.paused,
      videoEnded: video.ended,
      videoTime: Number(video.currentTime.toFixed(3)),
      dubTime: Number(dub.currentTime.toFixed(3)),
      drift: Number((dub.currentTime - video.currentTime).toFixed(3)),
      videoRate: video.playbackRate,
      dubRate: dub.playbackRate,
      videoMuted: video.muted,
      videoVolume: video.volume,
      playCalls
    };
  }

  video.addEventListener("waiting", () => {
    buffering = true;
    dub.pause();
    render("pause");
  });
  video.addEventListener("playing", () => {
    buffering = false;
    if (running) {
      sync(true);
    }
  });
  video.addEventListener("seeking", () => {
    buffering = true;
    if (running) {
      sync(true);
    }
  });
  video.addEventListener("seeked", () => {
    buffering = false;
    if (running) {
      sync(true);
    }
  });
  video.addEventListener("pause", () => {
    dub.pause();
    render("pause");
  });
  video.addEventListener("ended", () => {
    running = false;
    dub.pause();
    cancelAnimationFrame(rafId);
    render("stop");
  });
  video.addEventListener("ratechange", () => {
    if (running) {
      sync();
    }
  });
  dub.addEventListener("loadedmetadata", () => {
    sync(true);
    render("ready");
  });

  document.querySelector("[data-action='start']").addEventListener("click", async () => {
    cancelAnimationFrame(rafId);
    video.currentTime = 0;
    dub.currentTime = 0;
    running = true;
    buffering = false;
    sync(true);
    await Promise.all([
      video.play(),
      requestDubPlayback().catch((error) => {
        if (error?.name !== "AbortError") {
          throw error;
        }
      })
    ]);
    if (running) {
      tick();
    }
  });
  document.querySelector("[data-action='pause']").addEventListener("click", () => video.pause());
  document.querySelector("[data-action='resume']").addEventListener("click", () => video.play());
  document.querySelector("[data-action='seek']").addEventListener("click", () => {
    video.currentTime = 4;
  });
  document.querySelector("[data-action='rate']").addEventListener("click", () => {
    video.playbackRate = video.playbackRate === 1.5 ? 1 : 1.5;
  });
  document.querySelector("[data-action='end']").addEventListener("click", () => {
    video.currentTime = Math.max(0, video.duration - 0.12);
    video.play();
  });

  globalThis.readFullTrackHarness = () => readSnapshot();
  Promise.all([
    waitForEvent(video, "loadedmetadata"),
    waitForEvent(dub, "loadedmetadata")
  ]).then(() => render("ready"));
  video.addEventListener("loadeddata", () => render("ready"));
  dub.addEventListener("loadeddata", () => render("ready"));

  function waitForEvent(element, name) {
    if (element.readyState >= 1) {
      return Promise.resolve();
    }
    return new Promise((resolve) => element.addEventListener(name, resolve, { once: true }));
  }

  function createWaveBlob(durationSeconds) {
    const sampleRate = 8000;
    const sampleCount = Math.round(sampleRate * durationSeconds);
    const buffer = new ArrayBuffer(44 + sampleCount * 2);
    const view = new DataView(buffer);
    writeAscii(view, 0, "RIFF");
    view.setUint32(4, 36 + sampleCount * 2, true);
    writeAscii(view, 8, "WAVEfmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeAscii(view, 36, "data");
    view.setUint32(40, sampleCount * 2, true);
    for (let index = 0; index < sampleCount; index += 1) {
      const sample = Math.round(Math.sin((index / sampleRate) * Math.PI * 2 * 220) * 500);
      view.setInt16(44 + index * 2, sample, true);
    }
    return new Blob([buffer], { type: "audio/wav" });
  }

  function writeAscii(view, offset, value) {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  }
})();
