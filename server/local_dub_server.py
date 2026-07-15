#!/usr/bin/env python3
"""LocalTube Dub local AI bridge.

This server intentionally uses only the Python standard library so the
extension can be tested before installing a heavier AI stack. Ollama is an
optional advanced translation adapter; an unavailable translator must return
an explicit error instead of presenting original text as a successful result.
"""

from __future__ import annotations

import asyncio
from array import array
import json
import os
import base64
import functools
import hashlib
import importlib.util
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


HOST = os.environ.get("LOCAL_DUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_DUB_PORT", "8787"))
ENGINE_PROTOCOL_VERSION = 2
ENGINE_ROOT = Path(__file__).resolve().parents[1]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
WHISPER_MODEL = os.environ.get("LOCAL_DUB_WHISPER_MODEL", "base")
WHISPER_COMMAND = os.environ.get("LOCAL_DUB_WHISPER_COMMAND", "")
WHISPER_CPP_COMMAND = os.environ.get("LOCAL_DUB_WHISPER_CPP_COMMAND", "")
WHISPER_CPP_MODEL = Path(
    os.environ.get(
        "LOCAL_DUB_WHISPER_CPP_MODEL",
        str(Path.home() / "Library" / "Application Support" / "LocalTube Dub" / "models" / "ggml-base.bin"),
    )
).expanduser()
FFMPEG_COMMAND = os.environ.get("LOCAL_DUB_FFMPEG_COMMAND", "")
FFPROBE_COMMAND = os.environ.get("LOCAL_DUB_FFPROBE_COMMAND", "")
YTDLP_COMMAND = os.environ.get("LOCAL_DUB_YTDLP_COMMAND", "")
YTDLP_IMPERSONATE = os.environ.get("LOCAL_DUB_YTDLP_IMPERSONATE", "auto").strip()
YTDLP_COOKIES_FROM_BROWSER = os.environ.get("LOCAL_DUB_YTDLP_COOKIES_FROM_BROWSER", "auto").strip()
if YTDLP_COOKIES_FROM_BROWSER.lower() in ("0", "false", "none", "off", "no"):
    YTDLP_COOKIES_FROM_BROWSER = ""
