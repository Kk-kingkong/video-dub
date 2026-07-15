(() => {
  const { syncLiveVoiceMediaElements } = globalThis.LocalTubeDubHelpers;
  const video = document.querySelector("[data-media='video']");
  const dub = document.querySelector("[data-media='dub']");
  const status = document.querySelector("[data-status]");
  const segment = { start: 1, end: 4.35, timeboxEnd: 5 };
  let running = false;
  let explicitSeek = false;
  let playPromise = null;
  let playCalls = 0;
  let playbackError = "";
  let mediaReady = false;
  let selfTest = null;
  let plannedRate = 0;
  let planVideoTime = 0;
  let planAudioTime = 0;
  let plannedVideoRate = 1;
  let lastSync = { action: "ready", playbackRate: 1, requiredRate: 1, expectedEnd: 5, lateRisk: false };
  let rafId = 0;

  video.src = URL.createObjectURL(createWaveBlob(8, 220));
  dub.src = URL.createObjectURL(createWaveBlob(3.4, 440));
  video.preload = "auto";
  dub.preload = "auto";
  video.muted = true;
  dub.muted = true;
  const mediaReadyPromise = Promise.all([waitForMetadata(video), waitForMetadata(dub)]);

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

  function sync() {
    if (plannedRate && Math.abs(plannedVideoRate - video.playbackRate) > 0.01) {
      plannedRate = 0;
    }
    lastSync = syncLiveVoiceMediaElements(video, dub, segment, {
      explicitSeek,
      finishGuard: 0.06,
      maxRateMultiplier: 1.2,
      plannedRate,
      anchorVideoTime: planVideoTime,
      anchorAudioTime: planAudioTime
    });
    if (!plannedRate || lastSync.seekTo !== null) {
      plannedRate = lastSync.plannedRate;
      plannedVideoRate = video.playbackRate;
      planVideoTime = video.currentTime;
      planAudioTime = dub.currentTime;
    }
    explicitSeek = false;
    if (lastSync.action === "play") {
      requestDubPlayback().catch(() => {});
    } else if (lastSync.action === "stop") {
      running = false;
    }
    render();
    return lastSync;
  }

  function tick() {
    if (!running) {
      return;
    }
    sync();
    rafId = requestAnimationFrame(tick);
  }

  async function startAt(videoTime) {
    try {
      playbackError = "";
      cancelAnimationFrame(rafId);
      video.pause();
      dub.pause();
      video.currentTime = videoTime;
      dub.currentTime = 0;
      video.playbackRate = 1;
      plannedRate = 0;
      running = true;
      explicitSeek = false;
      await video.play();
      sync();
      tick();
    } catch (error) {
      playbackError = `${error?.name || "Error"}: ${error?.message || String(error)}`;
      running = error?.name === "NotAllowedError";
      if (running) {
        sync();
        tick();
      }
      render();
    }
  }

  function readSnapshot() {
    return {
      ready: Number.isFinite(video.duration) && video.duration > 0 && Number.isFinite(dub.duration) && dub.duration > 0,
      running,
      action: lastSync.action,
      videoPaused: video.paused,
      dubPaused: dub.paused,
      videoTime: Number(video.currentTime.toFixed(3)),
      dubTime: Number(dub.currentTime.toFixed(3)),
      videoRate: video.playbackRate,
      dubRate: Number(dub.playbackRate.toFixed(3)),
      requiredRate: Number(lastSync.requiredRate.toFixed(3)),
      expectedEnd: Number(lastSync.expectedEnd.toFixed(3)),
      lateRisk: lastSync.lateRisk,
      playCalls,
      playbackError,
      selfTest
    };
  }

  function render() {
    const snapshot = readSnapshot();
    status.textContent = JSON.stringify(snapshot, null, 2);
    status.dataset.action = snapshot.action;
    status.dataset.running = String(snapshot.running);
  }

  document.querySelector("[data-action='start']").addEventListener("click", () => startAt(0.75));
  document.querySelector("[data-action='late']").addEventListener("click", () => startAt(2));
  document.querySelector("[data-action='pause']").addEventListener("click", () => video.pause());
  document.querySelector("[data-action='resume']").addEventListener("click", () => video.play());
  document.querySelector("[data-action='seek']").addEventListener("click", () => {
    explicitSeek = true;
    video.currentTime = 3.5;
  });
  document.querySelector("[data-action='rate']").addEventListener("click", () => {
    video.playbackRate = video.playbackRate === 1.5 ? 1 : 1.5;
  });
  document.querySelector("[data-action='self-test']").addEventListener("click", async () => {
    await mediaReadyPromise;
    video.pause();
    dub.pause();
    video.currentTime = 2;
    video.playbackRate = 1;
    dub.currentTime = 0;
    const late = syncLiveVoiceMediaElements(video, dub, segment, { finishGuard: 0.06, maxRateMultiplier: 1.2 });
    const stable = syncLiveVoiceMediaElements(video, dub, segment, {
      finishGuard: 0.06,
      maxRateMultiplier: 1.2,
      plannedRate: late.plannedRate,
      anchorVideoTime: 2,
      anchorAudioTime: 0
    });
    video.currentTime = 2.5;
    video.playbackRate = 1.5;
    dub.currentTime = 0.8;
    const fast = syncLiveVoiceMediaElements(video, dub, segment, { finishGuard: 0.06, maxRateMultiplier: 1.2 });
    video.currentTime = 3.5;
    video.playbackRate = 1;
    dub.currentTime = 0.1;
    const sought = syncLiveVoiceMediaElements(video, dub, segment, {
      explicitSeek: true,
      finishGuard: 0.06,
      maxRateMultiplier: 1.2
    });
    selfTest = {
      passed:
        late.playbackRate <= 1.2 &&
        late.expectedEnd <= 5.05 &&
        stable.playbackRate <= late.plannedRate * 1.03 + 0.001 &&
        stable.playbackRate >= late.plannedRate * 0.97 - 0.001 &&
        fast.playbackRate >= 1.5 &&
        fast.expectedEnd <= 5.05 &&
        sought.seekTo > 2.5 &&
        Math.abs(dub.currentTime - sought.seekTo) < 0.02,
      lateRate: Number(late.playbackRate.toFixed(3)),
      lateExpectedEnd: Number(late.expectedEnd.toFixed(3)),
      stableRate: Number(stable.playbackRate.toFixed(3)),
      fastRate: Number(fast.playbackRate.toFixed(3)),
      fastExpectedEnd: Number(fast.expectedEnd.toFixed(3)),
      seekTo: Number((sought.seekTo || 0).toFixed(3)),
      realDurations: [Number(video.duration.toFixed(3)), Number(dub.duration.toFixed(3))]
    };
    render();
  });
  video.addEventListener("pause", sync);
  video.addEventListener("playing", sync);
  video.addEventListener("seeking", () => {
    if (running) {
      sync();
    }
  });
  video.addEventListener("ended", () => {
    running = false;
    dub.pause();
    render();
  });
  video.addEventListener("ratechange", sync);

  globalThis.readLiveVoiceHarness = readSnapshot;
  mediaReadyPromise.then(() => {
    mediaReady = true;
    render();
  });

  function waitForMetadata(element) {
    if (element.readyState >= 1) {
      return Promise.resolve();
    }
    return new Promise((resolve) => element.addEventListener("loadedmetadata", resolve, { once: true }));
  }

  function createWaveBlob(durationSeconds, frequency) {
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
      const sample = Math.round(Math.sin((index / sampleRate) * Math.PI * 2 * frequency) * 500);
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
