let activeRecording = null;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "localtube.offscreenCancelTabAudio") {
    sendResponse({ ok: true, cancelled: cancelActiveRecording(message.requestId) });
    return false;
  }

  if (message?.type !== "localtube.offscreenRecordTabAudio") {
    return false;
  }

  recordTabAudio(message)
    .then((payload) => sendResponse(payload))
    .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
  return true;
});

async function recordTabAudio(message) {
  const streamId = message.streamId;
  const requestId = String(message.requestId || "");
  const durationMs = clamp(Number(message.durationMs || 45000), 5000, 120000);
  if (!streamId || !requestId) {
    throw new Error("Missing tab audio stream or request id");
  }
  if (activeRecording) throw new Error("另一个视频页正在录音，请完成后再试。");
  const active = { requestId, recorder: null, timer: 0, cancelled: false };
  activeRecording = active;
  let stream;
  let audioContext;
  let source;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
      video: false
    });
    if (active.cancelled) throw new Error("录音已取消");
    audioContext = new AudioContext();
    source = audioContext.createMediaStreamSource(stream);
    source.connect(audioContext.destination);
    const recording = await collectRecording(stream, durationMs, active);
    const dataUrl = await blobToDataUrl(recording.blob);
    if (active.cancelled) throw new Error("录音已取消");
    return {
      ok: true,
      mimeType: recording.mimeType,
      dataUrl,
      durationMs
    };
  } finally {
    clearTimeout(active.timer);
    if (activeRecording === active) activeRecording = null;
    stream?.getTracks().forEach((track) => track.stop());
    source?.disconnect();
    await audioContext?.close().catch(() => {});
  }
}

function collectRecording(stream, durationMs, active) {
  return new Promise((resolve, reject) => {
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks = [];
    active.recorder = recorder;

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) {
        chunks.push(event.data);
      }
    });

    recorder.addEventListener("error", () => reject(new Error("Audio recorder failed")));
    recorder.addEventListener("stop", () => {
      if (active.cancelled) {
        reject(new Error("录音已取消"));
        return;
      }
      resolve({
        mimeType,
        blob: new Blob(chunks, { type: mimeType })
      });
    });

    recorder.start(1000);
    active.timer = setTimeout(() => {
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
    }, durationMs);
  });
}

function cancelActiveRecording(requestId) {
  const active = activeRecording;
  if (!active || active.requestId !== requestId) {
    return false;
  }

  active.cancelled = true;
  clearTimeout(active.timer);
  if (active.recorder?.state && active.recorder.state !== "inactive") {
    active.recorder.stop();
  }
  return true;
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Could not read recorded audio"));
    reader.readAsDataURL(blob);
  });
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number.isFinite(value) ? value : min));
}
