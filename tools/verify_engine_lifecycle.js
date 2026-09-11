const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const extension = path.resolve(__dirname, "../extension");
const context = vm.createContext({
  AbortController, URL, setTimeout, clearTimeout,
  chrome: {
    storage: { sync: { get: async (defaults) => defaults } },
    runtime: { getManifest: () => ({ version: "test" }), onInstalled: { addListener() {} }, onMessage: { addListener() {} } }
  },
  importScripts(...names) {
    for (const name of names) vm.runInContext(fs.readFileSync(path.join(extension, name), "utf8"), context);
  }
});
vm.runInContext(fs.readFileSync(path.join(extension, "background.js"), "utf8"), context);
const autoStart = context.autoStartCaptionHttpEngine;
const nativeMessage = context.sendNativeMessage;

async function main() {
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
main().catch((error) => { console.error(error); process.exitCode = 1; });
