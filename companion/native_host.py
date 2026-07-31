#!/usr/bin/env python3
"""Chrome Native Messaging host for LocalTube Dub Engine."""

from __future__ import annotations

import json
import os
import subprocess
import struct
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if os.name == "nt":
    import msvcrt
else:
    msvcrt = None  # type: ignore[assignment]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

from local_dub_server import ENGINE_PROTOCOL_VERSION, PORT as DEFAULT_ENGINE_PORT, build_captions_payload, build_dub_payload, build_health_payload, build_transcribe_payload, build_tts_payload, build_video_transcribe_payload, build_voices_payload  # noqa: E402


MAX_CHROME_MESSAGE_BYTES = 64 * 1024 * 1024
UTF8_BOM = b"\xef\xbb\xbf"
NATIVE_INPUT_FIRST_FRAME = True
NATIVE_INPUT_UTF8_BOM_COMPAT = (
    os.environ.get("LOCAL_DUB_NATIVE_INPUT_UTF8_BOM_COMPAT", "").strip() == "1"
)
ENGINE_LOG_PATH = Path(tempfile.gettempdir()) / "localtube-dub-engine.log"
NATIVE_LOG_PATH = Path(tempfile.gettempdir()) / "localtube-dub-native-host.log"
WHISPER_INSTALL_LOG_PATH = Path(tempfile.gettempdir()) / "localtube-dub-whisper-install.log"
AUTOSTART_INSTALL_LOG_PATH = Path(tempfile.gettempdir()) / "localtube-dub-autostart-install.log"
ENGINE_START_WAIT_SECONDS = float(os.environ.get("LOCAL_DUB_ENGINE_START_WAIT_SECONDS", "10"))
MODEL_FORWARD_TIMEOUT_SECONDS = float(os.environ.get("LOCAL_DUB_MODEL_FORWARD_TIMEOUT_SECONDS", "5"))


def default_engine_pid_path() -> Path:
    override = os.environ.get("LOCAL_DUB_ENGINE_PID_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        product_root = (
            Path(local_app_data).expanduser()
            if local_app_data
            else Path.home() / "AppData" / "Local"
        ) / "LocalTube Dub"
        return product_root / "state" / "engine.pid"
    return Path(tempfile.gettempdir()) / "localtube-dub-engine.pid"


ENGINE_PID_PATH = default_engine_pid_path()


def windows_engine_state_path() -> Path:
    override = os.environ.get("LOCAL_DUB_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser() / "engine-state.json"
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    product_root = (
        Path(local_app_data).expanduser()
        if local_app_data
        else Path.home() / "AppData" / "Local"
    ) / "LocalTube Dub"
    return product_root / "state" / "engine-state.json"


def configured_engine_endpoint() -> tuple[str, int]:
    configured_port = int(os.environ.get("LOCAL_DUB_PORT", str(DEFAULT_ENGINE_PORT)))
    raw_base_url = os.environ.get("LOCAL_DUB_ENGINE_BASE_URL", "").strip()
    if not raw_base_url:
        return f"http://127.0.0.1:{configured_port}", configured_port
    parsed = urllib.parse.urlsplit(raw_base_url)
    if parsed.scheme.lower() != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("LOCAL_DUB_ENGINE_BASE_URL must be an HTTP loopback URL")
    if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("LOCAL_DUB_ENGINE_BASE_URL contains unsupported components")
    port = int(parsed.port or configured_port)
    return raw_base_url.rstrip("/"), port


ENGINE_BASE_URL, ENGINE_PORT = configured_engine_endpoint()
KOKORO_MODEL_ENDPOINTS = {
    "status": ("GET", "/api/tts-model/kokoro/status"),
    "install": ("POST", "/api/tts-model/kokoro/install"),
    "cancel": ("POST", "/api/tts-model/kokoro/cancel"),
    "uninstall": ("POST", "/api/tts-model/kokoro/uninstall"),
}


def configure_native_stdio() -> None:
    """Use Chrome's required binary framing on Windows."""

    global NATIVE_INPUT_FIRST_FRAME
    NATIVE_INPUT_FIRST_FRAME = True
    if os.name != "nt" or msvcrt is None:
        return
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)