REQUEST_TIMEOUT = float(os.environ.get("LOCAL_DUB_TIMEOUT", "90"))
WHISPER_TIMEOUT = float(os.environ.get("LOCAL_DUB_WHISPER_TIMEOUT", "120"))
VIDEO_TRANSCRIBE_DOWNLOAD_TIMEOUT = float(os.environ.get("LOCAL_DUB_VIDEO_TRANSCRIBE_DOWNLOAD_TIMEOUT", "45"))
VIDEO_TRANSCRIBE_MAX_SECONDS = float(os.environ.get("LOCAL_DUB_VIDEO_TRANSCRIBE_MAX_SECONDS", "90"))
FULL_TRANSCRIPT_DOWNLOAD_TIMEOUT = float(os.environ.get("LOCAL_DUB_FULL_TRANSCRIPT_DOWNLOAD_TIMEOUT", "900"))
FULL_TRANSCRIPT_WHISPER_TIMEOUT = float(os.environ.get("LOCAL_DUB_FULL_TRANSCRIPT_WHISPER_TIMEOUT", "7200"))
FULL_TRANSCRIPT_MAX_SECONDS = float(os.environ.get("LOCAL_DUB_FULL_TRANSCRIPT_MAX_SECONDS", "7200"))
FULL_TRANSCRIPT_JOB_TTL_SECONDS = float(os.environ.get("LOCAL_DUB_FULL_TRANSCRIPT_JOB_TTL_SECONDS", "3600"))
DUB_TRACK_JOB_TTL_SECONDS = float(os.environ.get("LOCAL_DUB_DUB_TRACK_JOB_TTL_SECONDS", "3600"))
DUB_TRACK_MAX_CUES = int(os.environ.get("LOCAL_DUB_DUB_TRACK_MAX_CUES", "10000"))
DUB_TRACK_MAX_TEXT_CHARS = int(os.environ.get("LOCAL_DUB_DUB_TRACK_MAX_TEXT_CHARS", "1000000"))
DUB_TRACK_MIX_TIMEOUT = float(os.environ.get("LOCAL_DUB_DUB_TRACK_MIX_TIMEOUT", "900"))
DUB_TRACK_TTS_WORKERS = max(1, min(int(os.environ.get("LOCAL_DUB_DUB_TRACK_TTS_WORKERS", "3")), 4))
DUB_TRACK_OUTPUT_DIR = Path(
    os.environ.get(
        "LOCAL_DUB_DUB_TRACK_OUTPUT_DIR",
        str(Path.home() / "Library" / "Caches" / "LocalTube Dub" / "exports"),
    )
).expanduser()
CAPTION_TIMEOUT = float(os.environ.get("LOCAL_DUB_CAPTION_TIMEOUT", "22"))
CAPTION_METADATA_TIMEOUT = float(os.environ.get("LOCAL_DUB_CAPTION_METADATA_TIMEOUT", "16"))
CAPTION_HTTP_TIMEOUT = float(os.environ.get("LOCAL_DUB_CAPTION_HTTP_TIMEOUT", "8"))
CAPTION_DOWNLOAD_TIMEOUT = float(os.environ.get("LOCAL_DUB_CAPTION_DOWNLOAD_TIMEOUT", "14"))
TTS_TIMEOUT = float(os.environ.get("LOCAL_DUB_TTS_TIMEOUT", "30"))
EDGE_TTS_VOICES = (
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（自然女声）", "language": "zh-CN", "gender": "female"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊（自然女声）", "language": "zh-CN", "gender": "female"},
    {"id": "zh-CN-YunxiNeural", "name": "云希（自然男声）", "language": "zh-CN", "gender": "male"},
    {"id": "zh-CN-YunjianNeural", "name": "云健（自然男声）", "language": "zh-CN", "gender": "male"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻（自然女聲）", "language": "zh-TW", "gender": "female"},
    {"id": "zh-TW-YunJheNeural", "name": "雲哲（自然男聲）", "language": "zh-TW", "gender": "male"},
    {"id": "en-US-JennyNeural", "name": "Jenny（自然女声）", "language": "en-US", "gender": "female"},
    {"id": "en-US-GuyNeural", "name": "Guy（自然男声）", "language": "en-US", "gender": "male"},
    {"id": "ja-JP-NanamiNeural", "name": "Nanami（自然女声）", "language": "ja-JP", "gender": "female"},
    {"id": "ja-JP-KeitaNeural", "name": "Keita（自然男声）", "language": "ja-JP", "gender": "male"},
    {"id": "ko-KR-SunHiNeural", "name": "SunHi（自然女声）", "language": "ko-KR", "gender": "female"},
    {"id": "ko-KR-InJoonNeural", "name": "InJoon（自然男声）", "language": "ko-KR", "gender": "male"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira（自然女声）", "language": "es-ES", "gender": "female"},
    {"id": "es-ES-AlvaroNeural", "name": "Alvaro（自然男声）", "language": "es-ES", "gender": "male"},
    {"id": "fr-FR-DeniseNeural", "name": "Denise（自然女声）", "language": "fr-FR", "gender": "female"},
    {"id": "fr-FR-HenriNeural", "name": "Henri（自然男声）", "language": "fr-FR", "gender": "male"},
    {"id": "de-DE-KatjaNeural", "name": "Katja（自然女声）", "language": "de-DE", "gender": "female"},
    {"id": "de-DE-ConradNeural", "name": "Conrad（自然男声）", "language": "de-DE", "gender": "male"},
    {"id": "it-IT-ElsaNeural", "name": "Elsa（自然女声）", "language": "it-IT", "gender": "female"},
    {"id": "it-IT-DiegoNeural", "name": "Diego（自然男声）", "language": "it-IT", "gender": "male"},
    {"id": "pt-BR-FranciscaNeural", "name": "Francisca（自然女声）", "language": "pt-BR", "gender": "female"},
    {"id": "pt-BR-AntonioNeural", "name": "Antonio（自然男声）", "language": "pt-BR", "gender": "male"},
    {"id": "ru-RU-SvetlanaNeural", "name": "Svetlana（自然女声）", "language": "ru-RU", "gender": "female"},
    {"id": "ru-RU-DmitryNeural", "name": "Dmitry（自然男声）", "language": "ru-RU", "gender": "male"},
    {"id": "ar-SA-ZariyahNeural", "name": "Zariyah（自然女声）", "language": "ar-SA", "gender": "female"},
    {"id": "ar-SA-HamedNeural", "name": "Hamed（自然男声）", "language": "ar-SA", "gender": "male"},
)
EDGE_TTS_DEFAULT_VOICES = {
    "zh-cn": "zh-CN-XiaoxiaoNeural",
    "zh-tw": "zh-TW-HsiaoChenNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "es": "es-ES-ElviraNeural",
    "fr": "fr-FR-DeniseNeural",
    "de": "de-DE-KatjaNeural",
    "it": "it-IT-ElsaNeural",
    "pt": "pt-BR-FranciscaNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "ar": "ar-SA-ZariyahNeural",
}
OLLAMA_HEALTH_TIMEOUT = float(os.environ.get("LOCAL_DUB_OLLAMA_HEALTH_TIMEOUT", "0.8"))
HEALTH_CACHE_SECONDS = float(os.environ.get("LOCAL_DUB_HEALTH_CACHE_SECONDS", "4"))
CAPTION_CACHE_SECONDS = int(os.environ.get("LOCAL_DUB_CAPTION_CACHE_SECONDS", "3600"))
CAPTION_CACHE_MAX_ENTRIES = max(4, int(os.environ.get("LOCAL_DUB_CAPTION_CACHE_MAX_ENTRIES", "24")))
CAPTION_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CAPTION_FAILURE_BACKOFF_SECONDS = {
    "YOUTUBE_RATE_LIMITED": 300,
    "NO_PUBLIC_CAPTIONS": 60,
    "VIDEO_UNAVAILABLE": 60,
}
CAPTION_FAILURE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CAPTION_CACHE_LOCK = threading.RLock()
CAPTION_INFLIGHT: dict[str, threading.Event] = {}
CAPTION_INFLIGHT_LOCK = threading.Lock()
CAPTION_CANDIDATE_LIMIT = int(os.environ.get("LOCAL_DUB_CAPTION_CANDIDATE_LIMIT", "12"))
CAPTION_URL_ATTEMPT_LIMIT = int(os.environ.get("LOCAL_DUB_CAPTION_URL_ATTEMPT_LIMIT", "18"))
CAPTION_TARGET_URL_ATTEMPT_LIMIT = int(os.environ.get("LOCAL_DUB_CAPTION_TARGET_URL_ATTEMPT_LIMIT", "3"))
CAPTION_DIRECT_FETCH_BUDGET = float(os.environ.get("LOCAL_DUB_CAPTION_DIRECT_FETCH_BUDGET", "6"))
HEALTH_CACHE: tuple[float, dict[str, bool]] | None = None
HEALTH_CACHE_LOCK = threading.Lock()
FULL_TRANSCRIPT_JOBS: dict[str, dict[str, Any]] = {}
FULL_TRANSCRIPT_CANCEL_EVENTS: dict[str, threading.Event] = {}
FULL_TRANSCRIPT_LOCK = threading.Lock()
DUB_TRACK_JOBS: dict[str, dict[str, Any]] = {}
DUB_TRACK_CANCEL_EVENTS: dict[str, threading.Event] = {}
DUB_TRACK_LOCK = threading.Lock()

LANGUAGE_NAMES = {
    "zh-CN": "Simplified Chinese",
    "zh-TW": "Traditional Chinese",
    "en-US": "English",
    "ja-JP": "Japanese",
    "ko-KR": "Korean",
    "es-ES": "Spanish",
    "fr-FR": "French",
    "de-DE": "German",
    "it-IT": "Italian",
    "pt-BR": "Brazilian Portuguese",
    "ru-RU": "Russian",
    "ar-SA": "Arabic",
}


class LocalDubHandler(BaseHTTPRequestHandler):
    server_version = "LocalTubeDub/0.1"

    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/dub-track/download":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("id", [""])[0]
            preview = query.get("preview", [""])[0] == "1"
            self.send_dub_track(job_id, head_only=True, inline=preview)
            return
        self.send_response(404)
        self.send_header("content-length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/api/health":
            self.send_json(build_health_payload(transport="http"))
            return

        if parsed.path == "/api/voices":
            self.send_json(build_voices_payload(transport="http"))
            return

        if parsed.path == "/api/full-transcript/status":
            job_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
            response = get_full_transcript_job(job_id)
            self.send_json(response, status=200 if response.get("ok") else 404)
            return

        if parsed.path == "/api/dub-track/status":
            job_id = urllib.parse.parse_qs(parsed.query).get("id", [""])[0]
            response = get_dub_track_job(job_id)
            self.send_json(response, status=200 if response.get("ok") else 404)
            return

        if parsed.path == "/api/dub-track/download":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("id", [""])[0]
            preview = query.get("preview", [""])[0] == "1"
            self.send_dub_track(job_id, inline=preview)
            return

        self.send_json({"ok": False, "error": "Not found"}, status=404)

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=400)
            return

        if self.path in ("/api/dub", "/api/translate"):
            self.handle_translate(payload)
            return

        if self.path == "/api/transcribe":
            self.handle_transcribe(payload)
            return

        if self.path == "/api/transcribe-video":
            self.handle_video_transcribe(payload)
            return

        if self.path == "/api/full-transcript/start":
            response = start_full_transcript_job(payload)
            self.send_json(response, status=200 if response.get("ok") else 400)
            return

        if self.path == "/api/full-transcript/cancel":
            response = cancel_full_transcript_job(str(payload.get("jobId") or ""))
            self.send_json(response, status=200 if response.get("ok") else 404)
            return

        if self.path == "/api/dub-track/start":
            response = start_dub_track_job(payload)
            self.send_json(response, status=200 if response.get("ok") else 400)
            return

        if self.path == "/api/dub-track/cancel":
            response = cancel_dub_track_job(str(payload.get("jobId") or ""))
            self.send_json(response, status=200 if response.get("ok") else 404)
            return

        if self.path == "/api/tts":
            self.handle_tts(payload)
            return

        if self.path == "/api/restart":
            self.handle_restart()
            return

        if self.path == "/api/captions":
            self.handle_captions(payload)
            return

        self.send_json({"ok": False, "error": "Not found"}, status=404)

    def handle_translate(self, payload: dict[str, Any]) -> None:
        response = build_dub_payload(payload, transport="http")
        if not response.get("ok"):
            self.send_json(response, status=400)
            return
        self.send_json(response)

    def handle_transcribe(self, payload: dict[str, Any]) -> None:
        response = build_transcribe_payload(payload, transport="http")
        if not response.get("ok"):
            self.send_json(response, status=400)
            return
        self.send_json(response)

    def handle_video_transcribe(self, payload: dict[str, Any]) -> None:
        response = build_video_transcribe_payload(payload, transport="http")
        if not response.get("ok"):
            self.send_json(response, status=400)
            return
        self.send_json(response)

    def handle_tts(self, payload: dict[str, Any]) -> None:
        response = build_tts_payload(payload, transport="http")
        if not response.get("ok"):
            self.send_json(response, status=400)
            return
        self.send_json(response)

    def handle_restart(self) -> None:
        self.send_json({"ok": True, "message": "LocalTube Dub Engine restarting"})
        threading.Timer(0.25, restart_current_process).start()

    def handle_captions(self, payload: dict[str, Any]) -> None:
        response = build_captions_payload(payload, transport="http")
        if not response.get("ok"):
            self.send_json(response, status=caption_error_http_status(str(response.get("code") or "")))
            return
        self.send_json(response)

    def read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("content-length", "0"))
        if content_length <= 0:
            return {}

        raw = self.rfile.read(content_length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-allow-methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("access-control-allow-headers", "content-type, range")
        self.end_headers()
        self.wfile.write(body)

    def send_dub_track(self, job_id: str, head_only: bool = False, inline: bool = False) -> None:
        job, path = get_dub_track_file(job_id)
        if not job or not path or job.get("status") != "completed" or not path.is_file():
            if head_only:
                self.send_response(404)
                self.send_header("content-length", "0")
                self.send_header("access-control-allow-origin", "*")
                self.end_headers()
                return
            self.send_json({"ok": False, "error": "配音音轨不存在、尚未完成或已过期。"}, status=404)
            return
        filename = str(job.get("filename") or "LocalTube-Dub-track.wav").replace('"', "")
        file_size = path.stat().st_size
        try:
            byte_range = parse_http_byte_range(self.headers.get("range", ""), file_size)
        except ValueError:
            self.send_response(416)
            self.send_header("content-range", f"bytes */{file_size}")
            self.send_header("accept-ranges", "bytes")
            self.send_header("content-length", "0")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-expose-headers", "content-length, content-range, accept-ranges")
            self.end_headers()
            return
        start, end = byte_range if byte_range else (0, max(0, file_size - 1))
        content_length = max(0, end - start + 1)
        self.send_response(206 if byte_range else 200)
        self.send_header("content-type", mime_type_for_audio_path(path))
        self.send_header("content-length", str(content_length))
        self.send_header("content-disposition", f'{"inline" if inline else "attachment"}; filename="{filename}"')
        self.send_header("accept-ranges", "bytes")
        self.send_header("cache-control", "private, max-age=3600")
        if byte_range:
            self.send_header("content-range", f"bytes {start}-{end}/{file_size}")
        self.send_header("access-control-allow-origin", "*")
        self.send_header("access-control-expose-headers", "content-length, content-range, accept-ranges")
        self.end_headers()
        if head_only:
            return
        with path.open("rb") as source:
            if not byte_range:
                shutil.copyfileobj(source, self.wfile, length=1024 * 1024)
                return
            source.seek(start)
            remaining = content_length
            while remaining > 0:
                chunk = source.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    break
                remaining -= len(chunk)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def parse_http_byte_range(header_value: str, file_size: int) -> tuple[int, int] | None:
    value = str(header_value or "").strip()
    size = max(0, int(file_size))
    if not value:
        return None
    if size <= 0 or not value.lower().startswith("bytes="):
        raise ValueError("Invalid byte range")
    spec = value[6:].strip()
    if not spec or "," in spec or "-" not in spec:
        raise ValueError("Multiple or invalid byte ranges are not supported")
    start_text, end_text = (part.strip() for part in spec.split("-", 1))
    try:
        if not start_text:
            suffix_length = int(end_text)
            if suffix_length <= 0:
                raise ValueError("Invalid suffix range")
            start = max(0, size - suffix_length)
            return start, size - 1
        start = int(start_text)
        if start < 0 or start >= size:
            raise ValueError("Unsatisfiable byte range")
        end = size - 1 if not end_text else min(size - 1, int(end_text))
        if end < start:
            raise ValueError("Invalid byte range end")
        return start, end
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid byte range") from exc


def normalize_cues(raw_cues: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_cues, list):
        return []

    cues: list[dict[str, Any]] = []
    for index, cue in enumerate(raw_cues):
        if not isinstance(cue, dict):
            continue

        text = str(cue.get("text") or "").strip()
        if not text:
            continue

        start = float(cue.get("start") or 0)
        end = float(cue.get("end") or start + 1.8)
        cues.append(
            {
                "id": str(cue.get("id") or index),
                "start": start,
                "end": max(end, start + 0.8),
                "text": text,
            }
        )

    return cues


def build_health_payload(transport: str) -> dict[str, Any]:
    health = get_runtime_health()
    return {
        "ok": True,
        "service": "localtube-dub",
        "engineVersion": get_engine_version(),
        "protocolVersion": ENGINE_PROTOCOL_VERSION,
        "transport": transport,
        "model": OLLAMA_MODEL,
        **health,
        "time": int(time.time()),
    }


@functools.lru_cache(maxsize=1)
def get_engine_version() -> str:
    candidates = [ENGINE_ROOT / "release.json", ENGINE_ROOT / "extension" / "manifest.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        version = str(payload.get("version") or "").strip()
        if version:
            return version
    return "development"


def get_runtime_health() -> dict[str, bool]:
    global HEALTH_CACHE
    now = time.monotonic()
    with HEALTH_CACHE_LOCK:
        if HEALTH_CACHE and now - HEALTH_CACHE[0] <= HEALTH_CACHE_SECONDS:
            return dict(HEALTH_CACHE[1])

        health = {
            "ollama": check_ollama(),
            "whisper": check_whisper(),
            "ytDlp": check_ytdlp(),
            "tts": check_tts(),
            "edgeTts": edge_tts_available(),
        }
        HEALTH_CACHE = (time.monotonic(), health)
        return dict(health)


def build_captions_payload(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    video_url = str(payload.get("videoUrl") or "").strip()
    video_id = str(payload.get("videoId") or "").strip()
    source_language = str(payload.get("sourceLanguage") or "auto").strip()
    target_language = str(payload.get("targetLanguage") or "").strip()
    if not video_url and video_id:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    if not video_url:
        return {"ok": False, "code": "BAD_REQUEST", "error": "Missing YouTube video URL"}

    cache_key = caption_cache_key(video_url, source_language, target_language)
    cached = get_cached_captions(cache_key)
    if cached:
        return {
            "ok": True,
            **cached,
            "transport": transport,
            "cache": True,
        }
    cached_failure = get_cached_caption_failure(cache_key)
    if cached_failure:
        return {
            "ok": False,
            **cached_failure,
            "cache": True,
        }

    request_event, is_owner = begin_caption_request(cache_key)
    if not is_owner:
        if not request_event.wait(timeout=max(5.0, CAPTION_TIMEOUT + 5.0)):
            return {
                "ok": False,
                "code": "ENGINE_TIMEOUT",
                "error": "同一视频的字幕任务仍在处理中，请稍后重试。",
            }
        cached = get_cached_captions(cache_key)
        if cached:
            return {
                "ok": True,
                **cached,
                "transport": transport,
                "cache": True,
                "coalesced": True,
            }
        cached_failure = get_cached_caption_failure(cache_key)
        if cached_failure:
            return {
                "ok": False,
                **cached_failure,
                "cache": True,
                "coalesced": True,
            }
        return {
            "ok": False,
            "code": "CAPTION_ENGINE_ERROR",
            "error": "合并的字幕任务没有返回可用结果，请稍后重试。",
        }

    try:
        result = extract_youtube_captions(video_url, source_language, target_language)
        set_cached_captions(cache_key, result)
        return {
            "ok": True,
            "engine": result["engine"],
            "transport": transport,
            "source": result["source"],
            "sourceLanguage": result["sourceLanguage"],
            "translatedByYouTube": bool(result.get("translatedByYouTube")),
            "cues": result["cues"],
        }
    except Exception as exc:
        message = str(exc)
        code = classify_caption_error(message)
        response = {
            "code": code,
            "error": message,
            "retryAfterSeconds": CAPTION_FAILURE_BACKOFF_SECONDS.get(code, 0),
        }
        set_cached_caption_failure(cache_key, response)
        return {"ok": False, **response}
    finally:
        finish_caption_request(cache_key, request_event)


def begin_caption_request(cache_key: str) -> tuple[threading.Event, bool]:
    with CAPTION_INFLIGHT_LOCK:
        current = CAPTION_INFLIGHT.get(cache_key)
        if current:
            return current, False
        event = threading.Event()
        CAPTION_INFLIGHT[cache_key] = event
        return event, True


def finish_caption_request(cache_key: str, event: threading.Event) -> None:
    with CAPTION_INFLIGHT_LOCK:
        if CAPTION_INFLIGHT.get(cache_key) is event:
            CAPTION_INFLIGHT.pop(cache_key, None)
        event.set()


def classify_caption_error(message: str) -> str:
    text = str(message or "")
    if re.search(r"VIDEO_UNAVAILABLE|video unavailable|private video|members.only|age.restricted|requested format is not available", text, re.I):
        return "VIDEO_UNAVAILABLE"
    if re.search(r"429|too many requests|rate.?limit|限流", text, re.I):
        return "YOUTUBE_RATE_LIMITED"
    if re.search(r"timeout|timed out|超时", text, re.I):
        return "ENGINE_TIMEOUT"
    if re.search(r"返回空内容|empty", text, re.I):
        return "CAPTION_EMPTY"
    if re.search(r"没有读取到可用字幕|no captions|no subtitles|subtitles are disabled", text, re.I):
        return "NO_PUBLIC_CAPTIONS"
    if re.search(r"HTTP Error|读取失败|fetch", text, re.I):
        return "CAPTION_FETCH_FAILED"
    return "CAPTION_ENGINE_ERROR"


def caption_error_http_status(code: str) -> int:
    if code == "YOUTUBE_RATE_LIMITED":
        return 429
    if code == "BAD_REQUEST":
        return 400
    if code == "NO_PUBLIC_CAPTIONS":
        return 404
    if code == "VIDEO_UNAVAILABLE":
        return 422
    if code == "ENGINE_TIMEOUT":
        return 504
    return 400


def caption_cache_key(video_url: str, source_language: str, target_language: str = "") -> str:
    return "|".join(
        [
            video_url.strip(),
            normalize_language_code(source_language) or "auto",
            normalize_language_code(target_language) or "target-auto",
        ]
    )


def get_cached_captions(cache_key: str) -> dict[str, Any] | None:
    if CAPTION_CACHE_SECONDS <= 0:
        return None
    with CAPTION_CACHE_LOCK:
        item = CAPTION_CACHE.get(cache_key)
        if not item:
            return None
        created_at, payload = item
        if time.time() - created_at > CAPTION_CACHE_SECONDS:
            CAPTION_CACHE.pop(cache_key, None)
            return None
        return payload


def set_cached_captions(cache_key: str, payload: dict[str, Any]) -> None:
    if CAPTION_CACHE_SECONDS <= 0:
        return
    with CAPTION_CACHE_LOCK:
        CAPTION_FAILURE_CACHE.pop(cache_key, None)
        CAPTION_CACHE[cache_key] = (time.time(), payload)
        while len(CAPTION_CACHE) > CAPTION_CACHE_MAX_ENTRIES:
            oldest_key = min(CAPTION_CACHE, key=lambda key: CAPTION_CACHE[key][0])
            CAPTION_CACHE.pop(oldest_key, None)


def get_cached_caption_failure(cache_key: str) -> dict[str, Any] | None:
    with CAPTION_CACHE_LOCK:
        item = CAPTION_FAILURE_CACHE.get(cache_key)
        if not item:
            return None
        created_at, payload = item
        backoff_seconds = CAPTION_FAILURE_BACKOFF_SECONDS.get(str(payload.get("code") or ""), 0)
        if time.time() - created_at > backoff_seconds:
            CAPTION_FAILURE_CACHE.pop(cache_key, None)
            return None
        remaining_seconds = max(1, int(backoff_seconds - (time.time() - created_at)))
        return {**payload, "retryAfterSeconds": remaining_seconds}


def set_cached_caption_failure(cache_key: str, payload: dict[str, Any]) -> None:
    if not CAPTION_FAILURE_BACKOFF_SECONDS.get(str(payload.get("code") or "")):
        return
    with CAPTION_CACHE_LOCK:
        CAPTION_FAILURE_CACHE[cache_key] = (time.time(), payload)


def build_dub_payload(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    cues = normalize_cues(payload.get("cues", []))
    if not cues:
        return {"ok": False, "error": "No caption cues supplied"}

    target_language = str(payload.get("targetLanguage") or "zh-CN")
    source_language = str(payload.get("sourceLanguage") or "auto")
    target_name = LANGUAGE_NAMES.get(target_language, target_language)

    try:
        translated = translate_cues_with_ollama(cues, target_name, source_language)
        warning = ""
        engine = f"ollama:{OLLAMA_MODEL}"
    except Exception as exc:
        return {
            "ok": False,
            "code": "OLLAMA_UNAVAILABLE",
            "error": f"Ollama 本地翻译不可用：{exc}",
        }

    translated_cues = []
    for cue, translated_text in zip(cues, translated):
        translated_cues.append(
            {
                "id": cue["id"],
                "start": cue["start"],
                "end": cue["end"],
                "text": cue["text"],
                "translatedText": clean_translation(translated_text),
            }
        )

    return {
        "ok": True,
        "engine": engine,
        "transport": transport,
        "targetLanguage": target_language,
        "sourceLanguage": source_language,
        "warning": warning,
        "cues": translated_cues,
    }


def build_transcribe_payload(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    try:
        audio_bytes, mime_type = decode_data_url(str(payload.get("dataUrl") or ""), str(payload.get("mimeType") or "audio/webm"))
        start_time = float(payload.get("startTime") or 0)
        duration_seconds = float(payload.get("durationSeconds") or 12)
        language = str(payload.get("language") or "").strip()
        model = str(payload.get("model") or WHISPER_MODEL).strip() or WHISPER_MODEL
        transcript = transcribe_audio_with_whisper(audio_bytes, mime_type, model, language)
        cues = whisper_payload_to_cues(transcript, start_time, duration_seconds)
        if not cues:
            return {"ok": False, "error": "本地 Whisper 没有从这段音频中识别到语音。"}

        return {
            "ok": True,
            "engine": f"whisper:{model}",
            "transport": transport,
            "sourceLanguage": transcript.get("language") or language or "auto",
            "cues": cues,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def build_video_transcribe_payload(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    video_url = str(payload.get("videoUrl") or "").strip()
    video_id = str(payload.get("videoId") or "").strip()
    if not video_url and video_id:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    if not is_supported_youtube_url(video_url):
        return {"ok": False, "error": "Only YouTube video URLs can be transcribed"}

    try:
        start_time = max(0.0, float(payload.get("startTime") or 0))
        duration_seconds = max(
            6.0,
            min(float(payload.get("durationSeconds") or 30), VIDEO_TRANSCRIBE_MAX_SECONDS),
        )
        language = str(payload.get("language") or "").strip()
        model = str(payload.get("model") or WHISPER_MODEL).strip() or WHISPER_MODEL
        audio_bytes, mime_type = download_youtube_audio_window(video_url, start_time, duration_seconds)
        transcript = transcribe_audio_with_whisper(audio_bytes, mime_type, model, language)
        cues = whisper_payload_to_cues(transcript, start_time, duration_seconds)
        return {
            "ok": True,
            "engine": f"yt-dlp+whisper:{model}",
            "transport": transport,
            "sourceLanguage": transcript.get("language") or language or "auto",
            "windowStart": start_time,
            "windowEnd": start_time + duration_seconds,
            "silence": not bool(cues),
            "cues": cues,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


class FullTranscriptCancelled(RuntimeError):
    pass


def start_full_transcript_job(payload: dict[str, Any]) -> dict[str, Any]:
    video_url = str(payload.get("videoUrl") or "").strip()
    video_id = str(payload.get("videoId") or "").strip()
    if not video_url and video_id:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
    if not is_supported_youtube_url(video_url):
        return {"ok": False, "code": "INVALID_VIDEO_URL", "error": "Only YouTube video URLs can be transcribed"}
    try:
        duration_seconds = float(payload.get("durationSeconds") or 0)
    except (TypeError, ValueError):
        duration_seconds = 0
    if not 1 <= duration_seconds <= FULL_TRANSCRIPT_MAX_SECONDS:
        return {
            "ok": False,
            "code": "INVALID_VIDEO_DURATION",
            "error": f"完整本地转写只支持 1 到 {int(FULL_TRANSCRIPT_MAX_SECONDS)} 秒的视频。",
        }
    if not check_ytdlp() or not check_whisper():
        return {
            "ok": False,
            "code": "FULL_TRANSCRIPT_ENGINE_NOT_READY",
            "error": "完整转写需要先安装 yt-dlp、ffmpeg、whisper.cpp 和本地模型。",
        }

    language = str(payload.get("language") or "").strip()
    model = str(payload.get("model") or WHISPER_MODEL).strip() or WHISPER_MODEL
    key = full_transcript_job_key(video_url, language, model)
    cleanup_full_transcript_jobs()
    with DUB_TRACK_LOCK:
        dub_track_busy = any(job.get("status") in ("queued", "rendering") for job in DUB_TRACK_JOBS.values())
    if dub_track_busy:
        return {
            "ok": False,
            "code": "HEAVY_ENGINE_JOB_BUSY",
            "error": "本地 Engine 正在生成配音音轨，请完成或取消后再准备完整字幕。",
        }
    with FULL_TRANSCRIPT_LOCK:
        for job in FULL_TRANSCRIPT_JOBS.values():
            if job.get("key") == key and job.get("status") in ("queued", "downloading", "transcribing", "completed"):
                return {"ok": True, "job": public_full_transcript_job(job), "reused": True}
        if any(job.get("status") in ("queued", "downloading", "transcribing") for job in FULL_TRANSCRIPT_JOBS.values()):
            return {
                "ok": False,
                "code": "FULL_TRANSCRIPT_BUSY",
                "error": "本地 Engine 正在准备另一个视频的完整字幕，请等待完成或先取消。",
            }

        job_id = secrets.token_urlsafe(16)
        now = time.time()
        job = {
            "id": job_id,
            "key": key,
            "videoId": video_id,
            "videoUrl": video_url,
            "durationSeconds": duration_seconds,
            "language": language,
            "model": model,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": now,
            "updatedAt": now,
            "sourceLanguage": language or "auto",
            "cues": [],
            "error": "",
        }
        cancel_event = threading.Event()
        FULL_TRANSCRIPT_JOBS[job_id] = job
        FULL_TRANSCRIPT_CANCEL_EVENTS[job_id] = cancel_event

    threading.Thread(target=run_full_transcript_job, args=(job_id, cancel_event), daemon=True).start()
    return {"ok": True, "job": public_full_transcript_job(job), "reused": False}


def get_full_transcript_job(job_id: str) -> dict[str, Any]:
    cleanup_full_transcript_jobs()
    with FULL_TRANSCRIPT_LOCK:
        job = FULL_TRANSCRIPT_JOBS.get(str(job_id or ""))
        if not job:
            return {"ok": False, "code": "FULL_TRANSCRIPT_NOT_FOUND", "error": "完整字幕任务不存在或已过期。"}
        return {"ok": True, "job": public_full_transcript_job(job)}


def cancel_full_transcript_job(job_id: str) -> dict[str, Any]:
    with FULL_TRANSCRIPT_LOCK:
        job = FULL_TRANSCRIPT_JOBS.get(str(job_id or ""))
        event = FULL_TRANSCRIPT_CANCEL_EVENTS.get(str(job_id or ""))
        if not job:
            return {"ok": False, "code": "FULL_TRANSCRIPT_NOT_FOUND", "error": "完整字幕任务不存在或已过期。"}
        if event:
            event.set()
        if job.get("status") not in ("completed", "failed", "cancelled"):
            job.update({"status": "cancelled", "stage": "cancelled", "updatedAt": time.time(), "error": "任务已取消"})
        return {"ok": True, "job": public_full_transcript_job(job)}


def full_transcript_job_key(video_url: str, language: str, model: str) -> str:
    parsed = urllib.parse.urlsplit(video_url)
    query = urllib.parse.parse_qs(parsed.query)
    video_id = query.get("v", [""])[0] if parsed.hostname != "youtu.be" else parsed.path.strip("/")
    return "|".join((video_id or video_url, normalize_language_code(language), model))


def public_full_transcript_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        key: job.get(key)
        for key in (
            "id",
            "videoId",
            "durationSeconds",
            "status",
            "stage",
            "progress",
            "createdAt",
            "updatedAt",
            "sourceLanguage",
            "cues",
            "error",
        )
    }


def cleanup_full_transcript_jobs() -> None:
    cutoff = time.time() - FULL_TRANSCRIPT_JOB_TTL_SECONDS
    with FULL_TRANSCRIPT_LOCK:
        expired = [
            job_id
            for job_id, job in FULL_TRANSCRIPT_JOBS.items()
            if float(job.get("updatedAt") or 0) < cutoff and job.get("status") in ("completed", "failed", "cancelled")
        ]
        for job_id in expired:
            FULL_TRANSCRIPT_JOBS.pop(job_id, None)
            FULL_TRANSCRIPT_CANCEL_EVENTS.pop(job_id, None)


def update_full_transcript_job(job_id: str, **updates: Any) -> None:
    with FULL_TRANSCRIPT_LOCK:
        job = FULL_TRANSCRIPT_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updatedAt"] = time.time()


def run_full_transcript_job(job_id: str, cancel_event: threading.Event) -> None:
    with FULL_TRANSCRIPT_LOCK:
        job = dict(FULL_TRANSCRIPT_JOBS.get(job_id) or {})
    if not job:
        return
    try:
        update_full_transcript_job(job_id, status="downloading", stage="downloading", progress=8)
        with tempfile.TemporaryDirectory(prefix="localtube-full-transcript-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            audio_path = download_youtube_full_audio(job["videoUrl"], temp_dir, cancel_event)
            if cancel_event.is_set():
                raise FullTranscriptCancelled("任务已取消")
            update_full_transcript_job(job_id, status="transcribing", stage="transcribing", progress=42)
            transcript = transcribe_audio_path_with_whisper(
                audio_path,
                temp_dir,
                str(job.get("model") or WHISPER_MODEL),
                str(job.get("language") or ""),
                timeout=FULL_TRANSCRIPT_WHISPER_TIMEOUT,
                cancel_event=cancel_event,
            )
            if cancel_event.is_set():
                raise FullTranscriptCancelled("任务已取消")
            cues = whisper_payload_to_cues(transcript, 0, float(job.get("durationSeconds") or 0))
            if not cues:
                raise RuntimeError("本地 Whisper 没有从完整视频音频中识别到语音。")
            update_full_transcript_job(
                job_id,
                status="completed",
                stage="completed",
                progress=100,
                sourceLanguage=transcript.get("language") or job.get("language") or "auto",
                cues=cues,
                error="",
            )
    except FullTranscriptCancelled as exc:
        update_full_transcript_job(job_id, status="cancelled", stage="cancelled", error=str(exc), cues=[])
    except Exception as exc:
        update_full_transcript_job(job_id, status="failed", stage="failed", error=str(exc), cues=[])
    finally:
        with FULL_TRANSCRIPT_LOCK:
            FULL_TRANSCRIPT_CANCEL_EVENTS.pop(job_id, None)


def start_dub_track_job(payload: dict[str, Any]) -> dict[str, Any]:
    cues = normalize_dub_track_cues(payload.get("cues"))
    if not cues:
        return {"ok": False, "code": "INVALID_DUB_TRACK_CUES", "error": "没有可渲染的翻译字幕。"}
    if len(cues) > DUB_TRACK_MAX_CUES:
        return {
            "ok": False,
            "code": "DUB_TRACK_TOO_MANY_CUES",
            "error": f"单条音轨最多支持 {DUB_TRACK_MAX_CUES} 条字幕。",
        }
    if sum(len(cue["text"]) for cue in cues) > DUB_TRACK_MAX_TEXT_CHARS:
        return {
            "ok": False,
            "code": "DUB_TRACK_TEXT_TOO_LARGE",
            "error": "配音字幕文本总量过大，无法安全生成音轨。",
        }
    duration_seconds = max(float(payload.get("durationSeconds") or 0), max(cue["end"] for cue in cues))
    if duration_seconds <= 0 or duration_seconds > FULL_TRANSCRIPT_MAX_SECONDS:
        return {
            "ok": False,
            "code": "INVALID_DUB_TRACK_DURATION",
            "error": f"配音音轨只支持最长 {int(FULL_TRANSCRIPT_MAX_SECONDS)} 秒。",
        }
    language = str(payload.get("language") or payload.get("targetLanguage") or "zh-CN").strip() or "zh-CN"
    voice = str(payload.get("voice") or payload.get("voiceId") or "auto").strip() or "auto"
    tts_engine = sanitize_tts_engine(payload.get("ttsEngine"))
    try:
        base_rate = max(0.6, min(float(payload.get("rate") or 1), 1.4))
    except (TypeError, ValueError):
        base_rate = 1.0
    mix_original = payload.get("mixOriginal") is True
    try:
        original_volume = max(0.0, min(float(payload.get("originalVolume") or 0), 1.0))
    except (TypeError, ValueError):
        return {"ok": False, "code": "INVALID_ORIGINAL_VOLUME", "error": "原声音量必须在 0 到 1 之间。"}
    video_url = str(payload.get("videoUrl") or "").strip()
    output_format = str(payload.get("outputFormat") or "wav").strip().lower()
    if output_format not in ("wav", "m4a"):
        return {
            "ok": False,
            "code": "INVALID_DUB_TRACK_FORMAT",
            "error": "完整音轨目前只支持 WAV 或 M4A。",
        }
    if mix_original and not is_supported_youtube_url(video_url):
        return {
            "ok": False,
            "code": "INVALID_DUB_TRACK_VIDEO_URL",
            "error": "混合音轨只能读取当前 YouTube 视频的原音频。",
        }
    tts_ready = edge_tts_available() if tts_engine == "edge" else check_tts()
    if not tts_ready or not find_ffmpeg_command():
        return {
            "ok": False,
            "code": "DUB_TRACK_ENGINE_NOT_READY",
            "error": "完整配音音轨需要当前配音引擎和 ffmpeg 均已就绪。",
        }
    video_id = sanitize_export_filename(str(payload.get("videoId") or "youtube-video"))
    key = dub_track_job_key(
        cues,
        language,
        voice,
        base_rate,
        tts_engine=tts_engine,
        mix_original=mix_original,
        original_volume=original_volume,
        video_url=video_url,
        output_format=output_format,
    )
    cleanup_dub_track_jobs()
    with FULL_TRANSCRIPT_LOCK:
        full_transcript_busy = any(
            job.get("status") in ("queued", "downloading", "transcribing") for job in FULL_TRANSCRIPT_JOBS.values()
        )
    if full_transcript_busy:
        return {
            "ok": False,
            "code": "HEAVY_ENGINE_JOB_BUSY",
            "error": "本地 Engine 正在生成完整字幕，请完成或取消后再导出配音音轨。",
        }

    with DUB_TRACK_LOCK:
        for job in DUB_TRACK_JOBS.values():
            if job.get("key") == key and job.get("status") in ("queued", "rendering", "completed"):
                return {"ok": True, "job": public_dub_track_job(job), "reused": True}
        if any(job.get("status") in ("queued", "rendering") for job in DUB_TRACK_JOBS.values()):
            return {
                "ok": False,
                "code": "DUB_TRACK_BUSY",
                "error": "本地 Engine 正在渲染另一条配音音轨，请等待完成或先取消。",
            }
        job_id = secrets.token_urlsafe(16)
        now = time.time()
        track_suffix = "mixed" if mix_original else "dub"
        filename = f"LocalTube-Dub_{video_id}_{sanitize_export_filename(language)}_{track_suffix}.{output_format}"
        job = {
            "id": job_id,
            "key": key,
            "videoId": video_id,
            "durationSeconds": duration_seconds,
            "language": language,
            "voice": voice,
            "ttsEngine": tts_engine,
            "rate": base_rate,
            "mixOriginal": mix_original,
            "originalVolume": original_volume,
            "videoUrl": video_url if mix_original else "",
            "outputFormat": output_format,
            "status": "queued",
            "stage": "queued",
            "progress": 1,
            "createdAt": now,
            "updatedAt": now,
            "cueCount": len(cues),
            "cues": cues,
            "filename": filename,
            "filePath": str(DUB_TRACK_OUTPUT_DIR / f"{job_id}.{output_format}"),
            "error": "",
        }
        cancel_event = threading.Event()
        DUB_TRACK_JOBS[job_id] = job
        DUB_TRACK_CANCEL_EVENTS[job_id] = cancel_event

    threading.Thread(target=run_dub_track_job, args=(job_id, cancel_event), daemon=True).start()
    return {"ok": True, "job": public_dub_track_job(job), "reused": False}


def get_dub_track_job(job_id: str) -> dict[str, Any]:
    cleanup_dub_track_jobs()
    with DUB_TRACK_LOCK:
        job = DUB_TRACK_JOBS.get(str(job_id or ""))
        if not job:
            return {"ok": False, "code": "DUB_TRACK_NOT_FOUND", "error": "配音音轨任务不存在或已过期。"}
        return {"ok": True, "job": public_dub_track_job(job)}


def get_dub_track_file(job_id: str) -> tuple[dict[str, Any] | None, Path | None]:
    cleanup_dub_track_jobs()
    with DUB_TRACK_LOCK:
        job = DUB_TRACK_JOBS.get(str(job_id or ""))
        if not job:
            return None, None
        path = Path(str(job.get("filePath") or ""))
        return dict(job), path


def cancel_dub_track_job(job_id: str) -> dict[str, Any]:
    with DUB_TRACK_LOCK:
        job = DUB_TRACK_JOBS.get(str(job_id or ""))
        event = DUB_TRACK_CANCEL_EVENTS.get(str(job_id or ""))
        if not job:
            return {"ok": False, "code": "DUB_TRACK_NOT_FOUND", "error": "配音音轨任务不存在或已过期。"}
        if event:
            event.set()
        if job.get("status") not in ("completed", "failed", "cancelled"):
            job.update({"status": "cancelled", "stage": "cancelled", "updatedAt": time.time(), "error": "任务已取消"})
        return {"ok": True, "job": public_dub_track_job(job)}


def normalize_dub_track_cues(raw_cues: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_cues, list):
        return []
    cues = []
    for item in raw_cues:
        if not isinstance(item, dict):
            continue
        text = clean_translation(item.get("translatedText") or item.get("text") or "")[:2000]
        try:
            start = max(0.0, float(item.get("start") or 0))
            end = max(start + 0.2, float(item.get("end") or start + 1.8))
        except (TypeError, ValueError):
            continue
        if text:
            cues.append({"start": start, "end": end, "text": text})
    return sorted(cues, key=lambda cue: (cue["start"], cue["end"]))


def dub_track_job_key(
    cues: list[dict[str, Any]],
    language: str,
    voice: str,
    rate: float,
    tts_engine: str = "system",
    mix_original: bool = False,
    original_volume: float = 0.0,
    video_url: str = "",
    output_format: str = "wav",
) -> str:
    payload = json.dumps(
        {
            "cues": cues,
            "language": language,
            "voice": voice,
            "ttsEngine": sanitize_tts_engine(tts_engine),
            "rate": round(rate, 3),
            "mixOriginal": bool(mix_original),
            "originalVolume": round(float(original_volume), 3) if mix_original else 0,
            "videoUrl": str(video_url or "") if mix_original else "",
            "outputFormat": "m4a" if output_format == "m4a" else "wav",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def public_dub_track_job(job: dict[str, Any]) -> dict[str, Any]:
    result = {
        key: job.get(key)
        for key in (
            "id",
            "videoId",
            "durationSeconds",
            "status",
            "stage",
            "progress",
            "createdAt",
            "updatedAt",
            "cueCount",
            "renderedCues",
            "synthesisWorkers",
            "filename",
            "ttsEngine",
            "mixOriginal",
            "originalVolume",
            "outputFormat",
            "error",
        )
    }
    if job.get("status") == "completed":
        result["downloadUrl"] = f"http://127.0.0.1:{PORT}/api/dub-track/download?id={urllib.parse.quote(str(job.get('id') or ''))}"
    return result


def cleanup_dub_track_jobs() -> None:
    cutoff = time.time() - DUB_TRACK_JOB_TTL_SECONDS
    with DUB_TRACK_LOCK:
        expired = [
            job_id
            for job_id, job in DUB_TRACK_JOBS.items()
            if float(job.get("updatedAt") or 0) < cutoff and job.get("status") in ("completed", "failed", "cancelled")
        ]
        for job_id in expired:
            job = DUB_TRACK_JOBS.pop(job_id, None) or {}
            DUB_TRACK_CANCEL_EVENTS.pop(job_id, None)
            path = Path(str(job.get("filePath") or ""))
            if path.is_file():
                path.unlink(missing_ok=True)
    if DUB_TRACK_OUTPUT_DIR.is_dir():
        for path in DUB_TRACK_OUTPUT_DIR.iterdir():
            if path.is_file() and path.suffix in (".wav", ".m4a", ".partial"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass


def update_dub_track_job(job_id: str, **updates: Any) -> None:
    with DUB_TRACK_LOCK:
        job = DUB_TRACK_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updatedAt"] = time.time()


def run_dub_track_job(job_id: str, cancel_event: threading.Event) -> None:
    with DUB_TRACK_LOCK:
        job = dict(DUB_TRACK_JOBS.get(job_id) or {})
    if not job:
        return
    output_path = Path(str(job["filePath"]))
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        rendered_segments = []
        cues = job["cues"]
        with tempfile.TemporaryDirectory(prefix="localtube-dub-track-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            original_audio_path = None
            mix_original = bool(job.get("mixOriginal"))
            original_volume = max(0.0, min(float(job.get("originalVolume") or 0), 1.0))
            output_format = "m4a" if job.get("outputFormat") == "m4a" else "wav"
            if mix_original and original_volume > 0:
                update_dub_track_job(job_id, status="rendering", stage="downloading-original", progress=3)
                original_dir = temp_dir / "original"
                original_dir.mkdir(parents=True, exist_ok=True)
                original_audio_path = download_youtube_full_audio(str(job.get("videoUrl") or ""), original_dir, cancel_event)
            synthesis_start = 14 if original_audio_path else 3
            synthesis_span = 75 if original_audio_path else 87
            worker_count = min(DUB_TRACK_TTS_WORKERS, max(1, len(cues)))
            update_dub_track_job(
                job_id,
                status="rendering",
                stage="synthesizing",
                progress=synthesis_start,
                synthesisWorkers=worker_count,
            )
            with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="localtube-tts") as executor:
                futures = {
                    executor.submit(render_dub_track_segment, index, cue, cues, job, temp_dir, cancel_event): index
                    for index, cue in enumerate(cues)
                }
                try:
                    for completed_count, future in enumerate(as_completed(futures), start=1):
                        rendered_segments.append(future.result())
                        progress = synthesis_start + int((completed_count / len(cues)) * synthesis_span)
                        update_dub_track_job(job_id, progress=progress, renderedCues=completed_count)
                except Exception:
                    cancel_event.set()
                    for future in futures:
                        future.cancel()
                    raise
            rendered_segments.sort(key=lambda segment: (float(segment["start"]), float(segment["end"])))

            if cancel_event.is_set():
                raise FullTranscriptCancelled("任务已取消")
            update_dub_track_job(job_id, stage="assembling", progress=93)
            final_wav_path = temp_dir / "final-track.wav" if output_format == "m4a" else output_path
            voice_output_path = temp_dir / "voice-track.wav" if original_audio_path else final_wav_path
            write_dub_track_wav(rendered_segments, voice_output_path, float(job["durationSeconds"]))
            if original_audio_path:
                update_dub_track_job(job_id, stage="mixing", progress=96)
                mix_dub_track_with_original(
                    original_audio_path,
                    voice_output_path,
                    final_wav_path,
                    original_volume,
                    float(job["durationSeconds"]),
                    cancel_event,
                )
            if output_format == "m4a":
                update_dub_track_job(job_id, stage="encoding", progress=98)
                encode_dub_track_m4a(final_wav_path, output_path, float(job["durationSeconds"]), cancel_event)
        update_dub_track_job(job_id, status="completed", stage="completed", progress=100, error="")
    except FullTranscriptCancelled as exc:
        output_path.unlink(missing_ok=True)
        update_dub_track_job(job_id, status="cancelled", stage="cancelled", error=str(exc))
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        update_dub_track_job(job_id, status="failed", stage="failed", error=str(exc))
    finally:
        with DUB_TRACK_LOCK:
            DUB_TRACK_CANCEL_EVENTS.pop(job_id, None)


def render_dub_track_segment(
    index: int,
    cue: dict[str, Any],
    cues: list[dict[str, Any]],
    job: dict[str, Any],
    temp_dir: Path,
    cancel_event: threading.Event,
) -> dict[str, Any]:
    if cancel_event.is_set():
        raise FullTranscriptCancelled("任务已取消")
    next_start = float(cues[index + 1]["start"]) if index + 1 < len(cues) else float(cue["end"])
    slot_end = min(float(cue["end"]), next_start) if next_start > float(cue["start"]) else float(cue["end"])
    target_duration = max(0.2, slot_end - float(cue["start"]))
    request_rate = estimate_tts_request_rate(
        str(cue["text"]), str(job["language"]), float(job["rate"]), target_duration
    )
    segment_dir = temp_dir / f"segment-{index:05d}"
    segment = synthesize_speech_to_wav_file(
        str(cue["text"]),
        str(job["language"]),
        request_rate,
        str(job["voice"]),
        target_duration,
        segment_dir,
        max_fit_rate=4.5,
        cancel_event=cancel_event,
        tts_engine=str(job.get("ttsEngine") or "system"),
    )
    return {
        "index": index,
        "start": float(cue["start"]),
        "end": slot_end,
        "path": segment["path"],
    }


def sanitize_export_filename(value: str) -> str:
    result = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "")).strip("-.")
    return result[:80] or "untitled"


def estimate_tts_request_rate(text: str, language: str, base_rate: float, target_duration: float) -> float:
    value = str(text or "").strip()
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", value))
    punctuation_pause = len(re.findall(r"[，。！？；：,.!?;:]", value)) * 0.08
    if cjk_count >= max(4, len(value) * 0.35) or normalize_language_code(language) == "zh":
        estimated_seconds = max(0.8, cjk_count / 4.4 + punctuation_pause)
    else:
        word_count = len([part for part in re.split(r"\s+", value) if part]) or max(1, (len(value) + 6) // 7)
        estimated_seconds = max(0.8, word_count / 2.7 + punctuation_pause)
    base = max(0.6, min(float(base_rate), 1.4))
    target = max(0.8, float(target_duration))
    return max(base, min(base * (estimated_seconds / target), 1.8))


def write_dub_track_wav(segments: list[dict[str, Any]], output_path: Path, duration_seconds: float) -> dict[str, Any]:
    if not segments:
        raise RuntimeError("没有可写入音轨的配音片段。")
    first_path = Path(str(segments[0]["path"]))
    with wave.open(str(first_path), "rb") as first_audio:
        channels = first_audio.getnchannels()
        sample_width = first_audio.getsampwidth()
        sample_rate = first_audio.getframerate()
        compression = first_audio.getcomptype()
    if channels <= 0 or sample_width <= 0 or sample_rate <= 0 or compression != "NONE":
        raise RuntimeError("本地 TTS 返回了不支持的 WAV 格式。")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    partial_path.unlink(missing_ok=True)
    frame_size = channels * sample_width
    current_frame = 0
    try:
        with wave.open(str(partial_path), "wb") as output:
            output.setnchannels(channels)
            output.setsampwidth(sample_width)
            output.setframerate(sample_rate)
            output.setcomptype("NONE", "not compressed")
            for segment in sorted(segments, key=lambda item: float(item.get("start") or 0)):
                segment_path = Path(str(segment["path"]))
                start_frame = max(0, round(float(segment.get("start") or 0) * sample_rate))
                end_frame = max(start_frame + 1, round(float(segment.get("end") or 0) * sample_rate))
                if start_frame > current_frame:
                    write_silent_wav_frames(output, start_frame - current_frame, frame_size)
                    current_frame = start_frame
                skip_frames = max(0, current_frame - start_frame)
                writable_frames = max(0, end_frame - current_frame)
                if writable_frames <= 0:
                    continue
                with wave.open(str(segment_path), "rb") as source:
                    if (
                        source.getnchannels() != channels
                        or source.getsampwidth() != sample_width
                        or source.getframerate() != sample_rate
                        or source.getcomptype() != "NONE"
                    ):
                        raise RuntimeError("本地 TTS 片段的 WAV 格式不一致，无法合成音轨。")
                    if skip_frames:
                        source.readframes(skip_frames)
                    data = source.readframes(writable_frames)
                    output.writeframesraw(data)
                    current_frame += len(data) // frame_size

            final_frame = max(current_frame, round(max(0.0, duration_seconds) * sample_rate))
            if final_frame > current_frame:
                write_silent_wav_frames(output, final_frame - current_frame, frame_size)
                current_frame = final_frame
        partial_path.replace(output_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return {
        "path": output_path,
        "duration": current_frame / sample_rate,
        "sampleRate": sample_rate,
        "channels": channels,
    }


def write_silent_wav_frames(output: wave.Wave_write, frame_count: int, frame_size: int) -> None:
    remaining = max(0, int(frame_count))
    silence_chunk = b"\0" * (8192 * frame_size)
    while remaining:
        chunk_frames = min(remaining, 8192)
        output.writeframesraw(silence_chunk[: chunk_frames * frame_size])
        remaining -= chunk_frames


def mix_dub_track_with_original(
    original_path: Path,
    voice_path: Path,
    output_path: Path,
    original_volume: float,
    duration_seconds: float,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    ffmpeg = find_ffmpeg_command()
    if not ffmpeg:
        raise RuntimeError("混合音轨需要 ffmpeg。")
    if not original_path.is_file() or not voice_path.is_file():
        raise RuntimeError("混合音轨缺少原声音频或配音音轨。")
    duration = max(0.2, float(duration_seconds))
    volume = max(0.0, min(float(original_volume), 1.0))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    partial_path.unlink(missing_ok=True)
    command = build_ffmpeg_dub_mix_command(
        ffmpeg,
        original_path,
        voice_path,
        partial_path,
        volume,
        duration,
    )
    try:
        completed = run_cancellable_command(command, DUB_TRACK_MIX_TIMEOUT, cancel_event)
        if completed.returncode != 0 or not partial_path.is_file() or partial_path.stat().st_size <= 44:
            message = clean_translation(completed.stderr or completed.stdout or "ffmpeg 没有生成音轨")[:500]
            raise RuntimeError(f"原声与配音混合失败：{message}")
        actual_duration = validate_wav_duration(partial_path)
        if abs(actual_duration - duration) > 0.12:
            raise RuntimeError("混合音轨时长与视频时间轴不一致。")
        partial_path.replace(output_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return {"path": output_path, "duration": actual_duration, "originalVolume": volume}


def build_ffmpeg_dub_mix_command(
    ffmpeg: str,
    original_path: Path,
    voice_path: Path,
    output_path: Path,
    original_volume: float,
    duration_seconds: float,
) -> list[str]:
    duration = max(0.2, float(duration_seconds))
    volume = max(0.0, min(float(original_volume), 1.0))
    filter_graph = (
        f"[0:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume={volume:.4f}[original];"
        f"[1:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[voice];"
        "[original][voice]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.9500:attack=5:release=50:latency=1[mixed]"
    )
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(original_path),
        "-i",
        str(voice_path),
        "-filter_complex",
        filter_graph,
        "-map",
        "[mixed]",
        "-t",
        f"{duration:.3f}",
        "-ar",
        "22050",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        "-f",
        "wav",
        str(output_path),
    ]


def encode_dub_track_m4a(
    source_path: Path,
    output_path: Path,
    duration_seconds: float,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    ffmpeg = find_ffmpeg_command()
    if not ffmpeg:
        raise RuntimeError("M4A 音轨需要 ffmpeg。")
    if not source_path.is_file():
        raise RuntimeError("M4A 编码缺少已经合成的 WAV 音轨。")
    duration = max(0.2, float(duration_seconds))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_suffix(output_path.suffix + ".partial")
    partial_path.unlink(missing_ok=True)
    command = build_ffmpeg_m4a_command(ffmpeg, source_path, partial_path, duration)
    try:
        completed = run_cancellable_command(command, DUB_TRACK_MIX_TIMEOUT, cancel_event)
        if completed.returncode != 0 or not partial_path.is_file() or partial_path.stat().st_size <= 256:
            message = clean_translation(completed.stderr or completed.stdout or "ffmpeg 没有生成 M4A")[:500]
            raise RuntimeError(f"M4A 音轨编码失败：{message}")
        actual_duration = probe_audio_duration(partial_path)
        if actual_duration > 0 and abs(actual_duration - duration) > 0.2:
            raise RuntimeError("M4A 音轨时长与视频时间轴不一致。")
        partial_path.replace(output_path)
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise
    return {"path": output_path, "duration": actual_duration or duration, "format": "m4a"}


def build_ffmpeg_m4a_command(
    ffmpeg: str,
    source_path: Path,
    output_path: Path,
    duration_seconds: float,
) -> list[str]:
    duration = max(0.2, float(duration_seconds))
    return [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-t",
        f"{duration:.3f}",
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        "-movflags",
        "+faststart",
        "-f",
        "ipod",
        str(output_path),
    ]


def probe_audio_duration(path: Path) -> float:
    ffprobe = find_ffprobe_command()
    if not ffprobe or not path.is_file():
        return 0.0
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode == 0:
            return max(0.0, float((completed.stdout or "0").strip()))
    except (OSError, subprocess.SubprocessError, TypeError, ValueError):
        pass
    return 0.0


def is_supported_youtube_url(video_url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(video_url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and (
        host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    )


def download_youtube_audio_window(video_url: str, start_time: float, duration_seconds: float) -> tuple[bytes, str]:
    command_prefix = find_ytdlp_command()
    initial_cookies = initial_ytdlp_cookie_browser()
    retry_cookies = resolve_ytdlp_cookie_browser()
    with tempfile.TemporaryDirectory(prefix="localtube-video-window-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        completed = run_ytdlp_audio_window(
            command_prefix,
            video_url,
            start_time,
            duration_seconds,
            temp_dir,
            initial_cookies,
        )
        if completed.returncode != 0 and retry_cookies and should_retry_ytdlp_with_cookies(completed.stderr):
            completed = run_ytdlp_audio_window(
                command_prefix,
                video_url,
                start_time,
                duration_seconds,
                temp_dir,
                retry_cookies,
            )
        if completed.returncode != 0:
            message = read_ytdlp_error(clean_translation(completed.stderr or completed.stdout)[0:500])
            raise RuntimeError(f"视频音频窗口读取失败：{message}")

        candidates = [
            path
            for path in temp_dir.glob("window.*")
            if path.is_file() and path.suffix.lower() not in (".part", ".ytdl", ".json") and path.stat().st_size > 0
        ]
        if not candidates:
            raise RuntimeError("yt-dlp 没有生成可转写的视频音频窗口。")
        audio_path = max(candidates, key=lambda path: path.stat().st_size)
        return audio_path.read_bytes(), mime_type_for_audio_path(audio_path)


def run_ytdlp_audio_window(
    command_prefix: list[str],
    video_url: str,
    start_time: float,
    duration_seconds: float,
    output_dir: Path,
    cookies_browser: str,
) -> subprocess.CompletedProcess[str]:
    command = build_ytdlp_audio_window_command(
        command_prefix,
        video_url,
        start_time,
        duration_seconds,
        output_dir,
        cookies_browser,
    )
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=VIDEO_TRANSCRIBE_DOWNLOAD_TIMEOUT,
    )


def build_ytdlp_audio_window_command(
    command_prefix: list[str],
    video_url: str,
    start_time: float,
    duration_seconds: float,
    output_dir: Path,
    cookies_browser: str = "",
) -> list[str]:
    window_end = max(start_time + 0.5, start_time + duration_seconds)
    command = list(command_prefix)
    command.extend(
        [
            "--no-playlist",
            "--no-warnings",
            "--force-overwrites",
            "--concurrent-fragments",
            "4",
            "-f",
            "bestaudio/best",
            "--download-sections",
            f"*{start_time:.3f}-{window_end:.3f}",
            "-o",
            str(output_dir / "window.%(ext)s"),
        ]
    )
    command.extend(ytdlp_impersonate_args())
    if cookies_browser:
        command.extend(["--cookies-from-browser", cookies_browser])
    command.append(video_url)
    return command


def download_youtube_full_audio(video_url: str, output_dir: Path, cancel_event: threading.Event) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    command_prefix = find_ytdlp_command()
    initial_cookies = initial_ytdlp_cookie_browser()
    retry_cookies = resolve_ytdlp_cookie_browser()
    completed = run_cancellable_command(
        build_ytdlp_full_audio_command(command_prefix, video_url, output_dir, initial_cookies),
        FULL_TRANSCRIPT_DOWNLOAD_TIMEOUT,
        cancel_event,
    )
    if completed.returncode != 0 and retry_cookies and should_retry_ytdlp_with_cookies(completed.stderr):
        completed = run_cancellable_command(
            build_ytdlp_full_audio_command(command_prefix, video_url, output_dir, retry_cookies),
            FULL_TRANSCRIPT_DOWNLOAD_TIMEOUT,
            cancel_event,
        )
    if completed.returncode != 0:
        message = read_ytdlp_error(clean_translation(completed.stderr or completed.stdout)[0:500])
        raise RuntimeError(f"完整视频音频读取失败：{message}")

    candidates = [
        path
        for path in output_dir.glob("full-audio.*")
        if path.is_file() and path.suffix.lower() not in (".part", ".ytdl", ".json") and path.stat().st_size > 0
    ]
    if not candidates:
        raise RuntimeError("yt-dlp 没有生成完整转写所需的音频。")
    return max(candidates, key=lambda path: path.stat().st_size)


def build_ytdlp_full_audio_command(
    command_prefix: list[str],
    video_url: str,
    output_dir: Path,
    cookies_browser: str = "",
) -> list[str]:
    command = list(command_prefix)
    command.extend(
        [
            "--no-playlist",
            "--no-warnings",
            "--no-progress",
            "--force-overwrites",
            "--concurrent-fragments",
            "4",
            "-f",
            "bestaudio[abr<=96]/bestaudio/best",
            "-o",
            str(output_dir / "full-audio.%(ext)s"),
        ]
    )
    command.extend(ytdlp_impersonate_args())
    if cookies_browser:
        command.extend(["--cookies-from-browser", cookies_browser])
    command.append(video_url)
    return command


def run_cancellable_command(
    command: list[str],
    timeout: float,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess[str]:
    started_at = time.monotonic()
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(command, stdout=stdout_file, stderr=stderr_file, text=True)
        while process.poll() is None:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                raise FullTranscriptCancelled("任务已取消")
            if time.monotonic() - started_at > timeout:
                process.kill()
                process.wait(timeout=3)
                raise TimeoutError(f"命令运行超过 {int(timeout)} 秒")
            time.sleep(0.05)
        stdout_file.seek(0)
        stderr_file.seek(0)
        return subprocess.CompletedProcess(command, process.returncode, stdout_file.read(), stderr_file.read())


def mime_type_for_audio_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".m4a", ".mp4"):
        return "audio/mp4"
    if suffix in (".mp3", ".mpeg"):
        return "audio/mpeg"
    if suffix == ".ogg":
        return "audio/ogg"
    if suffix == ".wav":
        return "audio/wav"
    return "audio/webm"


def build_tts_payload(payload: dict[str, Any], transport: str) -> dict[str, Any]:
    text = clean_translation(str(payload.get("text") or ""))
    language = str(payload.get("language") or payload.get("targetLanguage") or "zh-CN").strip()
    voice = str(payload.get("voice") or payload.get("voiceId") or "auto").strip()
    tts_engine = sanitize_tts_engine(payload.get("ttsEngine"))
    if not text:
        return {"ok": False, "error": "Missing TTS text"}
    try:
        rate = float(payload.get("rate") or 1)
        target_duration = max(0.0, min(float(payload.get("targetDuration") or 0), 30.0))
        max_fit_rate = max(1.0, min(float(payload.get("maxFitRate") or 3.0), 3.0))
    except (TypeError, ValueError):
        return {"ok": False, "error": "Invalid TTS rate or target duration"}

    try:
        audio = synthesize_speech_with_system(
            text,
            language,
            rate,
            voice,
            target_duration,
            max_fit_rate,
            tts_engine=tts_engine,
        )
        return {
            "ok": True,
            "engine": audio["engine"],
            "ttsEngine": audio.get("ttsEngine", tts_engine),
            "transport": transport,
            "language": language,
            "mimeType": audio["mimeType"],
            "dataUrl": audio["dataUrl"],
            "duration": audio.get("duration", 0),
            "fitRate": audio.get("fitRate", 1),
            "leadingTrimSeconds": audio.get("leadingTrimSeconds", 0),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def extract_youtube_captions(video_url: str, source_language: str, target_language: str = "") -> dict[str, Any]:
    deadline = time.monotonic() + max(1.0, CAPTION_TIMEOUT)
    command_prefix = find_ytdlp_command()
    initial_cookies_browser = initial_ytdlp_cookie_browser()
    retry_cookies_browser = resolve_ytdlp_cookie_browser()
    errors: list[str] = []
    metadata: dict[str, Any] | None = None
    fallback_results: list[dict[str, Any]] = []
    completed = run_ytdlp_metadata(
        command_prefix,
        video_url,
        cookies_browser=initial_cookies_browser,
        source_language=source_language,
        target_language=target_language,
        timeout=caption_remaining_timeout(deadline, CAPTION_METADATA_TIMEOUT),
    )
    if completed.returncode != 0 and should_retry_ytdlp_with_cookies(completed.stderr):
        completed = run_ytdlp_metadata(
            command_prefix,
            video_url,
            cookies_browser=retry_cookies_browser,
            source_language=source_language,
            target_language=target_language,
            timeout=caption_remaining_timeout(deadline, CAPTION_METADATA_TIMEOUT),
        )
    if completed.returncode != 0:
        stderr = clean_translation(completed.stderr)[0:500]
        errors.append(read_ytdlp_error(stderr or "命令退出失败"))
    else:
        metadata = parse_ytdlp_metadata(completed.stdout)
        direct_deadline = min(deadline, time.monotonic() + CAPTION_DIRECT_FETCH_BUDGET)
        resolved = read_ytdlp_caption_candidates(
            metadata,
            source_language,
            target_language,
            errors,
            label="",
            deadline=direct_deadline,
            candidate_scope="target",
        )
        if resolved:
            return resolved

    if metadata is None or select_caption_candidates(metadata, source_language, target_language):
        downloaded = download_youtube_captions(
            command_prefix,
            video_url,
            source_language,
            target_language,
            initial_cookies_browser,
            metadata=metadata,
            deadline=deadline,
        )
        if downloaded:
            if caption_result_matches_target(downloaded, target_language):
                return downloaded
            fallback_results.append(downloaded)

    if retry_cookies_browser and retry_cookies_browser != initial_cookies_browser and caption_time_left(deadline) > 1:
        retry_completed = run_ytdlp_metadata(
            command_prefix,
            video_url,
            cookies_browser=retry_cookies_browser,
            source_language=source_language,
            target_language=target_language,
            timeout=caption_remaining_timeout(deadline, CAPTION_METADATA_TIMEOUT),
        )
        if retry_completed.returncode != 0:
            stderr = clean_translation(retry_completed.stderr)[0:500]
            errors.append(read_ytdlp_error(stderr or "命令退出失败"))
        else:
            retry_metadata = parse_ytdlp_metadata(retry_completed.stdout)
            metadata = retry_metadata
            direct_deadline = min(deadline, time.monotonic() + CAPTION_DIRECT_FETCH_BUDGET)
            resolved = read_ytdlp_caption_candidates(
                retry_metadata,
                source_language,
                target_language,
                errors,
                label="带 cookies ",
                deadline=direct_deadline,
                candidate_scope="target",
            )
            if resolved:
                return resolved

        if metadata is None or select_caption_candidates(metadata, source_language, target_language):
            downloaded = download_youtube_captions(
                command_prefix,
                video_url,
                source_language,
                target_language,
                retry_cookies_browser,
                metadata=metadata,
                deadline=deadline,
            )
            if downloaded:
                if caption_result_matches_target(downloaded, target_language):
                    return downloaded
                fallback_results.append(downloaded)

    source_metadata = metadata
    if source_metadata and caption_time_left(deadline) > 0.1:
        direct_deadline = min(deadline, time.monotonic() + CAPTION_DIRECT_FETCH_BUDGET)
        resolved = read_ytdlp_caption_candidates(
            source_metadata,
            source_language,
            target_language,
            errors,
            label="源语言 ",
            deadline=direct_deadline,
            candidate_scope="source",
        )
        if resolved:
            return resolved

    if fallback_results:
        return fallback_results[-1]

    error_details = "；".join(errors)
    if metadata_video_unavailable(metadata or {}):
        raise RuntimeError(f"VIDEO_UNAVAILABLE: {error_details or 'YouTube 没有返回可播放格式或公开视频元数据'}")
    if re.search(r"video unavailable|private video|members.only|age.restricted|requested format is not available", error_details, re.I):
        raise RuntimeError(f"VIDEO_UNAVAILABLE: {error_details}")
    raise RuntimeError("yt-dlp 没有读取到可用字幕。" + (f" 细节：{error_details}" if error_details else ""))


def read_ytdlp_caption_candidates(
    metadata: dict[str, Any],
    source_language: str,
    target_language: str,
    errors: list[str],
    label: str = "",
    deadline: float | None = None,
    candidate_scope: str = "all",
) -> dict[str, Any] | None:
    candidates = select_caption_candidates(metadata, source_language, target_language)
    if candidate_scope == "target":
        candidates = [caption for caption in candidates if caption_candidate_matches_target(caption, target_language)]
    elif candidate_scope == "source":
        candidates = [caption for caption in candidates if not caption_candidate_matches_target(caption, target_language)]
    if not candidates:
        return None

    seen_urls: set[str] = set()
    attempts = 0
    candidate_urls = [
        (caption, caption_candidate_label(caption), caption_fetch_urls(caption))
        for caption in candidates
    ]
    for _caption, caption_label, urls in candidate_urls:
        if not urls:
            errors.append(f"{label}字幕 URL 缺失：{caption_label}")

    max_rounds = max((len(urls) for _caption, _caption_label, urls in candidate_urls), default=0)
    attempt_limit = CAPTION_TARGET_URL_ATTEMPT_LIMIT if candidate_scope == "target" else CAPTION_URL_ATTEMPT_LIMIT
    for round_index in range(max_rounds):
        for caption, caption_label, urls in candidate_urls:
            if round_index >= len(urls):
                continue
            url = urls[round_index]
            if attempts >= attempt_limit:
                errors.append(f"{label}字幕 URL 尝试已达到上限")
                return None
            if deadline is not None and caption_time_left(deadline) <= 0.1:
                errors.append(f"{label}字幕 URL 快速读取超时")
                return None
            if url in seen_urls:
                continue
            seen_urls.add(url)
            attempts += 1
            try:
                timeout = caption_remaining_timeout(deadline, CAPTION_HTTP_TIMEOUT) if deadline is not None else CAPTION_HTTP_TIMEOUT
                text = fetch_caption_text(url, timeout=timeout)
                cues = parse_caption_text(text)
            except Exception as exc:
                errors.append(f"{label}字幕 URL 读取失败：{caption_label} {exc}")
                continue
            if cues:
                return {
                    "engine": "yt-dlp",
                    "source": caption.get("source") or "yt-dlp",
                    "sourceLanguage": caption.get("sourceLanguage") or "auto",
                    "translatedByYouTube": truthy(caption.get("translatedByYouTube")),
                    "cues": cues,
                }
            errors.append(f"{label}字幕 URL 返回空内容：{caption_label}")

    return None


def parse_ytdlp_metadata(stdout: str) -> dict[str, Any]:
    try:
        metadata = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp 没有返回可解析的视频信息") from exc
    if not isinstance(metadata, dict):
        raise RuntimeError("yt-dlp 返回的视频信息不是对象")
    return metadata


def metadata_video_unavailable(metadata: dict[str, Any]) -> bool:
    if not isinstance(metadata, dict):
        return True
    availability = str(metadata.get("availability") or "").strip().lower()
    if availability and availability not in ("public", "unlisted"):
        return True
    formats = metadata.get("formats")
    if isinstance(formats, list) and formats:
        return False
    title = str(metadata.get("title") or "").strip().lower()
    return not availability and (not title or title.startswith("youtube video #"))


def find_ytdlp_command() -> list[str]:
    if YTDLP_COMMAND:
        return shlex.split(YTDLP_COMMAND)
    executable = shutil.which("yt-dlp") or shutil.which("youtube-dl")
    if executable:
        return [executable]
    if importlib.util.find_spec("yt_dlp"):
        return [sys.executable, "-m", "yt_dlp"]
    raise RuntimeError("未检测到 yt-dlp。请先安装：python3 -m pip install -U yt-dlp，或设置 LOCAL_DUB_YTDLP_COMMAND。")


def build_ytdlp_metadata_command(command_prefix: list[str], video_url: str) -> list[str]:
    return build_ytdlp_metadata_command_with_cookies(command_prefix, video_url, resolve_ytdlp_cookie_browser())


def build_ytdlp_metadata_command_with_cookies(
    command_prefix: list[str],
    video_url: str,
    cookies_browser: str,
    source_language: str = "",
    target_language: str = "",
) -> list[str]:
    command = list(command_prefix)
    command.extend(
        [
            "--dump-json",
            "--skip-download",
            "--ignore-no-formats-error",
            "--no-warnings",
            "--no-playlist",
            "--simulate",
            "--write-auto-subs",
        ]
    )
    if source_language or target_language:
        command.extend(["--sub-langs", subtitle_language_selector(source_language, target_language)])
    command.extend(ytdlp_impersonate_args())
    if cookies_browser:
        command.extend(["--cookies-from-browser", cookies_browser])
    command.append(video_url)
    return command


def run_ytdlp_metadata(
    command_prefix: list[str],
    video_url: str,
    cookies_browser: str,
    source_language: str = "",
    target_language: str = "",
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    command = build_ytdlp_metadata_command_with_cookies(
        command_prefix,
        video_url,
        cookies_browser,
        source_language,
        target_language,
    )
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout or CAPTION_METADATA_TIMEOUT)


def download_youtube_captions(
    command_prefix: list[str],
    video_url: str,
    source_language: str,
    target_language: str,
    cookies_browser: str,
    metadata: dict[str, Any] | None = None,
    deadline: float | None = None,
) -> dict[str, Any] | None:
    if deadline is not None and caption_time_left(deadline) <= 0.5:
        return None
    with tempfile.TemporaryDirectory() as temp_dir_name:
        output_template = str(Path(temp_dir_name) / "%(id)s.%(ext)s")
        command = list(command_prefix)
        command.extend(
            [
                "--skip-download",
                "--ignore-no-formats-error",
                "--no-warnings",
                "--no-playlist",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs",
                subtitle_language_selector(source_language, target_language, metadata),
                "--sub-format",
                "json3/vtt/srv1/srv3/ttml/best",
                "-o",
                output_template,
            ]
        )
        command.extend(ytdlp_impersonate_args())
        if cookies_browser:
            command.extend(["--cookies-from-browser", cookies_browser])
        command.append(video_url)

        timeout = caption_remaining_timeout(deadline, CAPTION_DOWNLOAD_TIMEOUT) if deadline is not None else CAPTION_DOWNLOAD_TIMEOUT
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        if completed.returncode != 0:
            return None

        candidates = []
        for path in Path(temp_dir_name).glob("*"):
            if not path.is_file() or path.suffix.lower().lstrip(".") not in ("json3", "vtt", "srv1", "srv2", "srv3", "ttml", "xml"):
                continue
            try:
                cues = parse_caption_text(path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                cues = []
            if not cues:
                continue
            language = caption_file_language(path)
            candidates.append(
                {
                    "path": path,
                    "language": language,
                    "cues": cues,
                    "score": caption_file_score(language, path.suffix.lower().lstrip("."), source_language, target_language),
                }
            )

        if not candidates:
            return None

        selected = sorted(candidates, key=lambda item: int(item["score"]), reverse=True)[0]
        translated_by_youtube = is_youtube_translated_caption_language(selected["language"], target_language)
        return {
            "engine": "yt-dlp-download",
            "source": "yt-dlp-download",
            "sourceLanguage": selected["language"] or "auto",
            "translatedByYouTube": translated_by_youtube,
            "cues": selected["cues"],
        }


def subtitle_language_selector(
    source_language: str,
    target_language: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    values = []
    for language in (target_language, youtube_translation_language(target_language), source_language, "en"):
        value = str(language or "").strip()
        prefix = normalize_language_code(value)
        for candidate in (value, prefix):
            if candidate and candidate.lower() != "auto" and candidate not in values:
                values.append(candidate)

    target_identity = normalize_caption_language_identity(target_language)
    if target_identity == "zh-hans":
        values.extend(["zh-Hans", "zh-CN", "zh", "zh-Hans.*"])
    elif target_identity == "zh-hant":
        values.extend(["zh-Hant", "zh-TW", "zh-Hant.*"])

    if isinstance(metadata, dict):
        for caption in select_caption_candidates(metadata, source_language, target_language):
            for language in (caption.get("originalLanguage"), caption.get("sourceLanguage")):
                value = str(language or "").strip()
                if value and value not in values and value.lower() != "auto":
                    values.append(value)
            if len(values) >= 8:
                break

    return ",".join(dict.fromkeys(values))


def caption_time_left(deadline: float) -> float:
    return max(0.0, deadline - time.monotonic())


def caption_remaining_timeout(deadline: float | None, limit: float) -> float:
    if deadline is None:
        return max(0.25, limit)
    remaining = caption_time_left(deadline)
    if remaining <= 0.05:
        raise TimeoutError("字幕 Engine 总读取超时")
    return max(0.05, min(limit, remaining))


def caption_file_language(path: Path) -> str:
    parts = path.name.split(".")
    if len(parts) >= 3:
        return parts[-2]
    return ""


def caption_file_score(language: str, ext: str, source_language: str, target_language: str) -> int:
    language_prefix = normalize_language_code(language)
    preferred_source = normalize_language_code(source_language)
    language_identity = normalize_caption_language_identity(language)
    preferred_target = normalize_caption_language_identity(target_language)
    score = 0
    if preferred_target and language_identity == preferred_target:
        score += 200
    elif preferred_source and language_prefix == preferred_source:
        score += 90
    elif language_prefix == "en":
        score += 30
    if ext == "json3":
        score += 20
    elif ext == "vtt":
        score += 15
    elif ext in ("srv1", "srv2", "srv3"):
        score += 10
    elif ext in ("ttml", "xml"):
        score += 5
    return score


def resolve_ytdlp_cookie_browser() -> str:
    if YTDLP_COOKIES_FROM_BROWSER.lower() == "auto":
        return "chrome"
    return YTDLP_COOKIES_FROM_BROWSER


def initial_ytdlp_cookie_browser() -> str:
    if YTDLP_COOKIES_FROM_BROWSER.lower() == "auto":
        return ""
    return YTDLP_COOKIES_FROM_BROWSER


def ytdlp_impersonate_args() -> list[str]:
    value = YTDLP_IMPERSONATE.lower()
    if value in ("", "0", "false", "none", "off", "no"):
        return []
    if value == "auto":
        if importlib.util.find_spec("curl_cffi"):
            return ["--impersonate", "chrome"]
        return []
    return ["--impersonate", YTDLP_IMPERSONATE]


def should_retry_ytdlp_with_cookies(stderr: str) -> bool:
    if not resolve_ytdlp_cookie_browser():
        return False
    message = clean_translation(stderr).lower()
    retry_markers = ("429", "sign in", "login", "bot", "confirm", "cookies", "forbidden", "403")
    return any(marker in message for marker in retry_markers)


def read_ytdlp_error(stderr: str) -> str:
    message = clean_translation(stderr)
    if "429" in message or "Too Many Requests" in message:
        return (
            "YouTube 返回 429 Too Many Requests：当前网络/IP 被临时限流。"
            "请等待几分钟后重试；如果仍然出现，请先在 Chrome 登录 YouTube，"
            "并保持本地 Engine 使用默认 cookies-from-browser=chrome。"
            "也可以设置 LOCAL_DUB_YTDLP_COOKIES_FROM_BROWSER=chrome:Default 或稍后换网络重试。"
        )
    if "cookies" in message.lower() and "browser" in message.lower():
        return (
            "yt-dlp 读取 Chrome cookies 失败。请关闭正在运行的 Chrome 后重试，"
            "或设置 LOCAL_DUB_YTDLP_COOKIES_FROM_BROWSER=none 后重启本地 Engine。"
            f" 原始错误：{message}"
        )
    return f"yt-dlp 获取字幕信息失败：{message}"


def select_caption_entry(metadata: dict[str, Any], source_language: str, target_language: str = "") -> dict[str, str] | None:
    candidates = select_caption_candidates(metadata, source_language, target_language)
    return candidates[0] if candidates else None


def select_caption_candidates(metadata: dict[str, Any], source_language: str, target_language: str = "") -> list[dict[str, str]]:
    preferred_source = normalize_language_code(source_language)
    preferred_target = normalize_caption_language_identity(target_language)
    sources = [
        ("subtitles", metadata.get("subtitles")),
        ("automatic_captions", metadata.get("automatic_captions")),
    ]
    candidates: list[dict[str, str]] = []
    translation_seed: dict[str, str] | None = None
    has_target_candidate = False

    for source, caption_map in sources:
        if not isinstance(caption_map, dict):
            continue
        for language, entries in caption_map.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                url = str(entry.get("url") or "")
                ext = str(entry.get("ext") or "").lower()
                if not url:
                    continue
                score = caption_entry_score(source, language, ext, preferred_source, preferred_target)
                candidate = {
                    "url": url,
                    "source": source,
                    "sourceLanguage": str(language),
                    "ext": ext,
                    "score": str(score),
                }
                original_language = youtube_translated_caption_source_language(str(language), target_language)
                if original_language:
                    candidate.update(
                        {
                            "originalLanguage": original_language,
                            "translatedByYouTube": "true",
                        }
                    )
                candidates.append(candidate)
                if preferred_target and normalize_caption_language_identity(str(language)) == preferred_target:
                    has_target_candidate = True
                else:
                    seed = {
                        "url": url,
                        "source": source,
                        "sourceLanguage": str(language),
                        "ext": ext,
                        "score": str(score),
                    }
                    if translation_seed is None or int(seed["score"]) > int(translation_seed["score"]):
                        translation_seed = seed

    if translation_seed and not has_target_candidate:
        candidates.extend(
            build_youtube_translated_caption_entries(
                translation_seed["url"],
                translation_seed["source"],
                translation_seed["sourceLanguage"],
                translation_seed["ext"],
                preferred_source,
                preferred_target,
                target_language,
            )
        )

    if not candidates:
        return []
    candidates.sort(key=lambda item: int(item["score"]), reverse=True)
    unique: list[dict[str, str]] = []
    seen = set()
    for candidate in candidates:
        key = caption_candidate_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
        if len(unique) >= CAPTION_CANDIDATE_LIMIT:
            break
    return unique


def caption_candidate_key(candidate: dict[str, str]) -> str:
    return "|".join(
        [
            normalize_caption_url(candidate.get("url") or ""),
            candidate.get("source") or "",
            normalize_language_code(candidate.get("sourceLanguage") or ""),
            "translated" if truthy(candidate.get("translatedByYouTube")) else "original",
        ]
    )


def caption_candidate_matches_target(candidate: dict[str, Any], target_language: str) -> bool:
    preferred_target = normalize_caption_language_identity(target_language)
    return bool(
        preferred_target
        and (
            truthy(candidate.get("translatedByYouTube"))
            or normalize_caption_language_identity(str(candidate.get("sourceLanguage") or "")) == preferred_target
        )
    )


def caption_result_matches_target(result: dict[str, Any], target_language: str) -> bool:
    return caption_candidate_matches_target(result, target_language)


def caption_entry_score(source: str, language: str, ext: str, preferred_source: str, preferred_target: str = "") -> int:
    language_prefix = normalize_language_code(language)
    language_identity = normalize_caption_language_identity(language)
    score = 0
    if source == "subtitles":
        score += 80
    else:
        score += 20
    if preferred_target and language_identity == preferred_target:
        score += 1000
    elif preferred_source and language_prefix == preferred_source:
        score += 650
    elif language_prefix == "en":
        score += 620
    elif source == "subtitles":
        score += 540
    else:
        score += 320
    if ext == "vtt":
        score += 12
    elif ext in ("json3", "srv1", "srv2", "srv3"):
        score += 8
    elif ext in ("ttml", "xml"):
        score += 4
    return score


def build_youtube_translated_caption_entry(
    url: str,
    source: str,
    language: str,
    ext: str,
    preferred_source: str,
    preferred_target: str,
    target_language: str,
) -> dict[str, str] | None:
    entries = build_youtube_translated_caption_entries(
        url,
        source,
        language,
        ext,
        preferred_source,
        preferred_target,
        target_language,
    )
    return entries[0] if entries else None


def build_youtube_translated_caption_entries(
    url: str,
    source: str,
    language: str,
    ext: str,
    preferred_source: str,
    preferred_target: str,
    target_language: str,
) -> list[dict[str, str]]:
    tlang_candidates = youtube_translation_languages(target_language)
    source_prefix = normalize_language_code(language)
    source_identity = normalize_caption_language_identity(language)
    if not url or not tlang_candidates or not preferred_target or source_identity == preferred_target:
        return []

    score = 820
    if source == "subtitles":
        score += 60
    else:
        score += 20
    if preferred_source and source_prefix == preferred_source:
        score += 30
    elif source_prefix == "en":
        score += 24
    if ext in ("json3", "vtt"):
        score += 8
    elif ext in ("srv1", "srv2", "srv3"):
        score += 5

    return [
        {
            "url": add_url_query_params(url, {"tlang": tlang}),
            "source": "youtube-translate",
            "sourceLanguage": target_language,
            "originalLanguage": language,
            "translationLanguage": tlang,
            "ext": ext,
            "translatedByYouTube": "true",
            "score": str(score - index),
        }
        for index, tlang in enumerate(tlang_candidates)
    ]


def youtube_translation_language(language: str) -> str:
    candidates = youtube_translation_languages(language)
    return candidates[0] if candidates else ""


def youtube_translation_languages(language: str) -> list[str]:
    value = str(language or "").strip()
    if not value or value.lower() == "auto":
        return []
    lower = value.lower()
    if lower in ("zh-cn", "zh-hans"):
        return ["zh", "zh-Hans", "zh-CN"]
    if lower in ("zh-tw", "zh-hant"):
        return ["zh-TW", "zh-Hant"]
    if lower == "pt-br":
        return ["pt", "pt-BR"]
    normalized = re.split(r"[-_]", lower)[0] or lower
    return list(dict.fromkeys([normalized, value]))


def add_url_query_params(url: str, params: dict[str, str]) -> str:
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    next_query = [(key, value) for key, value in query if key not in params]
    next_query.extend((key, value) for key, value in params.items() if value)
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(next_query), parts.fragment)
    )


def caption_fetch_urls(caption: dict[str, str]) -> list[str]:
    url = str(caption.get("url") or "")
    if not url:
        return []
    ext = str(caption.get("ext") or "").lower()
    formats = []
    if ext:
        formats.append(ext)
    formats.extend(["json3", "srv3", "vtt", "srv1", "ttml"])

    urls = []
    for fmt in formats:
        if fmt:
            urls.append(add_url_query_params(url, {"fmt": fmt}))
            if fmt == "srv1":
                urls.append(add_url_query_params(url, {"fmt": "srv1", "c": "ANDROID", "_ytc_": "1", "potc": "1"}))
    urls.append(url)
    return list(dict.fromkeys(urls))


def caption_candidate_label(caption: dict[str, str]) -> str:
    source = caption.get("source") or "caption"
    language = caption.get("sourceLanguage") or "unknown"
    ext = caption.get("ext") or "raw"
    translated = " YouTube翻译" if truthy(caption.get("translatedByYouTube")) else ""
    return f"{source}/{language}/{ext}{translated}"


def normalize_caption_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
        query = sorted((key, value) for key, value in query if key not in ("fmt", "c", "_ytc_", "potc"))
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), ""))
    except Exception:
        return str(url or "")


def truthy(value: Any) -> bool:
    return str(value).lower() in ("1", "true", "yes", "on") if isinstance(value, str) else bool(value)


def normalize_language_code(language: str) -> str:
    value = str(language or "").strip().lower()
    if not value or value == "auto":
        return ""
    return re.split(r"[-_]", value)[0]


def normalize_caption_language_identity(language: str) -> str:
    value = str(language or "").strip().lower().replace("_", "-")
    if not value or value == "auto":
        return ""
    if any(value == alias or value.startswith(f"{alias}-") for alias in ("zh-cn", "zh-hans", "zh-chs")):
        return "zh-hans"
    if any(
        value == alias or value.startswith(f"{alias}-")
        for alias in ("zh-tw", "zh-hant", "zh-cht", "zh-hk", "zh-mo")
    ):
        return "zh-hant"
    if value == "pt-br" or value.startswith("pt-br-"):
        return "pt-br"
    return value.split("-")[0]


def youtube_translated_caption_source_language(language: str, target_language: str) -> str:
    value = str(language or "").strip().lower().replace("_", "-")
    if not value or normalize_caption_language_identity(value) != normalize_caption_language_identity(target_language):
        return ""

    aliases = {
        str(target_language or "").strip().lower().replace("_", "-"),
        *(candidate.lower().replace("_", "-") for candidate in youtube_translation_languages(target_language)),
    }
    aliases.discard("")
    if value in aliases:
        return ""
    for alias in sorted(aliases, key=len, reverse=True):
        marker = f"{alias}-"
        if value.startswith(marker):
            return value[len(marker):]
    return ""


def is_youtube_translated_caption_language(language: str, target_language: str) -> bool:
    return bool(youtube_translated_caption_source_language(language, target_language))


def fetch_caption_text(url: str, timeout: float | None = None) -> str:
    request = urllib.request.Request(url, headers={"user-agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout or CAPTION_HTTP_TIMEOUT) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def parse_caption_text(text: str) -> list[dict[str, Any]]:
    value = text.strip()
    if not value:
        return []
    if value.startswith("{"):
        try:
            return parse_json3_captions(json.loads(value))
        except json.JSONDecodeError:
            return []
    if value.upper().startswith("WEBVTT"):
        return parse_vtt_captions(value)
    return parse_xml_captions(value)


def parse_json3_captions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for index, event in enumerate(payload.get("events") or []):
        if not isinstance(event, dict):
            continue
        segments = event.get("segs")
        if not isinstance(segments, list):
            continue
        text = clean_caption_text("".join(str(segment.get("utf8") or "") for segment in segments if isinstance(segment, dict)))
        if not text:
            continue
        start = float(event.get("tStartMs") or 0) / 1000
        duration = float(event.get("dDurationMs") or 1800) / 1000
        cues.append({"id": str(index), "start": start, "end": start + max(duration, 0.8), "text": text})
    return cues


def parse_vtt_captions(text: str) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r", ""))
    for index, block in enumerate(blocks):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        time_line_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if time_line_index < 0:
            continue
        start_text, end_text = [part.strip().split()[0] for part in lines[time_line_index].split("-->", 1)]
        start = parse_timestamp(start_text)
        end = parse_timestamp(end_text)
        body = " ".join(lines[time_line_index + 1 :])
        cue_text = clean_caption_text(re.sub(r"<[^>]+>", "", body))
        if cue_text:
            cues.append({"id": str(index), "start": start, "end": max(end, start + 0.8), "text": cue_text})
    return cues


def parse_xml_captions(text: str) -> list[dict[str, Any]]:
    cues: list[dict[str, Any]] = []
    for index, match in enumerate(re.finditer(r"<text\b([^>]*)>([\s\S]*?)</text>", text, re.IGNORECASE)):
        attrs = parse_xml_attrs(match.group(1))
        start = float(attrs.get("start") or 0)
        duration = float(attrs.get("dur") or 1.8)
        body = clean_caption_text(re.sub(r"<[^>]+>", "", match.group(2)))
        if body:
            cues.append({"id": str(index), "start": start, "end": start + max(duration, 0.8), "text": body})
    if cues:
        return cues

    for index, match in enumerate(re.finditer(r"<p\b([^>]*)>([\s\S]*?)</p>", text, re.IGNORECASE)):
        attrs = parse_xml_attrs(match.group(1))
        if attrs.get("t") not in (None, ""):
            start = float(attrs.get("t") or 0) / 1000
        else:
            start = parse_timestamp(attrs.get("begin") or "0")
        if attrs.get("d") not in (None, ""):
            duration = float(attrs.get("d") or 1800) / 1000
        elif attrs.get("dur") not in (None, ""):
            duration = parse_timestamp(attrs.get("dur") or "1.8")
        else:
            end = parse_timestamp(attrs.get("end") or "0")
            duration = end - start if end > start else 1.8
        body = clean_caption_text(re.sub(r"<[^>]+>", "", match.group(2)))
        if body:
            cues.append({"id": str(index), "start": start, "end": start + max(duration, 0.8), "text": body})
    return cues


def parse_xml_attrs(source: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r"([:\w-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", source):
        attrs[match.group(1)] = decode_html_entities(match.group(2) if match.group(2) is not None else match.group(3) or "")
    return attrs


def parse_timestamp(value: str) -> float:
    normalized = str(value or "0").strip().replace(",", ".")
    if normalized.endswith("s"):
        normalized = normalized[:-1]
    parts = normalized.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    else:
        return float(normalized or 0)
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_caption_text(text: str) -> str:
    return clean_translation(decode_html_entities(text))


def decode_html_entities(text: str) -> str:
    value = str(text or "")
    for _ in range(3):
        next_value = (
            value.replace("&quot;", '"')
            .replace("&apos;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
        )
        next_value = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), next_value)
        next_value = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), next_value)
        if next_value == value:
            return value
        value = next_value
    return value


def decode_data_url(data_url: str, fallback_mime_type: str) -> tuple[bytes, str]:
    if "," not in data_url:
        raise RuntimeError("Missing audio data URL")

    header, encoded = data_url.split(",", 1)
    mime_match = re.match(r"data:([^;]+)", header)
    mime_type = mime_match.group(1) if mime_match else fallback_mime_type
    try:
        audio_bytes = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise RuntimeError("Invalid base64 audio payload") from exc

    if not audio_bytes:
        raise RuntimeError("Recorded audio is empty")
    return audio_bytes, mime_type


def synthesize_speech_with_system(
    text: str,
    language: str,
    rate: float,
    voice_id: str = "auto",
    target_duration: float = 0,
    max_fit_rate: float = 3.0,
    tts_engine: str = "system",
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        audio = synthesize_speech_to_wav_file(
            text,
            language,
            rate,
            voice_id,
            target_duration,
            Path(temp_dir_name),
            max_fit_rate=max_fit_rate,
            tts_engine=tts_engine,
        )
        encoded = base64.b64encode(Path(audio["path"]).read_bytes()).decode("ascii")
        return {
            "engine": audio["engine"],
            "mimeType": "audio/wav",
            "dataUrl": f"data:audio/wav;base64,{encoded}",
            "duration": audio["duration"],
            "fitRate": audio["fitRate"],
            "ttsEngine": audio.get("ttsEngine", sanitize_tts_engine(tts_engine)),
            "leadingTrimSeconds": audio.get("leadingTrimSeconds", 0),
        }


def synthesize_speech_to_wav_file(
    text: str,
    language: str,
    rate: float,
    voice_id: str,
    target_duration: float,
    output_dir: Path,
    max_fit_rate: float = 3.0,
    cancel_event: threading.Event | None = None,
    tts_engine: str = "system",
) -> dict[str, Any]:
    if sanitize_tts_engine(tts_engine) == "edge":
        return synthesize_edge_speech_to_wav_file(
            text,
            language,
            rate,
            voice_id,
            target_duration,
            output_dir,
            max_fit_rate=max_fit_rate,
            cancel_event=cancel_event,
        )

    say_command = shutil.which("say")
    if not say_command:
        raise RuntimeError("本地 TTS 需要 macOS say 命令。当前系统未检测到 say。")

    voice = pick_system_voice(language, voice_id)
    words_per_minute = str(int(max(90, min(260, 180 * rate))))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "voice.wav"
    command = [
        say_command,
        "-v",
        voice,
        "-r",
        words_per_minute,
        "-o",
        str(output_path),
        "--file-format=WAVE",
        "--data-format=LEI16",
        text,
    ]
    completed = (
        run_cancellable_command(command, TTS_TIMEOUT, cancel_event)
        if cancel_event
        else subprocess.run(command, capture_output=True, text=True, timeout=TTS_TIMEOUT)
    )
    if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size <= 0:
        message = clean_translation(completed.stderr or completed.stdout or "系统 TTS 没有生成音频")
        raise RuntimeError(f"本地 TTS 生成失败：{message}")

    original_duration = validate_wav_duration(output_path)
    final_path = output_path
    fit_rate = 1.0
    if target_duration > 0.3 and original_duration > target_duration * 1.04:
        fitted = fit_wav_to_target_duration(
            output_path,
            output_dir,
            target_duration,
            max_fit_rate=max_fit_rate,
            cancel_event=cancel_event,
        )
        if fitted:
            final_path, fit_rate = fitted
    final_duration = validate_wav_duration(final_path)
    return {
        "engine": f"say:{voice}",
        "path": final_path,
        "duration": final_duration,
        "fitRate": fit_rate,
        "ttsEngine": "system",
        "leadingTrimSeconds": 0,
    }


def synthesize_edge_speech_to_wav_file(
    text: str,
    language: str,
    rate: float,
    voice_id: str,
    target_duration: float,
    output_dir: Path,
    max_fit_rate: float = 3.0,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    edge_command = find_edge_tts_command()
    if not edge_command:
        raise RuntimeError("自然在线语音尚未安装，请重新运行 Engine 一键依赖安装。")
    ffmpeg = find_ffmpeg_command()
    if not ffmpeg:
        raise RuntimeError("自然在线语音需要 ffmpeg 转换音频，请先完成 Engine 依赖安装。")

    voice = pick_edge_voice(language, voice_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    compressed_path = output_dir / "voice-edge.mp3"
    output_path = output_dir / "voice-edge.wav"
    if cancel_event:
        command = [
            *edge_command,
            "--voice",
            voice,
            f"--rate={edge_tts_rate_argument(rate)}",
            "--text",
            clean_translation(text),
            "--write-media",
            str(compressed_path),
        ]
        completed = run_cancellable_command(command, TTS_TIMEOUT, cancel_event)
        if completed.returncode != 0:
            message = clean_translation(completed.stderr or completed.stdout or "在线语音没有生成音频")
            raise RuntimeError(f"自然在线语音生成失败：{message}")
    else:
        generate_edge_tts_media(clean_translation(text), voice, edge_tts_rate_argument(rate), compressed_path)
    if not compressed_path.is_file() or compressed_path.stat().st_size <= 0:
        raise RuntimeError("自然在线语音没有生成音频。")

    convert_command = [
        ffmpeg,
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(compressed_path),
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    converted = (
        run_cancellable_command(convert_command, TTS_TIMEOUT, cancel_event)
        if cancel_event
        else subprocess.run(convert_command, capture_output=True, text=True, timeout=TTS_TIMEOUT)
    )
    if converted.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 44:
        message = clean_translation(converted.stderr or converted.stdout or "ffmpeg 没有生成 WAV")
        raise RuntimeError(f"自然在线语音转换失败：{message}")

    trimmed_path, leading_trim_seconds = trim_wav_leading_silence(output_path, output_dir)
    original_duration = validate_wav_duration(trimmed_path)
    final_path = trimmed_path
    fit_rate = 1.0
    if target_duration > 0.3 and original_duration > target_duration * 1.04:
        fitted = fit_wav_to_target_duration(
            trimmed_path,
            output_dir,
            target_duration,
            max_fit_rate=max_fit_rate,
            cancel_event=cancel_event,
        )
        if fitted:
            final_path, fit_rate = fitted
    return {
        "engine": f"edge:{voice}",
        "path": final_path,
        "duration": validate_wav_duration(final_path),
        "fitRate": fit_rate,
        "ttsEngine": "edge",
        "leadingTrimSeconds": leading_trim_seconds,
    }


def trim_wav_leading_silence(
    source_path: Path,
    output_dir: Path,
    threshold: float = 220,
    preroll_seconds: float = 0.035,
    minimum_trim_seconds: float = 0.04,
) -> tuple[Path, float]:
    """Remove transport silence while preserving a short natural speech onset."""
    try:
        with wave.open(str(source_path), "rb") as audio_file:
            channels = audio_file.getnchannels()
            sample_width = audio_file.getsampwidth()
            sample_rate = audio_file.getframerate()
            compression_type = audio_file.getcomptype()
            compression_name = audio_file.getcompname()
            frame_bytes = audio_file.readframes(audio_file.getnframes())
    except (OSError, EOFError, wave.Error):
        return source_path, 0

    if channels <= 0 or sample_width != 2 or sample_rate <= 0 or not frame_bytes:
        return source_path, 0

    samples = array("h")
    samples.frombytes(frame_bytes)
    if sys.byteorder != "little":
        samples.byteswap()
    total_frames = len(samples) // channels
    window_frames = max(1, round(sample_rate * 0.01))
    consecutive_voiced_windows = 0
    first_voiced_frame: int | None = None
    required_voiced_windows = 2

    for start_frame in range(0, total_frames, window_frames):
        end_frame = min(total_frames, start_frame + window_frames)
        start_sample = start_frame * channels
        end_sample = end_frame * channels
        window = samples[start_sample:end_sample]
        if not window:
            break
        rms = (sum(sample * sample for sample in window) / len(window)) ** 0.5
        if rms >= threshold:
            consecutive_voiced_windows += 1
            if consecutive_voiced_windows >= required_voiced_windows:
                first_voiced_frame = max(
                    0,
                    start_frame - ((required_voiced_windows - 1) * window_frames),
                )
                break
        else:
            consecutive_voiced_windows = 0

    if first_voiced_frame is None:
        return source_path, 0
    trim_frame = max(0, first_voiced_frame - round(sample_rate * preroll_seconds))
    trimmed_seconds = trim_frame / sample_rate
    if trimmed_seconds < minimum_trim_seconds:
        return source_path, 0

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "voice-edge-trimmed.wav"
    bytes_per_frame = channels * sample_width
    with wave.open(str(output_path), "wb") as output_file:
        output_file.setnchannels(channels)
        output_file.setsampwidth(sample_width)
        output_file.setframerate(sample_rate)
        output_file.setcomptype(compression_type, compression_name)
        output_file.writeframes(frame_bytes[trim_frame * bytes_per_frame :])
    return output_path, trimmed_seconds


def validate_wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio_file:
            frame_count = audio_file.getnframes()
            sample_rate = audio_file.getframerate()
    except (OSError, EOFError, wave.Error) as exc:
        raise RuntimeError(f"本地 TTS 生成了无效音频：{exc}") from exc
    if frame_count <= 0 or sample_rate <= 0:
        raise RuntimeError("本地 TTS 没有生成可播放的声音，已改用浏览器朗读。")
    return frame_count / sample_rate


def fit_wav_to_target_duration(
    source_path: Path,
    output_dir: Path,
    target_duration: float,
    max_fit_rate: float = 3.0,
    cancel_event: threading.Event | None = None,
) -> tuple[Path, float] | None:
    ffmpeg = find_ffmpeg_command()
    if not ffmpeg or target_duration <= 0:
        return None
    original_duration = validate_wav_duration(source_path)
    requested_rate = original_duration / target_duration
    fit_rate = max(1.0, min(requested_rate, max(1.0, float(max_fit_rate))))
    if fit_rate <= 1.02:
        return None

    output_path = output_dir / "voice-fitted.wav"
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(source_path),
        "-filter:a",
        build_atempo_filter(fit_rate),
        "-c:a",
        "pcm_s16le",
        str(output_path),
    ]
    completed = (
        run_cancellable_command(command, TTS_TIMEOUT, cancel_event)
        if cancel_event
        else subprocess.run(command, capture_output=True, text=True, timeout=TTS_TIMEOUT)
    )
    if completed.returncode != 0 or not output_path.is_file() or output_path.stat().st_size <= 44:
        return None
    validate_wav_duration(output_path)
    return output_path, fit_rate


def build_atempo_filter(rate: float) -> str:
    remaining = max(0.5, float(rate))
    factors = []
    while remaining > 2.0:
        factors.append(2.0)
        remaining /= 2.0
    factors.append(remaining)
    return ",".join(f"atempo={factor:.6f}" for factor in factors)


def sanitize_tts_engine(value: Any) -> str:
    return "edge" if str(value or "").strip().lower() in ("edge", "edge-tts", "natural-online") else "system"


def find_edge_tts_command() -> list[str] | None:
    try:
        if importlib.util.find_spec("edge_tts") is not None:
            return [sys.executable or "python3", "-m", "edge_tts"]
    except (ImportError, ValueError):
        pass
    command = shutil.which("edge-tts")
    return [command] if command else None


def edge_tts_available() -> bool:
    return bool(find_edge_tts_command())


def generate_edge_tts_media(text: str, voice: str, rate: str, output_path: Path) -> None:
    try:
        import edge_tts  # type: ignore
    except ImportError as exc:
        raise RuntimeError("自然在线语音尚未安装，请重新运行 Engine 一键依赖安装。") from exc

    async def save_media() -> None:
        communicator = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        await asyncio.wait_for(communicator.save(str(output_path)), timeout=TTS_TIMEOUT)

    try:
        asyncio.run(save_media())
    except Exception as exc:
        raise RuntimeError(f"自然在线语音连接失败：{exc}") from exc


def edge_tts_rate_argument(rate: float) -> str:
    multiplier = max(0.6, min(float(rate), 1.4))
    return f"{round((multiplier - 1.0) * 100):+d}%"


def pick_edge_voice(language: str, voice_id: str = "auto") -> str:
    selected = str(voice_id or "").strip()
    available_ids = {str(voice["id"]) for voice in EDGE_TTS_VOICES}
    if selected and selected.lower() != "auto" and selected in available_ids:
        return selected

    normalized = str(language or "").strip().lower().replace("_", "-")
    default_key = normalized if normalized in ("zh-cn", "zh-tw") else normalize_language_code(normalized)
    preferred = EDGE_TTS_DEFAULT_VOICES.get(default_key)
    if preferred:
        return preferred
    matching = next(
        (
            str(voice["id"])
            for voice in EDGE_TTS_VOICES
            if normalize_language_code(str(voice.get("language") or "")) == normalize_language_code(normalized)
        ),
        "",
    )
    return matching or "en-US-JennyNeural"


def pick_system_voice(language: str, voice_id: str = "auto") -> str:
    selected = str(voice_id or "").strip()
    prefix = normalize_language_code(language)
    voices = {
        "zh": "Tingting",
        "en": "Samantha",
        "ja": "Kyoko",
        "ko": "Yuna",
        "es": "Mónica",
        "fr": "Thomas",
        "de": "Anna",
        "it": "Alice",
        "pt": "Luciana",
        "ru": "Milena",
        "ar": "Majed",
    }
    preferred = "Meijia" if str(language or "").lower() in ("zh-tw", "zh-hant") else voices.get(prefix, "Samantha")
    available = available_system_voices()
    if not available:
        return selected if selected and selected.lower() != "auto" else preferred

    available_names = {voice["id"] for voice in available}
    if selected and selected.lower() != "auto" and selected in available_names:
        return selected
    if preferred in available_names:
        return preferred
    matching = next(
        (voice["id"] for voice in available if normalize_language_code(voice.get("language") or "") == prefix),
        "",
    )
    return matching or str(available[0]["id"])


def build_voices_payload(transport: str) -> dict[str, Any]:
    system_voices = [
        {**voice, "provider": "system", "localService": True}
        for voice in available_system_voices()
    ]
    edge_ready = edge_tts_available()
    edge_voices = [
        {**voice, "provider": "edge", "localService": False, "available": edge_ready}
        for voice in EDGE_TTS_VOICES
    ]
    return {
        "ok": True,
        "transport": transport,
        "engine": "say" if shutil.which("say") else "unavailable",
        "edgeTts": edge_ready,
        "voices": [*system_voices, *edge_voices],
    }


def parse_system_voice_output(output: str) -> list[dict[str, Any]]:
    voices: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(r"^\s*(.+?)\s{2,}([a-z]{2,3}(?:_[A-Za-z0-9]+)?)\s+#\s*(.*)$")
    for line in str(output or "").splitlines():
        match = pattern.match(line.rstrip())
        if not match:
            continue
        name = match.group(1).strip()
        locale = match.group(2).replace("_", "-")
        if not name or name in seen:
            continue
        seen.add(name)
        voices.append(
            {
                "id": name,
                "name": name,
                "language": locale,
                "localService": True,
            }
        )
    return voices


@functools.lru_cache(maxsize=1)
def available_system_voices() -> list[dict[str, Any]]:
    say_command = shutil.which("say")
    if not say_command:
        return []
    try:
        completed = subprocess.run([say_command, "-v", "?"], capture_output=True, text=True, timeout=4)
    except Exception:
        return []
    if completed.returncode != 0:
        return []
    return parse_system_voice_output(completed.stdout)


@functools.lru_cache(maxsize=1)
def available_system_voice_names() -> set[str]:
    return {voice["id"] for voice in available_system_voices()}


def transcribe_audio_with_whisper(audio_bytes: bytes, mime_type: str, model: str, language: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="localtube-whisper-") as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        audio_path = temp_dir / f"input{audio_suffix(mime_type)}"
        audio_path.write_bytes(audio_bytes)
        return transcribe_audio_path_with_whisper(audio_path, temp_dir, model, language)


def transcribe_audio_path_with_whisper(
    audio_path: Path,
    output_dir: Path,
    model: str,
    language: str,
    timeout: float = WHISPER_TIMEOUT,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if not WHISPER_COMMAND and find_whisper_cpp_command() and WHISPER_CPP_MODEL.is_file():
        whisper_audio_path = convert_audio_for_whisper_cpp(audio_path, output_dir)
        command = build_whisper_cpp_command(whisper_audio_path, output_dir, language)
    else:
        command = build_whisper_command(audio_path, output_dir, model, language)
    if cancel_event:
        completed = run_cancellable_command(command, timeout, cancel_event)
    else:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if completed.returncode != 0:
        stderr = clean_translation(completed.stderr)[0:400]
        raise RuntimeError(f"本地 Whisper 转写失败：{stderr or '命令退出失败'}")
    return read_whisper_json(output_dir, completed.stdout)


def find_whisper_cpp_command() -> str:
    if WHISPER_CPP_COMMAND:
        parts = shlex.split(WHISPER_CPP_COMMAND)
        return parts[0] if parts else ""
    return shutil.which("whisper-cli") or shutil.which("whisper-cpp") or ""


def find_ffmpeg_command() -> str:
    if FFMPEG_COMMAND:
        parts = shlex.split(FFMPEG_COMMAND)
        return parts[0] if parts else ""
    return shutil.which("ffmpeg") or ""


def find_ffprobe_command() -> str:
    if FFPROBE_COMMAND:
        parts = shlex.split(FFPROBE_COMMAND)
        return parts[0] if parts else ""
    ffmpeg = find_ffmpeg_command()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name("ffprobe")
        if sibling.is_file() and os.access(sibling, os.X_OK):
            return str(sibling)
    return shutil.which("ffprobe") or ""


def convert_audio_for_whisper_cpp(audio_path: Path, output_dir: Path) -> Path:
    ffmpeg = find_ffmpeg_command()
    if not ffmpeg:
        raise RuntimeError("本地 whisper.cpp 需要 ffmpeg。请在安装说明中点击“一键安装本地转写”。")
    wav_path = output_dir / "whisper-input.wav"
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(audio_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_s16le",
        str(wav_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if completed.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size <= 44:
        message = clean_translation(completed.stderr or completed.stdout or "音频转换失败")
        raise RuntimeError(f"本地转写音频转换失败：{message}")
    return wav_path


def build_whisper_cpp_command(audio_path: Path, output_dir: Path, language: str) -> list[str]:
    executable = find_whisper_cpp_command()
    if not executable or not WHISPER_CPP_MODEL.is_file():
        raise RuntimeError("未检测到 whisper.cpp 或本地模型。请在安装说明中点击“一键安装本地转写”。")
    output_base = output_dir / "whisper-result"
    return [
        executable,
        "-m",
        str(WHISPER_CPP_MODEL),
        "-f",
        str(audio_path),
        "-oj",
        "-of",
        str(output_base),
        "-l",
        (language.split("-")[0] if language and language != "auto" else "auto"),
        "-np",
    ]


def build_whisper_command(audio_path: Path, output_dir: Path, model: str, language: str) -> list[str]:
    if WHISPER_COMMAND:
        return [
            part.format(audio=str(audio_path), out_dir=str(output_dir), model=model, language=language or "")
            for part in shlex.split(WHISPER_COMMAND)
        ]

    whisper_executable = shutil.which("whisper")
    if not whisper_executable:
        raise RuntimeError(
            "未检测到本地 Whisper CLI。请安装 openai-whisper 后确认 `whisper` 命令可用，"
            "或设置 LOCAL_DUB_WHISPER_COMMAND。"
        )

    command = [
        whisper_executable,
        str(audio_path),
        "--model",
        model,
        "--task",
        "transcribe",
        "--output_format",
        "json",
        "--output_dir",
        str(output_dir),
    ]
    if language and language != "auto":
        command.extend(["--language", language.split("-")[0]])
    return command


def read_whisper_json(output_dir: Path, stdout: str) -> dict[str, Any]:
    for path in output_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return normalize_whisper_json(payload)
        except json.JSONDecodeError:
            continue

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("本地 Whisper 没有生成 JSON 输出") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("本地 Whisper JSON 输出不是对象")
    return normalize_whisper_json(payload)


def normalize_whisper_json(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("segments"), list):
        return payload

    transcription = payload.get("transcription")
    if not isinstance(transcription, list):
        return payload

    segments = []
    for item in transcription:
        if not isinstance(item, dict):
            continue
        offsets = item.get("offsets") if isinstance(item.get("offsets"), dict) else {}
        timestamps = item.get("timestamps") if isinstance(item.get("timestamps"), dict) else {}
        start = whisper_cpp_offset_seconds(offsets.get("from"), timestamps.get("from"))
        end = whisper_cpp_offset_seconds(offsets.get("to"), timestamps.get("to"))
        text = clean_translation(item.get("text") or "")
        if text:
            segments.append({"start": start, "end": max(end, start + 0.3), "text": text})

    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return {
        "language": result.get("language") or payload.get("language") or "",
        "text": " ".join(segment["text"] for segment in segments),
        "segments": segments,
    }


def whisper_cpp_offset_seconds(offset: Any, timestamp: Any) -> float:
    try:
        return max(0.0, float(offset) / 1000.0)
    except (TypeError, ValueError):
        return max(0.0, parse_timestamp(str(timestamp or "0")))


def whisper_payload_to_cues(payload: dict[str, Any], start_time: float, duration_seconds: float) -> list[dict[str, Any]]:
    segments = payload.get("segments")
    cues: list[dict[str, Any]] = []
    if isinstance(segments, list):
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            text = clean_translation(segment.get("text") or "")
            if not text:
                continue
            start = start_time + float(segment.get("start") or 0)
            end = start_time + float(segment.get("end") or segment.get("start") or 0)
            cues.append({"id": f"asr-{index}", "start": start, "end": max(end, start + 0.8), "text": text})
    if cues:
        return cues

    return estimate_cues_from_transcript(str(payload.get("text") or ""), start_time, duration_seconds)


def estimate_cues_from_transcript(text: str, start_time: float, duration_seconds: float) -> list[dict[str, Any]]:
    parts = [clean_translation(part) for part in re.split(r"(?<=[.!?。！？])\s+", clean_translation(text))]
    parts = [part for part in parts if part]
    if not parts:
        return []

    cue_duration = max(2.0, duration_seconds / len(parts))
    return [
        {
            "id": f"asr-{index}",
            "start": start_time + index * cue_duration,
            "end": start_time + (index + 1) * cue_duration,
            "text": part,
        }
        for index, part in enumerate(parts)
    ]


def audio_suffix(mime_type: str) -> str:
    if "mp4" in mime_type or "m4a" in mime_type:
        return ".m4a"
    if "mpeg" in mime_type or "mp3" in mime_type:
        return ".mp3"
    if "wav" in mime_type:
        return ".wav"
    if "ogg" in mime_type:
        return ".ogg"
    return ".webm"


def translate_cues_with_ollama(
    cues: list[dict[str, Any]], target_language: str, source_language: str
) -> list[str]:
    all_translations: list[str] = []
    for batch in make_batches(cues):
        all_translations.extend(translate_ollama_batch_with_recovery(batch, target_language, source_language))
    return all_translations


def translate_ollama_batch_with_recovery(
    cues: list[dict[str, Any]], target_language: str, source_language: str
) -> list[str]:
    prompt = build_translation_prompt(cues, target_language, source_language)
    response_text = call_ollama(prompt)
    translations = [clean_translation(item) for item in parse_translation_array(response_text)]
    if len(translations) == len(cues) and all(translations):
        return translations
    if len(cues) <= 1:
        raise RuntimeError(f"model returned {len(translations)} valid translations for {len(cues)} cues")

    midpoint = (len(cues) + 1) // 2
    return [
        *translate_ollama_batch_with_recovery(cues[:midpoint], target_language, source_language),
        *translate_ollama_batch_with_recovery(cues[midpoint:], target_language, source_language),
    ]


def make_batches(cues: list[dict[str, Any]], max_items: int = 24, max_chars: int = 3200):
    batch: list[dict[str, Any]] = []
    char_count = 0

    for cue in cues:
        next_chars = len(cue["text"])
        if batch and (len(batch) >= max_items or char_count + next_chars > max_chars):
            yield batch
            batch = []
            char_count = 0

        batch.append(cue)
        char_count += next_chars

    if batch:
        yield batch


def build_translation_prompt(
    cues: list[dict[str, Any]], target_language: str, source_language: str
) -> str:
    texts = [cue["text"] for cue in cues]
    return (
        "You are a professional audiovisual subtitle translator.\n"
        f"Translate each caption from {source_language} into {target_language}.\n"
        "Keep the same number of items and preserve timing-friendly short phrasing.\n"
        "Do not add explanations, markdown, numbering, timestamps, or extra fields.\n"
        "Return only a valid JSON array of translated strings.\n\n"
        f"Captions JSON:\n{json.dumps(texts, ensure_ascii=False)}"
    )


def call_ollama(prompt: str) -> str:
    payload = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.15},
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))

    text = data.get("response")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("empty response from Ollama")
    return text.strip()


def parse_translation_array(text: str) -> list[str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            raise
        parsed = json.loads(match.group(0))

    if not isinstance(parsed, list):
        raise RuntimeError("translation response is not a JSON array")

    return [str(item).strip() for item in parsed]


def clean_translation(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def check_ollama() -> bool:
    try:
        request = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(
                {
                    "model": OLLAMA_MODEL,
                    "prompt": "Reply with OK.",
                    "stream": False,
                    "options": {"num_predict": 4},
                }
            ).encode("utf-8"),
            headers={"content-type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_HEALTH_TIMEOUT) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


def check_whisper() -> bool:
    if WHISPER_COMMAND:
        return True
    if shutil.which("whisper") is not None:
        return True
    return bool(find_whisper_cpp_command() and find_ffmpeg_command() and WHISPER_CPP_MODEL.is_file())


def check_ytdlp() -> bool:
    if YTDLP_COMMAND:
        return True
    return shutil.which("yt-dlp") is not None or shutil.which("youtube-dl") is not None or importlib.util.find_spec("yt_dlp") is not None


def check_tts() -> bool:
    return shutil.which("say") is not None


def restart_current_process() -> None:
    python = sys.executable or "python3"
    args = [python, *sys.argv]
    os.execv(python, args)


def main() -> None:
    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer((HOST, PORT), LocalDubHandler)
    print(f"LocalTube Dub server listening on http://{HOST}:{PORT}")
    print(f"Ollama endpoint: {OLLAMA_URL}")
    print(f"Ollama model: {OLLAMA_MODEL}")
    print(f"Whisper model: {WHISPER_MODEL}")
    server.serve_forever()


if __name__ == "__main__":
    main()
