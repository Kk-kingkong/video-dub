#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAUNCHER = ROOT / "companion" / "native_host_launcher_macos.sh"


def request_native(launcher: Path, message: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    request = json.dumps(message).encode("utf-8")
    framed_request = struct.pack("@I", len(request)) + request
    completed = subprocess.run(
        [str(launcher)],
        input=framed_request,
        capture_output=True,
        timeout=15,
        env=env,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.decode("utf-8", errors="replace") or f"Native Host exited {completed.returncode}")
    if len(completed.stdout) < 4:
        raise SystemExit("Native Host returned an incomplete frame")

    response_length = struct.unpack("@I", completed.stdout[:4])[0]
    response_bytes = completed.stdout[4 : 4 + response_length]
    if len(response_bytes) != response_length:
        raise SystemExit("Native Host response length does not match its frame header")
    return json.loads(response_bytes.decode("utf-8"))


class FakePersistentKokoroOwner:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.state = "not-installed"
        self.generation = 0
        self.install_calls = 0
        self.cancel_calls = 0
        self.uninstall_calls = 0
        self.request_calls = 0

    def status(self) -> dict[str, Any]:
        with self.lock:
            ready = self.state == "ready"
            installing = self.state == "installing"
            return {
                "state": self.state,
                "version": "test",
                "downloadedBytes": 50 if installing else (100 if ready else 0),
                "totalBytes": 100,
                "progress": 0.5 if installing else (1.0 if ready else 0.0),
                "installedBytes": 200 if ready else 0,
                "error": "",
            }

    def install(self) -> dict[str, Any]:
        with self.lock:
            if self.state in {"installing", "ready"}:
                return self.status()
            self.install_calls += 1
            self.generation += 1
            generation = self.generation
            self.state = "installing"
        threading.Thread(target=self._finish_install, args=(generation,), daemon=True).start()
        return self.status()

    def cancel(self) -> dict[str, Any]:
        with self.lock:
            self.cancel_calls += 1
            self.generation += 1
            self.state = "not-installed"
        return self.status()

    def uninstall(self) -> dict[str, Any]:
        with self.lock:
            self.uninstall_calls += 1
            self.generation += 1
            self.state = "not-installed"
        return self.status()

    def _finish_install(self, generation: int) -> None:
        time.sleep(0.3)
        with self.lock:
            if generation == self.generation and self.state == "installing":
                self.state = "ready"


class FakeOwnerHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_GET(self) -> None:
        owner = self.server.owner  # type: ignore[attr-defined]
        if self.path == "/api/health":
            self.send_payload(
                {
                    "ok": True,
                    "service": "localtube-dub",
                    "engineVersion": "test",
                    "protocolVersion": 2,
                    "transport": "http",
                }
            )
            return
        if self.path == "/api/tts-model/kokoro/status":
            owner.request_calls += 1
            self.send_payload({"ok": True, "transport": "http", "model": owner.status()})
            return
        self.send_payload({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self) -> None:
        owner = self.server.owner  # type: ignore[attr-defined]
        content_length = int(self.headers.get("content-length", "0"))
        raw_payload = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except json.JSONDecodeError:
            payload = None
        if payload != {}:
            self.send_payload(
                {"ok": False, "code": "INVALID_MODEL_REQUEST", "transport": "http", "model": owner.status()},
                status=400,
            )
            return
        operations = {
            "/api/tts-model/kokoro/install": owner.install,
            "/api/tts-model/kokoro/cancel": owner.cancel,
            "/api/tts-model/kokoro/uninstall": owner.uninstall,
        }
        operation = operations.get(self.path)
        if operation is None:
            self.send_payload({"ok": False, "error": "Not found"}, status=404)
            return
        owner.request_calls += 1
        self.send_payload({"ok": True, "transport": "http", "model": operation()})

    def send_payload(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


def wait_for_model_state(
    launcher: Path,
    env: dict[str, str],
    expected_state: str,
    timeout_seconds: float = 3.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_response: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last_response = request_native(launcher, {"type": "kokoro-model-status"}, env)
        if last_response.get("model", {}).get("state") == expected_state:
            return last_response
        time.sleep(0.05)
    raise SystemExit(f"Native Kokoro model never reached {expected_state}: {last_response}")


def main() -> None:
    launcher = Path(os.environ.get("LOCAL_DUB_NATIVE_LAUNCHER") or DEFAULT_LAUNCHER).expanduser()
    if not launcher.is_file():
        raise SystemExit(f"Native launcher not found: {launcher}")
    native_source = (ROOT / "companion" / "native_host.py").read_text(encoding="utf-8")
    if "build_kokoro_model_payload" in native_source:
        raise SystemExit("Native model commands still call the process-local model service")
    if "127.0.0.1:8787" in native_source or "-tiTCP:8787" in native_source:
        raise SystemExit("Native host still hardcodes the Engine port")
    for required_text in ("LOCAL_DUB_ENGINE_BASE_URL", "KOKORO_MODEL_ENDPOINTS", "ownerTransport"):
        if required_text not in native_source:
            raise SystemExit(f"Native forwarding contract is missing {required_text}")

    owner = FakePersistentKokoroOwner()
    fake_http = ThreadingHTTPServer(("127.0.0.1", 0), FakeOwnerHandler)
    fake_http.owner = owner  # type: ignore[attr-defined]
    http_worker = threading.Thread(target=fake_http.serve_forever, daemon=True)
    http_worker.start()
    owner_port = int(fake_http.server_address[1])
    native_env = os.environ.copy()
    native_env["LOCAL_DUB_ENGINE_BASE_URL"] = f"http://127.0.0.1:{owner_port}"
    native_env["LOCAL_DUB_PORT"] = str(owner_port)
    native_env["LOCAL_DUB_ENGINE_START_WAIT_SECONDS"] = "1"

    try:
        response = request_native(launcher, {"type": "health"}, native_env)
        if not response.get("ok") or response.get("transport") != "native":
            raise SystemExit(f"Native Host health failed: {response}")
        if int(response.get("protocolVersion") or 0) < 2 or not response.get("engineVersion"):
            raise SystemExit(f"Native Host version metadata failed: {response}")
        voices_response = request_native(launcher, {"type": "voices"}, native_env)
        voices = voices_response.get("voices") if voices_response.get("ok") else None
        if not isinstance(voices, list):
            raise SystemExit(f"Native Host voice discovery failed: {voices_response}")

        install = request_native(launcher, {"type": "install-kokoro-model"}, native_env)
        if install.get("transport") != "native" or install.get("ownerTransport") != "http":
            raise SystemExit(f"Native install did not forward to HTTP owner: {install}")
        if install.get("model", {}).get("state") != "installing":
            raise SystemExit(f"Native install did not start persistent job: {install}")
        in_flight = request_native(launcher, {"type": "kokoro-model-status"}, native_env)
        if in_flight.get("model", {}).get("state") not in {"installing", "ready"}:
            raise SystemExit(f"Later Native process lost persistent job status: {in_flight}")
        ready = wait_for_model_state(launcher, native_env, "ready")
        if owner.install_calls != 1:
            raise SystemExit(f"Native lifecycle started {owner.install_calls} installs")
        request_native(launcher, {"type": "install-kokoro-model"}, native_env)
        if owner.install_calls != 1:
            raise SystemExit("A ready model was installed again")

        uninstall = request_native(launcher, {"type": "uninstall-kokoro-model"}, native_env)
        if uninstall.get("model", {}).get("state") != "not-installed" or owner.uninstall_calls != 1:
            raise SystemExit(f"Native uninstall did not use persistent owner: {uninstall}")

        request_native(launcher, {"type": "install-kokoro-model"}, native_env)
        cancel = request_native(launcher, {"type": "cancel-kokoro-model-install"}, native_env)
        if cancel.get("model", {}).get("state") != "not-installed" or owner.cancel_calls != 1:
            raise SystemExit(f"Native cancel did not use persistent owner: {cancel}")
        time.sleep(0.4)
        cancelled_status = request_native(launcher, {"type": "kokoro-model-status"}, native_env)
        if cancelled_status.get("model", {}).get("state") != "not-installed":
            raise SystemExit(f"Cancelled install activated late: {cancelled_status}")

        request_native(launcher, {"type": "install-kokoro-model"}, native_env)
        uninstall_in_flight = request_native(launcher, {"type": "uninstall-kokoro-model"}, native_env)
        if uninstall_in_flight.get("model", {}).get("state") != "not-installed" or owner.uninstall_calls != 2:
            raise SystemExit(f"Native in-flight uninstall did not use persistent owner: {uninstall_in_flight}")
        time.sleep(0.4)
        uninstalled_status = request_native(launcher, {"type": "kokoro-model-status"}, native_env)
        if uninstalled_status.get("model", {}).get("state") != "not-installed":
            raise SystemExit(f"Uninstalled install activated late: {uninstalled_status}")

        calls_before_invalid = owner.request_calls
        invalid_messages = [
            {"type": request_type, "payload": {"url": "https://evil.invalid/model"}}
            for request_type in (
                "kokoro-model-status",
                "install-kokoro-model",
                "cancel-kokoro-model-install",
                "uninstall-kokoro-model",
            )
        ]
        invalid_messages.extend(
            {"type": "install-kokoro-model", "payload": {field: "caller-controlled"}}
            for field in ("path", "digest", "checksum", "package", "command")
        )
        invalid_messages.append({"type": "install-kokoro-model", "command": "caller-controlled"})
        for invalid_message in invalid_messages:
            invalid = request_native(launcher, invalid_message, native_env)
            if invalid.get("code") != "INVALID_MODEL_REQUEST" or invalid.get("ok") is not False:
                raise SystemExit(f"Native Host accepted an unsafe Kokoro request: {invalid}")
        if owner.request_calls != calls_before_invalid:
            raise SystemExit("Invalid Native model request reached the HTTP owner")

        print(
            json.dumps(
                {
                    "ok": True,
                    "transport": response.get("transport"),
                    "engineVersion": response.get("engineVersion"),
                    "protocolVersion": response.get("protocolVersion"),
                    "voices": len(voices),
                    "kokoroState": uninstalled_status["model"].get("state"),
                    "persistentInstallCalls": owner.install_calls,
                    "readyTransport": ready.get("transport"),
                    "ownerTransport": ready.get("ownerTransport"),
                    "launcher": str(launcher),
                },
                ensure_ascii=False,
            )
        )
    finally:
        fake_http.shutdown()
        fake_http.server_close()
        http_worker.join(timeout=2)


if __name__ == "__main__":
    main()