def native_log(message: str) -> None:
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with open(NATIVE_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


def normalize_initial_native_length_header(raw_length: bytes, reader) -> bytes:
    if not raw_length.startswith(UTF8_BOM):
        return raw_length
    continuation = reader(3)
    if len(continuation) != 3:
        raise RuntimeError("Incomplete Native Messaging length header after UTF-8 BOM")
    return raw_length[len(UTF8_BOM):] + continuation


def read_native_message() -> dict[str, Any] | None:
    global NATIVE_INPUT_FIRST_FRAME
    raw_length = sys.stdin.buffer.read(4)
    if not raw_length:
        return None
    if len(raw_length) != 4:
        raise RuntimeError("Incomplete Native Messaging length header")
    native_log(f"native frame header={raw_length.hex()}")
    if NATIVE_INPUT_FIRST_FRAME:
        NATIVE_INPUT_FIRST_FRAME = False
        if NATIVE_INPUT_UTF8_BOM_COMPAT:
            raw_length = normalize_initial_native_length_header(
                raw_length,
                sys.stdin.buffer.read,
            )

    message_length = struct.unpack("@I", raw_length)[0]
    if message_length > MAX_CHROME_MESSAGE_BYTES:
        raise RuntimeError(f"Native message too large: {message_length} bytes")

    raw_message = sys.stdin.buffer.read(message_length)
    if len(raw_message) != message_length:
        raise RuntimeError("Incomplete Native Messaging payload")
    native_log(f"native frame payload bytes={message_length}")

    message = json.loads(raw_message.decode("utf-8"))
    if not isinstance(message, dict):
        raise RuntimeError("Native message must be a JSON object")
    return message


def write_native_message(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("@I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def handle_message(message: dict[str, Any]) -> dict[str, Any]:
    message_type = message.get("type")

    if message_type in ("ping", "health"):
        return build_health_payload(transport="native")

    if message_type in ("voices", "list-voices"):
        return build_voices_payload(transport="native")

    model_operations = {
        "kokoro-model-status": "status",
        "install-kokoro-model": "install",
        "cancel-kokoro-model-install": "cancel",
        "uninstall-kokoro-model": "uninstall",
    }
    model_operation = model_operations.get(message_type)
    if model_operation:
        return handle_kokoro_model_message(model_operation, message)

    if message_type in ("start-http", "start"):
        return start_http_engine()

    if message_type in ("restart-http", "restart"):
        return restart_http_engine()

    if message_type in ("install-whisper", "install-local-whisper"):
        return start_local_whisper_install()

    if message_type in ("install-autostart", "repair-autostart"):
        return install_engine_autostart()

    if message_type in ("dub", "translate"):
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Missing dub payload"}
        return build_dub_payload(payload, transport="native")

    if message_type == "transcribe":
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Missing transcribe payload"}
        return build_transcribe_payload(payload, transport="native")

    if message_type == "transcribe-video":
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Missing video transcribe payload"}
        return build_video_transcribe_payload(payload, transport="native")

    if message_type == "tts":
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Missing TTS payload"}
        return build_tts_payload(payload, transport="native")

    if message_type == "captions":
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return {"ok": False, "error": "Missing captions payload"}
        return build_captions_payload(payload, transport="native")

    return {"ok": False, "error": f"Unsupported Native Messaging request: {message_type}"}


def empty_model_status(error: str = "") -> dict[str, Any]:
    return {
        "state": "not-installed",
        "version": "",
        "downloadedBytes": 0,
        "totalBytes": 0,
        "progress": 0.0,
        "installedBytes": 0,
        "error": error,
    }


def invalid_model_request() -> dict[str, Any]:
    return {
        "ok": False,
        "code": "INVALID_MODEL_REQUEST",
        "error": "Kokoro model requests must use an empty object.",
        "transport": "native",
        "model": empty_model_status(),
    }


def handle_kokoro_model_message(operation: str, message: dict[str, Any]) -> dict[str, Any]:
    if set(message).difference({"type", "payload"}):
        return invalid_model_request()
    if "payload" in message and (not isinstance(message.get("payload"), dict) or message.get("payload")):
        return invalid_model_request()
    return forward_kokoro_model_operation(operation)


def forward_kokoro_model_operation(operation: str) -> dict[str, Any]:
    endpoint = KOKORO_MODEL_ENDPOINTS.get(operation)
    if endpoint is None:
        return invalid_model_request()
    engine = start_http_engine()
    if not engine.get("ok"):
        error = str(engine.get("error") or "Persistent HTTP Engine is unavailable")
        return {
            "ok": False,
            "code": "KOKORO_MODEL_ENGINE_UNAVAILABLE",
            "error": error,
            "transport": "native",
            "model": empty_model_status(error),
        }

    method, path = endpoint
    request = urllib.request.Request(
        f"{ENGINE_BASE_URL}{path}",
        data=None if method == "GET" else b"{}",
        method=method,
        headers={} if method == "GET" else {"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=MODEL_FORWARD_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {"ok": False, "error": f"HTTP Engine returned HTTP {error.code}"}
    except Exception as error:
        message = f"Persistent HTTP Engine model request failed: {error}"
        return {
            "ok": False,
            "code": "KOKORO_MODEL_ENGINE_UNAVAILABLE",
            "error": message,
            "transport": "native",
            "model": empty_model_status(message),
        }

    if not isinstance(payload, dict) or not isinstance(payload.get("model"), dict):
        message = "Persistent HTTP Engine returned an invalid model response"
        return {
            "ok": False,
            "code": "KOKORO_MODEL_ENGINE_INVALID_RESPONSE",
            "error": message,
            "transport": "native",
            "model": empty_model_status(message),
        }
    owner_transport = str(payload.get("transport") or "http")
    return {
        **payload,
        "transport": "native",
        "ownerTransport": owner_transport,
        "model": payload["model"],
    }


def start_http_engine() -> dict[str, Any]:
    if http_engine_running():
        return {"ok": True, "transport": "native", "alreadyRunning": True}

    stale_result = stop_http_engine()
    if not stale_result.get("ok"):
        return stale_result
    if stale_result.get("stopped"):
        wait_for_port_release()
    if http_engine_running():
        return {"ok": True, "transport": "native", "alreadyRunning": True}

    return launch_http_engine()


def restart_http_engine() -> dict[str, Any]:
    stop_result = stop_http_engine(force=True)
    if not stop_result.get("ok"):
        return stop_result
    wait_for_port_release()
    if http_engine_running():
        return {
            "ok": True,
            "transport": "native",
            "restarted": True,
            "managedByLaunchAgent": True,
            "logPath": str(ENGINE_LOG_PATH),
            "nativeLogPath": str(NATIVE_LOG_PATH),
        }
    started = launch_http_engine()
    if started.get("ok"):
        started["restarted"] = True
    return started


def launch_http_engine() -> dict[str, Any]:
    if http_engine_running():
        return {"ok": True, "transport": "native", "alreadyRunning": True}
    if os.name == "nt":
        return run_windows_engine_manager("Start")
    output = open(ENGINE_LOG_PATH, "ab", buffering=0)
    command = [sys.executable or "python3", str(SERVER_DIR / "local_dub_server.py")]
    env = os.environ.copy()
    env["LOCAL_DUB_PORT"] = str(ENGINE_PORT)
    runtime_bin = str(Path(sys.executable).resolve().parent)
    if os.name == "nt":
        env["PATH"] = runtime_bin + os.pathsep + env.get("PATH", "")
    else:
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    native_log(f"launch-http command={command!r} cwd={PROJECT_ROOT}")
    popen_options: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdin": subprocess.DEVNULL,
        "stdout": output,
        "stderr": output,
        "env": env,
    }
    popen_options["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **popen_options)
        ENGINE_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        ENGINE_PID_PATH.write_text(str(process.pid), encoding="ascii")
    except Exception as exc:
        native_log(f"launch-http failed: {exc}")
        return {
            "ok": False,
            "error": f"Engine 启动进程失败：{exc}。Engine 日志：{ENGINE_LOG_PATH}；Native 日志：{NATIVE_LOG_PATH}",
            "logPath": str(ENGINE_LOG_PATH),
            "nativeLogPath": str(NATIVE_LOG_PATH),
        }

    attempts = max(1, int(ENGINE_START_WAIT_SECONDS / 0.25))
    for _ in range(attempts):
        if http_engine_running():
            native_log("launch-http healthy")
            return {
                "ok": True,
                "transport": "native",
                "started": True,
                "logPath": str(ENGINE_LOG_PATH),
                "nativeLogPath": str(NATIVE_LOG_PATH),
            }
        time.sleep(0.25)

    native_log("launch-http timed out waiting for health")
    return {
        "ok": False,
        "error": f"Engine 已尝试启动，但 {ENGINE_BASE_URL} 暂未响应。Engine 日志：{ENGINE_LOG_PATH}；Native 日志：{NATIVE_LOG_PATH}",
        "logPath": str(ENGINE_LOG_PATH),
        "nativeLogPath": str(NATIVE_LOG_PATH),
    }


def start_local_whisper_install() -> dict[str, Any]:
    script_path = PROJECT_ROOT / "scripts" / "install_local_whisper_macos.sh"
    if not script_path.is_file():
        return {"ok": False, "error": f"本地转写安装脚本不存在：{script_path}"}

    if local_whisper_install_running():
        return {
            "ok": True,
            "transport": "native",
            "alreadyRunning": True,
            "logPath": str(WHISPER_INSTALL_LOG_PATH),
        }

    output = open(WHISPER_INSTALL_LOG_PATH, "ab", buffering=0)
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    try:
        subprocess.Popen(
            [str(script_path)],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            env=env,
            start_new_session=True,
        )
    except Exception as exc:
        native_log(f"install-whisper failed: {exc}")
        return {
            "ok": False,
            "error": f"本地转写安装进程启动失败：{exc}",
            "logPath": str(WHISPER_INSTALL_LOG_PATH),
        }

    native_log(f"install-whisper started log={WHISPER_INSTALL_LOG_PATH}")
    return {
        "ok": True,
        "transport": "native",
        "started": True,
        "logPath": str(WHISPER_INSTALL_LOG_PATH),
    }


def install_engine_autostart() -> dict[str, Any]:
    if os.name == "nt":
        script_path = PROJECT_ROOT / "install-engine.ps1"
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-Repair",
        ]
    else:
        script_path = PROJECT_ROOT / "scripts" / "install_engine_autostart_macos.sh"
        command = [str(script_path)]
    if not script_path.is_file():
        return {"ok": False, "error": f"Engine 自启动安装脚本不存在：{script_path}"}

    env = os.environ.copy()
    if os.name != "nt":
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:" + env.get("PATH", "")
    try:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except Exception as exc:
        native_log(f"install-autostart failed: {exc}")
        return {
            "ok": False,
            "error": f"Engine 自启动安装失败：{exc}",
            "logPath": str(AUTOSTART_INSTALL_LOG_PATH),
        }

    output = (completed.stdout or "") + (completed.stderr or "")
    try:
        AUTOSTART_INSTALL_LOG_PATH.write_text(output, encoding="utf-8")
    except Exception:
        pass
    if completed.returncode != 0:
        message = output.strip() or f"安装脚本退出码 {completed.returncode}"
        native_log(f"install-autostart failed: {message}")
        return {
            "ok": False,
            "error": f"Engine 自启动安装失败：{message}",
            "logPath": str(AUTOSTART_INSTALL_LOG_PATH),
        }

    native_log("install-autostart completed")
    return {
        "ok": True,
        "transport": "native",
        "installed": True,
        "healthy": http_engine_running(),
        "logPath": str(AUTOSTART_INSTALL_LOG_PATH),
    }


def local_whisper_install_running() -> bool:
    if os.name == "nt":
        return False
    try:
        completed = subprocess.run(
            ["pgrep", "-f", "install_local_whisper_macos.sh"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return completed.returncode == 0 and bool(completed.stdout.strip())
    except Exception:
        return False


def stop_http_engine(force: bool = False) -> dict[str, Any]:
    if os.name == "nt":
        return stop_windows_http_engine(force)
    try:
        completed = subprocess.run(
            ["lsof", f"-tiTCP:{ENGINE_PORT}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return {"ok": True}

    pids = [item.strip() for item in completed.stdout.splitlines() if item.strip()]
    if not pids:
        return {"ok": True}

    stopped = False
    for pid in pids:
        command = process_command(pid)
        if "local_dub_server.py" not in command:
            return {
                "ok": False,
                "error": f"127.0.0.1:{ENGINE_PORT} 被其他进程占用（PID {pid}）。请关闭它后再启动 Engine。{command}",
            }
        if not force and http_engine_running():
            return {"ok": True}
        try:
            os.kill(int(pid), 15)
            stopped = True
        except Exception:
            pass
    return {"ok": True, "stopped": stopped}


def stop_windows_http_engine(force: bool = False) -> dict[str, Any]:
    if not force and http_engine_running():
        return {"ok": True}
    return run_windows_engine_manager("Stop")


def load_expected_engine_identity() -> dict[str, Any] | None:
    release_path = PROJECT_ROOT / "release.json"
    try:
        release = json.loads(release_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(release, dict):
        return None
    identity: dict[str, Any] = {
        "service": "localtube-dub",
        "engineVersion": str(release.get("version") or ""),
        "protocolVersion": int(release.get("protocolVersion") or 0),
        "platform": str(release.get("platform") or ""),
        "architecture": str(release.get("architecture") or ""),
        "runtimeRoot": str(PROJECT_ROOT.resolve()),
        "instanceId": "",
    }
    if os.name == "nt":
        try:
            state = json.loads(windows_engine_state_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
        if isinstance(state, dict):
            identity["instanceId"] = str(state.get("instanceId") or "")
    if (
        not identity["engineVersion"]
        or identity["protocolVersion"] <= 0
        or not identity["platform"]
        or not identity["architecture"]
    ):
        return None
    return identity


def normalized_identity_path(value: Any) -> str:
    try:
        return os.path.normcase(str(Path(str(value)).resolve()))
    except (OSError, ValueError):
        return ""


def health_matches_expected_engine(
    payload: Any,
    identity: dict[str, Any] | None = None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    expected = identity or load_expected_engine_identity()
    if not expected:
        return False
    for key in (
        "service",
        "engineVersion",
        "protocolVersion",
        "platform",
        "architecture",
    ):
        if payload.get(key) != expected.get(key):
            return False
    if normalized_identity_path(payload.get("runtimeRoot")) != normalized_identity_path(
        expected.get("runtimeRoot")
    ):
        return False
    expected_instance = str(expected.get("instanceId") or "")
    return bool(expected_instance) and payload.get("instanceId") == expected_instance


def parse_manager_payload(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        try:
            payload = json.loads(line.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload
    return None


def run_windows_engine_manager(action: str) -> dict[str, Any]:
    manager_path = PROJECT_ROOT / "manage-engine.ps1"
    identity = load_expected_engine_identity()
    if not manager_path.is_file() or not identity:
        return {
            "ok": False,
            "error": "Windows Engine 生命周期组件不完整，请重新安装 Engine。",
        }
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(manager_path),
        "-Action",
        action,
        "-ExpectedVersion",
        str(identity["engineVersion"]),
        "-ExpectedRuntimeRoot",
        str(PROJECT_ROOT),
        "-StateRootOverride",
        str(windows_engine_state_path().parent),
        "-LocalAppDataOverride",
        os.environ.get("LOCALAPPDATA", ""),
        "-Port",
        str(ENGINE_PORT),
        "-Json",
    ]
    timeout = max(15.0, ENGINE_START_WAIT_SECONDS + 10.0)
    try:
        with tempfile.TemporaryFile(
            mode="w+",
            encoding="utf-8",
            errors="replace",
        ) as stdout_file:
            with tempfile.TemporaryFile(
                mode="w+",
                encoding="utf-8",
                errors="replace",
            ) as stderr_file:
                process = subprocess.Popen(
                    command,
                    cwd=str(PROJECT_ROOT),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    text=True,
                )
                try:
                    returncode = process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                    return {
                        "ok": False,
                        "error": (
                            "Windows Engine 生命周期操作超时；已停止未完成的进程。"
                        ),
                    }
                stdout_file.flush()
                stderr_file.flush()
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read()
                stderr = stderr_file.read()
    except Exception as error:
        return {"ok": False, "error": f"Windows Engine 生命周期操作失败：{error}"}
    payload = parse_manager_payload(stdout)
    if returncode != 0:
        detail = (
            (payload or {}).get("error")
            or stderr.strip()
            or stdout.strip()
            or f"PowerShell exited with {returncode}"
        )
        return {"ok": False, "error": f"Windows Engine 生命周期操作失败：{detail}"}
    if not payload or payload.get("ok") is not True:
        return {"ok": False, "error": "Windows Engine 生命周期组件返回了无效响应。"}
    return {"transport": "native", **payload}


def wait_for_port_release() -> None:
    if os.name == "nt":
        for _ in range(20):
            if not http_engine_running():
                return
            time.sleep(0.25)
        return
    for _ in range(20):
        try:
            completed = subprocess.run(
                ["lsof", f"-tiTCP:{ENGINE_PORT}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=1,
            )
            if not completed.stdout.strip():
                return
        except Exception:
            return
        time.sleep(0.25)


def process_command(pid: str) -> str:
    try:
        completed = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True, timeout=2)
        return completed.stdout.strip()
    except Exception:
        return ""


def http_engine_running() -> bool:
    try:
        with urllib.request.urlopen(f"{ENGINE_BASE_URL}/api/health", timeout=0.8) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if response.status != 200:
                return False
            if os.name == "nt":
                return health_matches_expected_engine(payload)
            return int(payload.get("protocolVersion") or 0) >= ENGINE_PROTOCOL_VERSION
    except Exception:
        return False


def native_loop() -> int:
    native_log("native host started")
    while True:
        try:
            message = read_native_message()
            if message is None:
                native_log("native host stopped: stdin closed")
                return 0
            native_log(f"native request type={message.get('type')}")
            response = handle_message(message)
            native_log("native request handled")
            write_native_message(response)
            native_log("native response written")
        except Exception as exc:
            native_log(f"native host error: {exc}")
            write_native_message({"ok": False, "error": str(exc)})
            print(f"LocalTube Dub native host error: {exc}", file=sys.stderr)


def cli_health() -> int:
    print(json.dumps(build_health_payload(transport="cli"), ensure_ascii=False, indent=2))
    return 0


def cli_demo() -> int:
    demo_payload = {
        "targetLanguage": "zh-CN",
        "sourceLanguage": "en",
        "cues": [{"id": "1", "start": 0, "end": 2, "text": "Hello from YouTube"}],
    }
    print(json.dumps(build_dub_payload(demo_payload, transport="cli"), ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--health":
        return cli_health()
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        return cli_demo()

    configure_native_stdio()
    os.chdir(PROJECT_ROOT)
    return native_loop()


if __name__ == "__main__":
    raise SystemExit(main())
