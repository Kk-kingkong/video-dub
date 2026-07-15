const extensionId = chrome.runtime.id;
const projectPath = "$HOME/Documents/code/localtube-dub";
const { normalizeReleaseInfo } = globalThis.LocalTubeDubInstallHelpers;

initializeReleaseView();

document.querySelector("#extensionId").textContent = extensionId;
document.querySelector("#dependencyCommand").textContent = `cd ${projectPath}
./scripts/install_engine_deps_macos.sh`;
document.querySelector("#startCommand").textContent = `cd ${projectPath}
./scripts/start_engine_macos.sh`;
document.querySelector("#autostartCommand").textContent = `cd ${projectPath}
./scripts/install_engine_autostart_macos.sh`;
document.querySelector("#whisperInstallCommand").textContent = `cd ${projectPath}
./scripts/install_local_whisper_macos.sh`;
document.querySelector("#macCommand").textContent = `cd ${projectPath}/companion
./install_native_host_macos.sh ${extensionId}`;
document.querySelector("#nativeDiagnoseCommand").textContent = `cd ${projectPath}
"$HOME/Library/Application Support/LocalTube Dub/engine-runtime/.venv/bin/python" \\
  "$HOME/Library/Application Support/LocalTube Dub/engine-runtime/companion/native_host.py" --health
cat "$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.localtube.dub.engine.json"`;
document.querySelector("#diagnoseCommand").textContent = `cd ${projectPath}
./scripts/install_engine_deps_macos.sh
./scripts/start_engine_macos.sh

# 另开一个终端检查 Engine：
./.venv/bin/python - <<'PY'
import json, urllib.request
print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/health', timeout=5)), ensure_ascii=False, indent=2))
PY`;
document.querySelector("#rateLimitCommand").textContent = `# 默认：使用 Chrome cookies，降低 YouTube 429/风控概率
./scripts/start_engine_macos.sh

# 如果 cookies 读取失败，临时禁用 cookies 后重启 Engine：
LOCAL_DUB_YTDLP_COOKIES_FROM_BROWSER=none ./.venv/bin/python server/local_dub_server.py`;

async function initializeReleaseView() {
  let releaseInfo = null;
  try {
    const response = await fetch(chrome.runtime.getURL("release-info.json"), { cache: "no-store" });
    if (response.ok) {
      releaseInfo = await response.json();
    }
  } catch (error) {
    releaseInfo = null;
  }
  const normalized = normalizeReleaseInfo(releaseInfo, chrome.runtime.getManifest().version);
  document.body.dataset.releaseChannel = normalized.channel;
  if (normalized.channel === "development") {
    return;
  }

  document.querySelector("#engineBundleName").textContent = normalized.engineBundleName;
  document.querySelector("#releaseSummary").textContent = normalized.signed && normalized.notarized
    ? `当前为 ${normalized.version} 正式安装包。下载与扩展版本一致的 Engine 后双击安装。`
    : `当前为 ${normalized.version} 私测安装包，尚未签名和公证。请从同一发布页下载匹配 Engine ZIP，解压后右键安装文件并选择“打开”。`;

  const downloadLink = document.querySelector("#engineDownloadLink");
  if (normalized.engineDownloadUrl) {
    downloadLink.href = normalized.engineDownloadUrl;
    downloadLink.hidden = false;
  }
  const supportText = document.querySelector("#releaseSupportText");
  if (normalized.supportUrl) {
    supportText.textContent = "安装失败或找不到匹配版本时，请打开支持页面：";
    const link = document.createElement("a");
    link.href = normalized.supportUrl;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = normalized.supportUrl;
    supportText.append(link);
  } else if (!normalized.engineDownloadUrl) {
    supportText.textContent = "当前包没有配置公开下载地址，请从提供扩展 ZIP 的同一私测发布页取得 Engine ZIP。";
  }
}

