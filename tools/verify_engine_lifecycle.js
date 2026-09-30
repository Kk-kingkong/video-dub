const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const extension = path.resolve(__dirname, "../extension");
let storageChanged;
const context = vm.createContext({
  AbortController, URL, setTimeout, clearTimeout,
  chrome: {
    storage: { onChanged: { addListener(listener) { storageChanged = listener; } }, sync: { get: async (defaults) => defaults } },
    runtime: { getManifest: () => ({ version: "test" }), onInstalled: { addListener() {} }, onMessage: { addListener() {} } }
  },
  importScripts(...names) {
    for (const name of names) vm.runInContext(fs.readFileSync(path.join(extension, name), "utf8"), context);
  }
});
vm.runInContext(fs.readFileSync(path.join(extension, "background.js"), "utf8"), context);
const autoStart = context.autoStartCaptionHttpEngine;
const nativeMessage = context.sendNativeMessage;

async function verifyTtsDoesNotReplayAcceptedWork() {
  const originalFetch = context.fetchJson;
  const originalNative = context.sendNativeMessage;
  let nativeCalls = 0;
  context.sendNativeMessage = async () => { nativeCalls++; return { ok: true, dataUrl: "data:audio/wav;base64,AA==" }; };
  try {
    for (const failure of [
      { ok: false, status: 400, payload: { code: "TTS_VOICE_UNAVAILABLE" }, error: "invalid voice" },
      { ok: false, status: 503, payload: { code: "ENGINE_UPDATING" }, error: "updating" },
      { ok: false, code: "ENGINE_UPDATING", error: "Engine 正在自动更新" },
      new Error("本地 TTS 生成超时")
    ]) {
      context.fetchJson = async () => { if (failure instanceof Error) throw failure; return failure; };
      const result = await context.synthesizeSpeechWithEngine({ text: "test", ttsEngine: "kokoro" });
      assert.equal(result.ok, false);
      if (failure.code || failure.payload?.code) assert.equal(result.code, failure.code || failure.payload.code);
      assert.equal(nativeCalls, 0, "HTTP failures/timeouts must not replay accepted TTS through Native");
    }
    context.fetchJson = async () => { throw new TypeError("Failed to fetch"); };
    assert.equal((await context.synthesizeSpeechWithEngine({ text: "test", ttsEngine: "kokoro" })).ok, true);
    assert.equal(nativeCalls, 1, "connection failure retains the Native fallback");
  } finally {
    context.fetchJson = originalFetch;
    context.sendNativeMessage = originalNative;
  }
}

