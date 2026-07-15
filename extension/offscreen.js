let activeRecording = null;

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "localtube.offscreenCancelTabAudio") {
    sendResponse({ ok: true, cancelled: cancelActiveRecording() });
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
  cancelActiveRecording();
  const streamId = message.streamId;
  const durationMs = clamp(Number(message.durationMs || 45000), 5000, 120000);
  if (!streamId) {
    throw new Error("Missing tab audio stream id");
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: streamId
      }
    },
    video: false
  });

  const audioContext = new AudioContext();
  const source = audioContext.createMediaStreamSource(stream);
  source.connect(audioContext.destination);

  try {
    const recording = await collectRecording(stream, durationMs);
    return {
      ok: true,
      mimeType: recording.mimeType,
      dataUrl: await blobToDataUrl(recording.blob),
      durationMs
    };
  } finally {
    stream.getTracks().forEach((track) => track.stop());
    source.disconnect();
    await audioContext.close().catch(() => {});
  }
}

function collectRecording(stream, durationMs) {
  return new Promise((resolve, reject) => {
    const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "audio/webm";
    const recorder = new MediaRecorder(stream, { mimeType });
    const chunks = [];
    const active = {
      recorder,
      stream,
      timer: 0,
      cancelled: false
    };
    activeRecording = active;

    recorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) {
        chunks.push(event.data);
      }
    });

    recorder.addEventListener("error", () => reject(new Error("Audio recorder failed")));
    recorder.addEventListener("stop", () => {
      if (activeRecording === active) {
        activeRecording = null;
      }
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

function cancelActiveRecording() {
  const active = activeRecording;
  if (!active) {
    return false;
  }

  active.cancelled = true;
  clearTimeout(active.timer);
  active.stream?.getTracks().forEach((track) => track.stop());
  if (active.recorder?.state && active.recorder.state !== "inactive") {
    active.recorder.stop();
  } else {
    activeRecording = null;
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