const restartButton = document.querySelector("#restartEngineButton");
const startButton = document.querySelector("#startEngineButton");
const restartStatus = document.querySelector("#restartStatus");
const installWhisperButton = document.querySelector("#installWhisperButton");
const whisperInstallStatus = document.querySelector("#whisperInstallStatus");
const installAutostartButton = document.querySelector("#installAutostartButton");
startButton?.addEventListener("click", async () => {
  startButton.disabled = true;
  restartStatus.textContent = "正在启动 Engine...";
  try {
    const response = await chrome.runtime.sendMessage({ type: "localtube.startEngine" });
    if (!response?.ok) {
      restartStatus.textContent = response?.error || "启动失败，请复制启动命令手动启动。";
      return;
    }
    restartStatus.textContent = response.payload?.upgradeRequired
      ? `Engine 已运行，但版本过旧（${response.payload.engineVersion || "未知"}）。请重新运行当前版本 Engine 安装包，单纯重启不会更新代码。`
      : response.payload?.alreadyRunning
        ? "Engine 已经在运行。"
        : "Engine 已启动。";
  } catch (error) {
    restartStatus.textContent = "启动失败，请复制启动命令手动启动。";
  } finally {
    startButton.disabled = false;
  }
});

restartButton?.addEventListener("click", async () => {
  restartButton.disabled = true;
  restartStatus.textContent = "正在重启 Engine...";
  try {
    const response = await chrome.runtime.sendMessage({ type: "localtube.restartEngine" });
    if (!response?.ok) {
      restartStatus.textContent = response?.error || "重启失败，请复制启动命令手动启动。";
      return;
    }
    const payload = response.payload || {};
    restartStatus.textContent = payload.upgradeRequired
      ? `已重启，但仍是旧 Engine ${payload.engineVersion || "未知"}。请重新运行当前版本 Engine 安装包；重启不会替换旧代码。`
      : payload.tts
        ? "已重启，字幕和本地配音都可用。"
        : "已重启，但本地 TTS 不可用。";
  } catch (error) {
    restartStatus.textContent = "重启失败，请复制启动命令手动启动。";
  } finally {
    restartButton.disabled = false;
  }
});

installAutostartButton?.addEventListener("click", async () => {
  installAutostartButton.disabled = true;
  restartStatus.textContent = "正在安装 Engine 开机自启动...";
  try {
    const response = await chrome.runtime.sendMessage({ type: "localtube.installEngineAutostart" });
    if (!response?.ok) {
      restartStatus.textContent = response?.error || "安装失败，请复制开机自启命令手动执行。";
      return;
    }
    restartStatus.textContent = response.payload?.healthy
      ? "开机自启动已安装，Engine 正常运行。"
      : "开机自启动已安装，Engine 正在启动。";
  } catch (error) {
    restartStatus.textContent = "安装失败，请复制开机自启命令手动执行。";
  } finally {
    installAutostartButton.disabled = false;
  }
});

installWhisperButton?.addEventListener("click", async () => {
  installWhisperButton.disabled = true;
  whisperInstallStatus.textContent = "正在启动本地转写安装...";
  try {
    const response = await chrome.runtime.sendMessage({ type: "localtube.installLocalWhisper" });
    if (!response?.ok) {
      whisperInstallStatus.textContent = response?.error || "无法启动安装，请复制手动安装命令。";
      return;
    }
    whisperInstallStatus.textContent = response.payload?.alreadyRunning
      ? "安装正在后台进行，请稍候..."
      : "已开始后台安装，正在下载组件和模型...";
    pollWhisperInstallStatus();
  } catch (error) {
    whisperInstallStatus.textContent = "无法启动安装，请复制手动安装命令。";
  } finally {
    installWhisperButton.disabled = false;
  }
});

function pollWhisperInstallStatus() {
  let attempts = 0;
  const timer = setInterval(async () => {
    attempts += 1;
    const response = await chrome.runtime.sendMessage({ type: "localtube.captionEngineHealth" }).catch(() => null);
    if (response?.ok && response.payload?.whisper) {
      clearInterval(timer);
      whisperInstallStatus.textContent = "本地转写已就绪。";
      return;
    }
    if (attempts >= 60) {
      clearInterval(timer);
      whisperInstallStatus.textContent = "安装仍在进行；稍后回到扩展点击检查 Engine。";
    }
  }, 5000);
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

for (const button of document.querySelectorAll("[data-copy]")) {
  button.addEventListener("click", async () => {
    const target = document.querySelector(button.dataset.copy);
    const text = target?.textContent || "";
    if (!text) {
      return;
    }
    await navigator.clipboard.writeText(text);
    const original = button.textContent;
    button.textContent = "已复制";
    setTimeout(() => {
      button.textContent = original;
    }, 1200);
  });
}
