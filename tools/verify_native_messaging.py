#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LAUNCHER = ROOT / "companion" / "native_host_launcher_macos.sh"


def request_native(launcher: Path, request_type: str) -> dict:
    request = json.dumps({"type": request_type}).encode("utf-8")
    framed_request = struct.pack("@I", len(request)) + request
    completed = subprocess.run(
        [str(launcher)],
        input=framed_request,
        capture_output=True,
        timeout=15,
    )
    if completed.returncode != 0:
        raise SystemExit(completed.stderr.decode("utf-8", errors="replace") or f"Native Host exited {completed.returncode}")
    if len(completed.stdout) < 4:
        raise SystemExit("Native Host returned an incomplete frame")

    response_length = struct.unpack("@I", completed.stdout[:4])[0]
    response_bytes = completed.stdout[4 : 4 + response_length]
    if len(response_bytes) != response_length:
        raise SystemExit("Native Host response length does not match its frame header")
    response = json.loads(response_bytes.decode("utf-8"))
    return response


def main() -> None:
    launcher = Path(os.environ.get("LOCAL_DUB_NATIVE_LAUNCHER") or DEFAULT_LAUNCHER).expanduser()
    if not launcher.is_file():
        raise SystemExit(f"Native launcher not found: {launcher}")

    response = request_native(launcher, "health")
    if not response.get("ok") or response.get("transport") != "native":
        raise SystemExit(f"Native Host health failed: {response}")
    if int(response.get("protocolVersion") or 0) < 2 or not response.get("engineVersion"):
        raise SystemExit(f"Native Host version metadata failed: {response}")
    voices_response = request_native(launcher, "voices")
    voices = voices_response.get("voices") if voices_response.get("ok") else None
    if not isinstance(voices, list):
        raise SystemExit(f"Native Host voice discovery failed: {voices_response}")
    print(
        json.dumps(
            {
                "ok": True,
                "transport": response.get("transport"),
                "ytDlp": response.get("ytDlp"),
                "whisper": response.get("whisper"),
                "tts": response.get("tts"),
                "engineVersion": response.get("engineVersion"),
                "protocolVersion": response.get("protocolVersion"),
                "voices": len(voices),
                "launcher": str(launcher),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