async function verifyRecordingOwnership() {
  let deliver;
  let acquire;
  let stoppedTracks = 0;
  let closedContexts = 0;
  let recorder;
  let started;
  const stream = { getTracks: () => [{ stop() { stoppedTracks++; } }] };
  const offscreen = vm.createContext({
    Blob,
    setTimeout: () => 1, clearTimeout() {},
    navigator: { mediaDevices: { getUserMedia: () => new Promise((resolve) => { acquire = resolve; }) } },
    chrome: { runtime: { onMessage: { addListener(listener) { deliver = listener; } } } },
    AudioContext: class {
      createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
      async close() { closedContexts++; }
    },
    MediaRecorder: class {
      static isTypeSupported() { return true; }
      constructor() { this.events = {}; this.state = "inactive"; recorder = this; }
      addEventListener(name, listener) { this.events[name] = listener; }
      start() { this.state = "recording"; started?.(); }
      stop() { this.state = "inactive"; this.events.stop(); }
    }
  });
  vm.runInContext(fs.readFileSync(path.join(extension, "offscreen.js"), "utf8"), offscreen);
  offscreen.blobToDataUrl = async () => "data:audio/webm;base64,AA==";
  const message = (requestId) => ({ requestId, streamId: "stream", durationMs: 5000 });
  const pending = offscreen.recordTabAudio(message("pending"));
  await assert.rejects(offscreen.recordTabAudio(message("other")), /另一个视频页/);
  assert.equal(offscreen.cancelActiveRecording("other"), false);
  assert.equal(offscreen.cancelActiveRecording("pending"), true);
  acquire(stream);
  await assert.rejects(pending, /录音已取消/);
  assert.equal(stoppedTracks, 1, "a late stream is released after cancellation during acquisition");

  offscreen.navigator.mediaDevices.getUserMedia = async () => stream;
  let startGate = new Promise((resolve) => { started = resolve; });
  const recording = offscreen.recordTabAudio(message("tab-B"));
  await startGate;
  const cancelled = assert.rejects(recording, /录音已取消/);
  context.chrome.runtime.getURL = (file) => `chrome-extension://test/${file}`;
  context.chrome.runtime.getContexts = async () => [{}];
  context.chrome.runtime.sendMessage = async (request) => new Promise((resolve) => deliver(request, {}, resolve));
  assert.equal((await context.cancelTabAudioRecording("tab-A")).recordingCancelled, false);
  assert.equal(recorder.state, "recording", "another tab cannot stop the owner");
  assert.equal((await context.cancelTabAudioRecording("tab-B")).recordingCancelled, true);
  await cancelled;
  assert.equal(stoppedTracks, 2);
  assert.equal(closedContexts, 1);

  startGate = new Promise((resolve) => { started = resolve; });
  const completed = offscreen.recordTabAudio(message("tab-C"));
  await startGate;
  recorder.stop();
  assert.equal((await completed).ok, true, "normal completion releases the slot for the next recording");
  assert.equal(stoppedTracks, 3);
  assert.equal(closedContexts, 2);
  assert.equal(offscreen.cancelActiveRecording("tab-C"), false);
}

async function verifyConsentRevocation() {
  const originalFetch = context.fetchJson;
  const originalGet = context.chrome.storage.sync.get;
  let requests = 0;
  const notifications = [];
  const stored = { microsoftTtsConsent: false };
  context.chrome.storage.sync.get = async (defaults) => ({ ...defaults, ...stored });
  context.chrome.storage.sync.set = async (settings) => Object.assign(stored, settings);
  context.chrome.tabs = {
    query: async () => [{ id: 1 }, { id: 2 }],
    sendMessage: async (id, message) => notifications.push({ id, message })
  };
  context.fetchJson = async () => { requests++; return { ok: true, payload: { job: { id: "accepted" } } }; };
  try {
    const result = await context.startDubTrack({ cues: [{ start: 0, end: 1, text: "private" }] }, {
      ttsEngine: "edge", microsoftTtsConsent: true
    });
    assert.equal(result.code, "MICROSOFT_TTS_CONSENT_REQUIRED");
    assert.equal(requests, 0, "a stale page cannot send online TTS text after revocation");
    await context.saveSettings({ ttsEngine: "edge", microsoftTtsConsent: true });
    assert.equal(stored.microsoftTtsConsent, false, "a stale settings snapshot cannot re-grant consent");
    await storageChanged({ microsoftTtsConsent: { oldValue: true, newValue: false } }, "sync");
    assert.deepEqual(notifications.map(({ id }) => id), [1, 2], "revocation reaches every YouTube tab");
    assert.ok(notifications.every(({ message }) => message.type === "localtube.settingsChanged" && message.settings.microsoftTtsConsent === false));
    await context.saveSettings({ microsoftTtsConsent: true }, { consentChanged: true });
    assert.equal(stored.microsoftTtsConsent, true, "explicit checkbox action grants consent");
    assert.equal((await context.startDubTrack({ cues: [{ text: "allowed" }] }, { ttsEngine: "edge" })).ok, true);
  } finally {
    context.fetchJson = originalFetch;
    context.chrome.storage.sync.get = originalGet;
  }
}

async function verifyResponseBodyCancellation() {
  // Deliver headers immediately, then keep the real Response stream open until abort.
  const makeResponse = (_url, { signal }) => Promise.resolve(new Response(new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"ok":'));
      const abort = () => controller.error(new DOMException("Aborted", "AbortError"));
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    }
  })));
  context.fetch = makeResponse;
  await assert.rejects(context.fetchForExtension({ url: "http://127.0.0.1/api/health", timeoutMs: 25 }), /超时/);
  const controller = new AbortController();
  const request = context.fetchForExtension({ url: "http://127.0.0.1/api/health", signal: controller.signal });
  const cancelled = assert.rejects(request, /操作已取消/);
  await new Promise((resolve) => setImmediate(resolve));
  controller.abort();
  await cancelled;
  context.fetch = async () => new Response('{"ok":true}');
  assert.equal((await context.fetchForExtension({ url: "http://127.0.0.1/api/health" })).text, '{"ok":true}');
  context.fetch = async () => { throw new TypeError("Failed to fetch"); };
  await assert.rejects(context.fetchForExtension({ url: "http://127.0.0.1/api/health" }), /Failed to fetch/);
}

async function main() {
  await verifyConsentRevocation();
  await verifyResponseBodyCancellation();
  await verifyTtsDoesNotReplayAcceptedWork();
  await verifyRecordingOwnership();
  const helpers = context.LocalTubeDubBackgroundHelpers;
  assert.match(helpers.engineUpdateNotice({ service: "localtube-dub" }), /安装一次/);
  assert.equal(helpers.engineUpdateNotice({ updates: { enabled: false } }), "");
  for (const [status, message] of [["checking", /正在检查/], ["ready", /0\.2\.9.*空闲/], ["installing", /正在自动更新/], ["failed", /继续使用当前版本/], ["idle", /自动更新已开启/]]) {
    const payload = { updates: { enabled: true, status, availableVersion: "0.2.9" } };
    assert.match(context.httpEngineSuccessPayload({ payload }).payload.updateNotice, message);
    assert.match(context.nativeEngineSuccessPayload(payload).payload.updateNotice, message);
  }
  let starts = 0;
  context.fetchForExtension = async () => { throw new TypeError("Failed to fetch"); };
  context.sendNativeMessage = async () => ({ ok: true, ytDlp: true });
  context.autoStartCaptionHttpEngine = async () => { starts++; return { ok: true }; };
  const passive = await context.checkCaptionEngineHealth();
  assert.equal(starts, 0, "passive health must never wake a sleeping Engine");
  assert.equal(passive.payload.standby, true);
  await context.checkCaptionEngineHealth({}, { startIfNeeded: true });
  assert.equal(starts, 1, "a user operation can wake the Engine");

  starts = 0;
  let requests = 0;
  context.fetchForExtension = async () => {
    requests++;
    if (requests === 1) throw new TypeError("Failed to fetch");
    return { ok: true, status: 200, text: '{"ok":true}' };
  };
  assert.equal((await context.fetchJson("http://127.0.0.1:8787/api/tts", { startEngineIfNeeded: true })).ok, true);
  assert.equal(starts, 1);
  assert.equal(requests, 2, "real work retries exactly once after waking");
  for (const [url, message] of [
    ["http://127.0.0.1:8787/api/tts", "本地 TTS 生成超时"],
    ["https://api.example.com/api/tts", "Failed to fetch"]
  ]) {
    context.fetchForExtension = async () => { throw new Error(message); };
    await assert.rejects(context.fetchJson(url, { startEngineIfNeeded: true }), new RegExp(message));
  }
  assert.equal(starts, 1, "timeouts and remote APIs must not start a local Engine");
  context.fetchForExtension = async () => ({ ok: false, status: 429, text: '{"error":"limited"}' });
  assert.equal((await context.fetchJson("http://127.0.0.1:8787/api/tts", { startEngineIfNeeded: true })).status, 429);
  assert.equal(starts, 1, "HTTP errors must not replay a potentially accepted operation");

  const controller = new AbortController();
  context.fetchForExtension = async () => { throw new Error("Failed to fetch"); };
  context.autoStartCaptionHttpEngine = async () => { controller.abort(); return { ok: true }; };
  await assert.rejects(context.fetchJson("http://127.0.0.1:8787/api/dub", {
    startEngineIfNeeded: true, signal: controller.signal, abortMessage: "已取消"
  }), /已取消/);

  context.sendNativeMessage = nativeMessage;
  let nativeCalls = 0;
  context.chrome.runtime.sendNativeMessage = () => { nativeCalls++; };
  const before = Date.now();
  await Promise.all([autoStart("http://127.0.0.1:8787", [], 30), autoStart("http://127.0.0.1:8787", [], 30)]);
  assert.equal(nativeCalls, 1, "concurrent work shares one Engine launch");
  assert.ok(Date.now() - before < 500, "a silent Native Host cannot exceed the launch deadline");

  context.chrome.runtime.id = "abcdefghijklmnopabcdefghijklmnop";
  context.chrome.runtime.sendNativeMessage = (_host, _message, callback) => {
    context.chrome.runtime.lastError = { message: "Access to the specified native messaging host is forbidden." };
    callback();
    delete context.chrome.runtime.lastError;
  };
  let recoveryPolls = 0;
  context.recoverHttpEngineAfterNativeError = async () => { recoveryPolls++; return null; };
  for (const operation of [
    () => context.startLocalEngine(),
    () => context.restartLocalEngine(),
    () => context.checkCaptionEngineHealth(),
    () => context.checkProviderHealth({ provider: "native" }),
    () => context.installLocalWhisper(),
    () => context.installEngineAutostart()
  ]) {
    const denied = await operation();
    assert.equal(denied.code, "NATIVE_HOST_FORBIDDEN", "an installed but unauthorized host needs binding repair, not installation advice");
    assert.ok(denied.error.includes(context.chrome.runtime.id), "repair advice identifies the current extension");
    assert.doesNotMatch(denied.error, /未安装|退出并重启 Chrome|先安装 Native Host/);
  }
  vm.runInContext("captionEngineAutoStartCooldownUntil = 0", context);
  const launchErrors = [];
  assert.equal(await autoStart("http://127.0.0.1:8787", launchErrors), null);
  assert.ok(launchErrors.join().includes(context.chrome.runtime.id));
  assert.equal(recoveryPolls, 0, "access denial cannot launch Engine and must not wait for HTTP recovery");

  context.sendNativeMessage = async () => ({ ok: false, code: "ENGINE_UPDATING", error: "Engine 正在自动更新，请稍后再试。" });
  for (const operation of [context.startLocalEngine, context.restartLocalEngine, context.installLocalWhisper, context.installEngineAutostart]) {
    assert.equal((await operation()).code, "ENGINE_UPDATING");
  }
  vm.runInContext("captionEngineAutoStartCooldownUntil = 0", context);
  assert.equal((await autoStart("http://127.0.0.1:8787")).code, "ENGINE_UPDATING");
  assert.equal(recoveryPolls, 0, "installation must not trigger repeated launch/recovery attempts");
  context.sendNativeMessage = nativeMessage;

  context.chrome.runtime.sendNativeMessage = (_host, _message, callback) => {
    context.chrome.runtime.lastError = { message: "Specified native messaging host not found." };
    callback();
    delete context.chrome.runtime.lastError;
  };
  assert.equal((await context.installEngineAutostart()).code, "NATIVE_HOST_NOT_INSTALLED", "missing hosts retain their installation advice");
  console.log("Engine lifecycle checks passed: passive health, one wake/retry, timeout/HTTP/remote and cancellation guards.");
}
const deadline = setTimeout(() => { console.error("Engine lifecycle checks timed out"); process.exitCode = 1; }, 5000);
main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(deadline));
