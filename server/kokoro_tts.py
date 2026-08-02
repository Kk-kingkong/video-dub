"""Pinned Kokoro model installation with local-only state management."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import math
import json
import os
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import wave
from array import array
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Set, Union


KOKORO_MODEL_MANIFEST = MappingProxyType(
    {
        "id": "kokoro-int8-multi-lang-v1_1",
        "version": "1.1-int8",
        "url": "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/kokoro-int8-multi-lang-v1_1.tar.bz2",
        "sha256": "a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6",
        "archiveBytes": 147031220,
        "installedBytes": 215321602,
        "archiveRoot": "kokoro-int8-multi-lang-v1_1",
        "allowedRootFiles": (
            "LICENSE",
            "README.md",
            "date-zh.fst",
            "lexicon-gb-en.txt",
            "lexicon-us-en.txt",
            "lexicon-zh.txt",
            "model.int8.onnx",
            "number-zh.fst",
            "phone-zh.fst",
            "tokens.txt",
            "voices.bin",
        ),
        "allowedPrefixes": ("dict", "espeak-ng-data"),
        "requiredFiles": (
            "model.int8.onnx",
            "voices.bin",
            "tokens.txt",
            "lexicon-zh.txt",
            "lexicon-gb-en.txt",
            "lexicon-us-en.txt",
            "date-zh.fst",
            "number-zh.fst",
            "phone-zh.fst",
        ),
        "fileCount": 377,
    }
)


class KokoroModelError(RuntimeError):
    """A downloaded Kokoro model failed a local validation boundary."""


class KokoroModelCancelled(KokoroModelError):
    """A model installation was cancelled before activation."""


class KokoroRuntimeError(RuntimeError):
    """Kokoro inference could not safely produce local speech."""


class KokoroRuntimeCancelled(KokoroRuntimeError):
    """A queued Kokoro synthesis request was cancelled before inference."""


Fetcher = Callable[[str], Union[Path, bytes, bytearray]]


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or "\\" in value or path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise KokoroModelError("unsafe archive path")
    if path.parts and path.parts[0].endswith(":"):
        raise KokoroModelError("unsafe archive path")
    return path


def _normalized_required_files(required_files: Set[str]) -> Set[PurePosixPath]:
    return {_safe_relative_path(str(name)) for name in required_files}


def extract_verified_archive(
    archive: Path,
    destination: Path,
    required_files: Set[str],
    *,
    archive_root: Optional[str] = None,
    allowed_root_files: Optional[Set[str]] = None,
    allowed_prefixes: Optional[Set[str]] = None,
    expected_file_count: Optional[int] = None,
    expected_installed_bytes: Optional[int] = None,
) -> int:
    """Extract a fixed archive layout without following archive links."""

    expected_files = _normalized_required_files(required_files)
    normalized_root = _safe_relative_path(archive_root) if archive_root else None
    if normalized_root is not None and len(normalized_root.parts) != 1:
        raise KokoroModelError("unsafe archive root")
    allowed_files = _normalized_required_files(allowed_root_files or required_files)
    allowed_direct_files = {PurePosixPath(path.name) for path in allowed_files if len(path.parts) == 1}
    allowed_nested_prefixes = {str(prefix).rstrip("/") for prefix in (allowed_prefixes or set())}
    if any(not _safe_relative_path(prefix) or "/" in prefix for prefix in allowed_nested_prefixes):
        raise KokoroModelError("unsafe archive prefix")
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=False)
    destination_root = destination.resolve()

    try:
        with tarfile.open(archive, "r:*") as input_archive:
            members = input_archive.getmembers()
            regular_members = [member for member in members if member.isfile()]
            parsed_paths = [_safe_relative_path(member.name) for member in regular_members]
            common_prefix: Optional[str] = None
            if normalized_root is None and parsed_paths and all(len(path.parts) > 1 for path in parsed_paths):
                first_parts = {path.parts[0] for path in parsed_paths}
                if len(first_parts) == 1:
                    common_prefix = next(iter(first_parts))

            extracted: Set[PurePosixPath] = set()
            total_bytes = 0
            for member in members:
                member_path = _safe_relative_path(member.name)
                relative_path = member_path
                if normalized_root is not None:
                    if member_path.parts[0] != normalized_root.name:
                        raise KokoroModelError("unexpected archive root")
                    relative_path = PurePosixPath(*member_path.parts[1:])
                elif common_prefix is not None:
                    relative_path = PurePosixPath(*member_path.parts[1:])

                if member.isdir():
                    if normalized_root is not None and relative_path.parts:
                        top_level = relative_path.parts[0]
                        if len(relative_path.parts) == 1 and top_level not in allowed_nested_prefixes:
                            raise KokoroModelError("unexpected archive directory")
                        if len(relative_path.parts) > 1 and top_level not in allowed_nested_prefixes:
                            raise KokoroModelError("unexpected archive directory")
                    continue
                if not member.isfile():
                    raise KokoroModelError("unsafe archive member")
                if not relative_path.parts:
                    raise KokoroModelError("unexpected archive file")

                if normalized_root is None and relative_path not in expected_files:
                    raise KokoroModelError("unexpected archive file")
                if normalized_root is not None and len(relative_path.parts) == 1 and relative_path not in allowed_direct_files:
                    raise KokoroModelError("unexpected archive file")
                if normalized_root is not None and len(relative_path.parts) > 1 and relative_path.parts[0] not in allowed_nested_prefixes:
                    raise KokoroModelError("unexpected archive prefix")
                if relative_path in extracted:
                    raise KokoroModelError("duplicate archive file")

                output_path = destination.joinpath(*relative_path.parts)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                resolved_output = output_path.resolve()
                try:
                    resolved_output.relative_to(destination_root)
                except ValueError as error:
                    raise KokoroModelError("unsafe archive path") from error

                input_file = input_archive.extractfile(member)
                if input_file is None:
                    raise KokoroModelError("invalid archive member")
                with input_file, resolved_output.open("xb") as output_file:
                    shutil.copyfileobj(input_file, output_file)
                extracted.add(relative_path)
                total_bytes += member.size

    except (tarfile.TarError, OSError) as error:
        shutil.rmtree(destination, ignore_errors=True)
        if isinstance(error, KokoroModelError):
            raise
        raise KokoroModelError("invalid model archive") from error
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise

    if extracted != expected_files:
        if not expected_files.issubset(extracted):
            shutil.rmtree(destination, ignore_errors=True)
            raise KokoroModelError("model archive is missing required files")
    if expected_file_count is not None and len(extracted) != expected_file_count:
        shutil.rmtree(destination, ignore_errors=True)
        raise KokoroModelError("unexpected model file count")
    if expected_installed_bytes is not None and total_bytes != expected_installed_bytes:
        shutil.rmtree(destination, ignore_errors=True)
        raise KokoroModelError("unexpected installed model size")
    return total_bytes


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise KokoroModelError("model download redirect must use HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class KokoroModelManager:
    """Own the fixed model's staging, validation, and atomic activation.

    Production callers use this class with its fixed manifest and ``install``
    method only. ``_for_tests`` and ``_install_for_tests`` are deterministic
    test seams; Engine protocol handlers must never expose either input.
    """

    def __init__(self, root: Path, *, _manifest_for_tests: Optional[Mapping[str, Any]] = None) -> None:
        self.root = Path(root).expanduser().resolve()
        source_manifest = KOKORO_MODEL_MANIFEST if _manifest_for_tests is None else _manifest_for_tests
        self.manifest = MappingProxyType(dict(source_manifest))
        self._required_files = _normalized_required_files(set(self.manifest["requiredFiles"]))
        self._archive_root = self.manifest.get("archiveRoot")
        self._allowed_root_files = set(self.manifest.get("allowedRootFiles", self.manifest["requiredFiles"]))
        self._allowed_prefixes = set(self.manifest.get("allowedPrefixes", ()))
        self._file_count = self.manifest.get("fileCount")
        self.active_path = self.root / "active"
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._state = "not-installed"
        self._error = ""
        self._downloaded_bytes = 0

    @classmethod
    def _for_tests(cls, root: Path, manifest: Mapping[str, Any]) -> "KokoroModelManager":
        """Create a manager with a synthetic manifest for deterministic tests."""

        return cls(root, _manifest_for_tests=manifest)

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._state
            if state not in {"installing", "failed"}:
                state = "ready" if self._active_model_is_valid() else "not-installed"
            installed_bytes = self._installed_bytes() if state == "ready" else 0
            total_bytes = int(self.manifest["archiveBytes"])
            return {
                "state": state,
                "version": self.manifest["version"],
                "downloadedBytes": self._downloaded_bytes,
                "totalBytes": total_bytes,
                "progress": 1.0 if state == "ready" else min(1.0, self._downloaded_bytes / total_bytes),
                "installedBytes": installed_bytes,
                "error": self._error,
            }

    def install_request(self, request: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
        request = request or {}
        forbidden = {"url", "path", "checksum", "package", "command"}
        if any(name in request for name in forbidden) or request:
            return {"ok": False, "code": "INVALID_MODEL_REQUEST"}
        return self.install()

    def install(self) -> dict[str, Any]:
        """Install only the fixed production archive through its fixed HTTPS source."""

        return self._install(None)

    def _install_for_tests(self, fetcher: Fetcher) -> dict[str, Any]:
        """Install a synthetic archive for deterministic tests only."""

        return self._install(fetcher)

    def _install(self, fetcher: Optional[Fetcher]) -> dict[str, Any]:
        with self._lock:
            if self._state == "installing":
                return self.status()
            self._state = "installing"
            self._error = ""
            self._downloaded_bytes = 0
            self._cancel_event.clear()

        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".kokoro-stage-", dir=str(self.root)) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                archive = temp_dir / "model.tar.bz2"
                self._obtain_archive(archive, fetcher)
                self._raise_if_cancelled()
                self._verify_archive(archive)
                extracted = temp_dir / "extracted"
                installed_bytes = extract_verified_archive(
                    archive,
                    extracted,
                    {str(path) for path in self._required_files},
                    archive_root=self._archive_root,
                    allowed_root_files=self._allowed_root_files,
                    allowed_prefixes=self._allowed_prefixes,
                    expected_file_count=self._file_count,
                    expected_installed_bytes=int(self.manifest["installedBytes"]),
                )
                self._raise_if_cancelled()
                self._write_activation_metadata(extracted, installed_bytes)
                with self._lock:
                    self._raise_if_cancelled()
                    self._activate(extracted)
        except KokoroModelCancelled:
            with self._lock:
                self._state = "not-installed"
                self._error = ""
            return self.status()
        except (KokoroModelError, OSError, ValueError) as error:
            with self._lock:
                self._state = "failed"
                self._error = str(error)
            return self.status()

        with self._lock:
            self._state = "ready"
            self._error = ""
        return self.status()

    def cancel(self) -> dict[str, Any]:
        self._cancel_event.set()
        return self.status()

    def uninstall(self) -> dict[str, Any]:
        with self._lock:
            self._cancel_event.set()
            shutil.rmtree(self.active_path, ignore_errors=True)
            self._state = "not-installed"
            self._error = ""
            self._downloaded_bytes = 0
        return self.status()

    def _obtain_archive(self, destination: Path, fetcher: Optional[Fetcher]) -> None:
        if fetcher is None:
            self._download_fixed_archive(destination)
            return

        source = fetcher(str(self.manifest["url"]))
        self._raise_if_cancelled()
        if isinstance(source, (bytes, bytearray)):
            destination.write_bytes(source)
        else:
            source_path = Path(source).expanduser().resolve()
            shutil.copyfile(source_path, destination)
        self._downloaded_bytes = destination.stat().st_size

    def _download_fixed_archive(self, destination: Path) -> None:
        url = str(self.manifest["url"])
        if urllib.parse.urlsplit(url).scheme.lower() != "https":
            raise KokoroModelError("model download URL must use HTTPS")
        opener = urllib.request.build_opener(_HttpsOnlyRedirectHandler())
        with opener.open(url, timeout=60) as response, destination.open("xb") as output:
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) != int(self.manifest["archiveBytes"]):
                raise KokoroModelError("unexpected model archive size")
            while True:
                self._raise_if_cancelled()
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                self._downloaded_bytes += len(chunk)
                if self._downloaded_bytes > int(self.manifest["archiveBytes"]):
                    raise KokoroModelError("unexpected model archive size")

    def _verify_archive(self, archive: Path) -> None:
        expected_bytes = int(self.manifest["archiveBytes"])
        actual_bytes = archive.stat().st_size
        self._downloaded_bytes = actual_bytes
        if actual_bytes != expected_bytes:
            raise KokoroModelError("unexpected model archive size")
        digest = hashlib.sha256()
        with archive.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
                self._raise_if_cancelled()
                digest.update(chunk)
        if digest.hexdigest() != str(self.manifest["sha256"]):
            raise KokoroModelError("model archive checksum mismatch")

    def _write_activation_metadata(self, extracted: Path, installed_bytes: int) -> None:
        metadata = {
            "id": self.manifest["id"],
            "version": self.manifest["version"],
            "installedBytes": installed_bytes,
            "fileCount": self._file_count,
        }
        (extracted / ".kokoro-model.json").write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")

    def _activate(self, extracted: Path) -> None:
        replacement = self.root / ".kokoro-active-next"
        backup = self.root / ".kokoro-active-previous"
        shutil.rmtree(replacement, ignore_errors=True)
        if backup.exists():
            if self.active_path.exists():
                shutil.rmtree(backup)
            else:
                os.replace(backup, self.active_path)
        os.replace(extracted, replacement)
        moved_active_to_backup = False
        try:
            if self.active_path.exists():
                os.replace(self.active_path, backup)
                moved_active_to_backup = True
            os.replace(replacement, self.active_path)
        except OSError:
            if moved_active_to_backup and backup.exists() and not self.active_path.exists():
                try:
                    os.replace(backup, self.active_path)
                except OSError:
                    pass
            raise
        else:
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            shutil.rmtree(replacement, ignore_errors=True)

    def _active_model_is_valid(self) -> bool:
        try:
            metadata_path = self.active_path / ".kokoro-model.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("id") != self.manifest["id"] or metadata.get("version") != self.manifest["version"]:
                return False
            if metadata.get("installedBytes") != int(self.manifest["installedBytes"]):
                return False
            if self._file_count is not None and metadata.get("fileCount") != self._file_count:
                return False
            active_root = self.active_path.resolve()
            for relative_path in self._required_files:
                candidate = self.active_path.joinpath(*relative_path.parts)
                if candidate.is_symlink() or not candidate.is_file():
                    return False
                candidate.resolve().relative_to(active_root)
            file_count, installed_bytes = self._active_payload_stats()
            return (
                (self._file_count is None or file_count == self._file_count)
                and installed_bytes == int(self.manifest["installedBytes"])
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def _installed_bytes(self) -> int:
        return self._active_payload_stats()[1]

    def _active_payload_stats(self) -> tuple[int, int]:
        file_count = 0
        installed_bytes = 0
        for candidate in self.active_path.rglob("*"):
            if candidate.name == ".kokoro-model.json":
                continue
            if candidate.is_symlink() or not candidate.is_file():
                continue
            file_count += 1
            installed_bytes += candidate.stat().st_size
        return file_count, installed_bytes

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise KokoroModelCancelled("model installation cancelled")


# sherpa-onnx v1.13.4 documents these exact voice IDs and speaker IDs for
# kokoro-int8-multi-lang-v1_1. Keep the mapping data here rather than relying
# on an inference library's private voice table so Engine clients have stable IDs.
KOKORO_SHERPA_ONNX_VERSION = "1.13.4"
KOKORO_SAMPLE_RATE = 24000
KOKORO_IDLE_UNLOAD_SECONDS = 5 * 60
KOKORO_NUM_THREADS = 2
KOKORO_SYNTHESIS_LOCK = threading.Lock()
KOKORO_SPEAKER_NAMES = (
    "af_maple",
    "af_sol",
    "bf_vale",
    "zf_001",
    "zf_002",
    "zf_003",
    "zf_004",
    "zf_005",
    "zf_006",
    "zf_007",
    "zf_008",
    "zf_017",
    "zf_018",
    "zf_019",
    "zf_021",
    "zf_022",
    "zf_023",
    "zf_024",
    "zf_026",
    "zf_027",
    "zf_028",
    "zf_032",
    "zf_036",
    "zf_038",
    "zf_039",
    "zf_040",
    "zf_042",
    "zf_043",
    "zf_044",
    "zf_046",
    "zf_047",
    "zf_048",
    "zf_049",
    "zf_051",
    "zf_059",
    "zf_060",
    "zf_067",
    "zf_070",
    "zf_071",
    "zf_072",
    "zf_073",
    "zf_074",
    "zf_075",
    "zf_076",
    "zf_077",
    "zf_078",
    "zf_079",
    "zf_083",
    "zf_084",
    "zf_085",
    "zf_086",
    "zf_087",
    "zf_088",
    "zf_090",
    "zf_092",
    "zf_093",
    "zf_094",
    "zf_099",
    "zm_009",
    "zm_010",
    "zm_011",
    "zm_012",
    "zm_013",
    "zm_014",
    "zm_015",
    "zm_016",
    "zm_020",
    "zm_025",
    "zm_029",
    "zm_030",
    "zm_031",
    "zm_033",
    "zm_034",
    "zm_035",
    "zm_037",
    "zm_041",
    "zm_045",
    "zm_050",
    "zm_052",
    "zm_053",
    "zm_054",
    "zm_055",
    "zm_056",
    "zm_057",
    "zm_058",
    "zm_061",
    "zm_062",
    "zm_063",
    "zm_064",
    "zm_065",
    "zm_066",
    "zm_068",
    "zm_069",
    "zm_080",
    "zm_081",
    "zm_082",
    "zm_089",
    "zm_091",
    "zm_095",
    "zm_096",
    "zm_097",
    "zm_098",
    "zm_100",
)


def _kokoro_voice_record(sid: int, voice_id: str) -> dict[str, Any]:
    if voice_id.startswith("zf_"):
        language = "zh-CN"
        gender = "female"
        name = f"Kokoro 中文女声 {voice_id[3:]}"
        fallback_id = "zf_003" if voice_id == "zf_002" else "zf_002"
    elif voice_id.startswith("zm_"):
        language = "zh-CN"
        gender = "male"
        name = f"Kokoro 中文男声 {voice_id[3:]}"
        fallback_id = "zm_011" if voice_id == "zm_010" else "zm_010"
    elif voice_id.startswith("bf_"):
        language = "en-GB"
        gender = "female"
        name = "Kokoro British female Vale"
        fallback_id = "af_maple"
    else:
        language = "en-US"
        gender = "female"
        name = f"Kokoro American female {voice_id[3:].title()}"
        fallback_id = "af_sol" if voice_id == "af_maple" else "af_maple"
    return {
        "id": voice_id,
        "name": name,
        "language": language,
        "locale": language,
        "gender": gender,
        "sid": sid,
        "fallbackId": fallback_id,
        "provider": "kokoro",
    }


KOKORO_VOICE_BY_SID = {
    sid: _kokoro_voice_record(sid, voice_id) for sid, voice_id in enumerate(KOKORO_SPEAKER_NAMES)
}
KOKORO_VOICE_BY_ID = {voice["id"]: voice for voice in KOKORO_VOICE_BY_SID.values()}
KOKORO_CHINESE_CATALOG_ORDER = ("zf_002", "zf_001", "zf_003", "zm_010", "zm_011")


def kokoro_voice_catalog(available: bool = False) -> list[dict[str, Any]]:
    """Return all fixed Kokoro voices with Chinese choices ordered first."""

    ordered_ids = [*KOKORO_CHINESE_CATALOG_ORDER]
    ordered_ids.extend(voice_id for voice_id in KOKORO_SPEAKER_NAMES if voice_id not in ordered_ids)
    return [{**KOKORO_VOICE_BY_ID[voice_id], "available": bool(available)} for voice_id in ordered_ids]


def _normalize_kokoro_language(language: str) -> str:
    normalized = str(language or "").strip().lower().replace("_", "-")
    if normalized == "zh" or normalized.startswith("zh-"):
        return "zh"
    if normalized == "en" or normalized.startswith("en-"):
        return "en"
    raise KokoroRuntimeError("Kokoro supports only Chinese and English target languages")


def _select_kokoro_voice(language: str, voice_id: str) -> dict[str, Any]:
    chinese = _normalize_kokoro_language(language) == "zh"
    selected = str(voice_id or "").strip()
    candidate = KOKORO_VOICE_BY_ID.get(selected)
    if candidate and (candidate["id"].startswith(("zf_", "zm_")) == chinese):
        return candidate
    return KOKORO_VOICE_BY_ID["zf_002" if chinese else "af_maple"]


class KokoroRuntime:
    """Lazy, bounded sherpa-onnx Kokoro inference for the fixed local model."""

    max_concurrent_jobs = 1
    num_threads = KOKORO_NUM_THREADS
    provider = "cpu"

    def __init__(
        self,
        model_manager: KokoroModelManager,
        *,
        clock: Callable[[], float] = time.monotonic,
        sherpa_loader: Optional[Callable[[], Any]] = None,
        runtime_probe: Optional[Callable[[], Any]] = None,
        schedule_idle_release: bool = True,
        idle_unload_seconds: float = KOKORO_IDLE_UNLOAD_SECONDS,
    ) -> None:
        self.model_manager = model_manager
        self._clock = clock
        self._sherpa_loader = sherpa_loader or self._load_sherpa_onnx
        self._runtime_probe = runtime_probe or self._installed_sherpa_version
        self._schedule_idle_release = bool(schedule_idle_release)
        self._idle_unload_seconds = max(1.0, float(idle_unload_seconds))
        self._state_lock = threading.RLock()
        self._tts: Any | None = None
        self._last_used = 0.0
        self._active_job = False
        self._idle_timer: threading.Timer | None = None
        self._runtime_error = ""

    @property
    def loaded(self) -> bool:
        with self._state_lock:
            return self._tts is not None

    def status(self) -> dict[str, Any]:
        model = self.model_manager.status()
        model_state = str(model.get("state") or "not-installed")
        runtime_version = self._runtime_version()
        with self._state_lock:
            loaded = self._tts is not None
            runtime_error = self._runtime_error
        if model_state != "ready":
            state = "model-not-installed" if model_state == "not-installed" else f"model-{model_state}"
        elif not runtime_version:
            state = "runtime-not-installed"
        elif runtime_version != KOKORO_SHERPA_ONNX_VERSION or runtime_error:
            state = "runtime-incompatible"
        else:
            state = "ready"
        health_error = runtime_error
        if not health_error and runtime_version and runtime_version != KOKORO_SHERPA_ONNX_VERSION:
            health_error = (
                f"Kokoro requires sherpa-onnx {KOKORO_SHERPA_ONNX_VERSION}, found {runtime_version}"
            )
        return {
            "state": state,
            "available": state == "ready",
            "loaded": loaded,
            "runtimeVersion": runtime_version,
            "requiredRuntimeVersion": KOKORO_SHERPA_ONNX_VERSION,
            "numThreads": self.num_threads,
            "provider": self.provider,
            "error": health_error,
        }

    def synthesize(
        self,
        text: str,
        language: str,
        voice_id: str,
        rate: float,
        output_path: Path,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict[str, Any]:
        value = str(text or "").strip()
        if not value:
            raise KokoroRuntimeError("Kokoro requires non-empty text")
        selected_voice = _select_kokoro_voice(language, voice_id)
        fallback_voice = KOKORO_VOICE_BY_ID[str(selected_voice["fallbackId"])]
        if fallback_voice["id"] == selected_voice["id"]:
            raise KokoroRuntimeError("Kokoro voice fallback configuration is invalid")

        self._acquire_synthesis_lock(cancel_event)
        try:
            with self._state_lock:
                self._active_job = True
            try:
                tts = self._ensure_loaded()
                output = Path(output_path)
                try:
                    result = self._synthesize_voice(tts, value, selected_voice, rate, output, selected_voice)
                    self._raise_if_synthesis_cancelled(cancel_event)
                    return result
                except KokoroRuntimeError as selected_error:
                    self._raise_if_synthesis_cancelled(cancel_event)
                    try:
                        result = self._synthesize_voice(
                            tts,
                            value,
                            fallback_voice,
                            rate,
                            output,
                            selected_voice,
                            selected_error,
                        )
                        self._raise_if_synthesis_cancelled(cancel_event)
                        return result
                    except KokoroRuntimeError as fallback_error:
                        raise KokoroRuntimeError(
                            f"Kokoro cannot generate speech with {selected_voice['id']} or its local fallback "
                            f"{fallback_voice['id']}: {fallback_error}"
                        ) from fallback_error
            finally:
                with self._state_lock:
                    self._active_job = False
                    self._last_used = self._clock()
                self._schedule_release()
        finally:
            KOKORO_SYNTHESIS_LOCK.release()

    def release_if_idle(self) -> bool:
        """Release inference deterministically once no work used it for five minutes."""

        with self._state_lock:
            if self._tts is None or self._active_job:
                return False
            if self._clock() - self._last_used < self._idle_unload_seconds:
                return False
            self._tts = None
            self._runtime_error = ""
            timer = self._idle_timer
            self._idle_timer = None
        if timer:
            timer.cancel()
        return True

    def _synthesize_voice(
        self,
        tts: Any,
        text: str,
        actual_voice: Mapping[str, Any],
        rate: float,
        output_path: Path,
        requested_voice: Mapping[str, Any],
        prior_error: Optional[BaseException] = None,
    ) -> dict[str, Any]:
        try:
            if prior_error is None:
                # The selected voice gets one bounded retry. The locale fallback gets
                # a single attempt so a broken voice cannot hold up later segments.
                try:
                    audio = tts.generate(text=text, sid=int(actual_voice["sid"]), speed=self._clamp_rate(rate))
                    self._write_pcm16_wav(audio, output_path)
                except Exception:
                    audio = tts.generate(text=text, sid=int(actual_voice["sid"]), speed=self._clamp_rate(rate))
                    self._write_pcm16_wav(audio, output_path)
            else:
                audio = tts.generate(text=text, sid=int(actual_voice["sid"]), speed=self._clamp_rate(rate))
                self._write_pcm16_wav(audio, output_path)
        except KokoroRuntimeError:
            raise
        except Exception as error:
            raise KokoroRuntimeError(f"Kokoro voice {actual_voice['id']} failed: {error}") from error

        duration = self._validate_pcm16_wav(output_path)
        fallback = actual_voice["id"] != requested_voice["id"]
        return {
            "path": Path(output_path),
            "duration": duration,
            "sampleRate": KOKORO_SAMPLE_RATE,
            "requestedVoice": requested_voice["id"],
            "actualVoice": actual_voice["id"],
            "voiceFallback": fallback,
            "voiceFallbackMessage": (
                f"当前 Kokoro 音色 {requested_voice['id']} 不可用，已切换为 {actual_voice['id']}。" if fallback else ""
            ),
        }

    def _ensure_loaded(self) -> Any:
        with self._state_lock:
            if self._tts is not None:
                return self._tts
        model = self.model_manager.status()
        if str(model.get("state") or "") != "ready":
            raise KokoroRuntimeError("Kokoro model is not installed or is not ready")
        installed_version = self._runtime_version()
        if installed_version != KOKORO_SHERPA_ONNX_VERSION:
            found = installed_version or "not installed"
            raise KokoroRuntimeError(
                f"Kokoro runtime requires sherpa-onnx {KOKORO_SHERPA_ONNX_VERSION}, found {found}"
            )
        try:
            sherpa_onnx = self._sherpa_loader()
            actual_version = str(getattr(sherpa_onnx, "__version__", "") or "").strip()
            if actual_version != KOKORO_SHERPA_ONNX_VERSION:
                found = actual_version or "unversioned module"
                raise KokoroRuntimeError(
                    f"Kokoro runtime requires sherpa-onnx {KOKORO_SHERPA_ONNX_VERSION}, found {found}"
                )
            active_path = Path(self.model_manager.active_path)
            config = sherpa_onnx.OfflineTtsConfig(
                model=sherpa_onnx.OfflineTtsModelConfig(
                    kokoro=sherpa_onnx.OfflineTtsKokoroModelConfig(
                        model=str(active_path / "model.int8.onnx"),
                        voices=str(active_path / "voices.bin"),
                        tokens=str(active_path / "tokens.txt"),
                        lexicon=f"{active_path / 'lexicon-us-en.txt'},{active_path / 'lexicon-zh.txt'}",
                        data_dir=str(active_path / "espeak-ng-data"),
                    ),
                    num_threads=self.num_threads,
                    provider=self.provider,
                    debug=False,
                ),
                max_num_sentences=1,
                silence_scale=0.2,
            )
            validate = getattr(config, "validate", None)
            if callable(validate) and not validate():
                raise KokoroRuntimeError("Kokoro runtime configuration is invalid")
            loaded = sherpa_onnx.OfflineTts(config)
        except KokoroRuntimeError as error:
            with self._state_lock:
                self._runtime_error = str(error)
            raise
        except Exception as error:
            with self._state_lock:
                self._runtime_error = str(error)
            raise KokoroRuntimeError(f"Kokoro runtime failed to load: {error}") from error
        with self._state_lock:
            self._tts = loaded
            self._runtime_error = ""
        return loaded

    def _schedule_release(self) -> None:
        if not self._schedule_idle_release:
            return
        with self._state_lock:
            previous = self._idle_timer
            timer = threading.Timer(self._idle_unload_seconds, self.release_if_idle)
            timer.daemon = True
            self._idle_timer = timer
        if previous:
            previous.cancel()
        timer.start()

    def _runtime_version(self) -> str:
        try:
            value = self._runtime_probe()
        except Exception:
            return ""
        if value is None or isinstance(value, bool):
            return ""
        return str(value).strip()

    @staticmethod
    def _installed_sherpa_version() -> str:
        try:
            return str(importlib.metadata.version("sherpa-onnx") or "").strip()
        except importlib.metadata.PackageNotFoundError:
            return ""

    @staticmethod
    def _raise_if_synthesis_cancelled(cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise KokoroRuntimeCancelled("Kokoro synthesis was cancelled")

    @classmethod
    def _acquire_synthesis_lock(cls, cancel_event: Optional[threading.Event]) -> None:
        if cancel_event is None:
            KOKORO_SYNTHESIS_LOCK.acquire()
            return
        while True:
            cls._raise_if_synthesis_cancelled(cancel_event)
            if KOKORO_SYNTHESIS_LOCK.acquire(timeout=0.05):
                try:
                    cls._raise_if_synthesis_cancelled(cancel_event)
                except Exception:
                    KOKORO_SYNTHESIS_LOCK.release()
                    raise
                return

    @staticmethod
    def _load_sherpa_onnx() -> Any:
        return importlib.import_module("sherpa_onnx")

    @staticmethod
    def _clamp_rate(rate: float) -> float:
        return max(0.6, min(float(rate), 1.8))

    @staticmethod
    def _write_pcm16_wav(audio: Any, output_path: Path) -> None:
        samples = list(getattr(audio, "samples", ()) or ())
        sample_rate = int(getattr(audio, "sample_rate", 0) or 0)
        if sample_rate != KOKORO_SAMPLE_RATE:
            raise KokoroRuntimeError(f"Kokoro returned unsupported sample rate {sample_rate}")
        if not samples:
            raise KokoroRuntimeError("Kokoro returned empty audio")
        pcm_samples = array("h")
        for sample in samples:
            value = float(sample)
            if not math.isfinite(value):
                raise KokoroRuntimeError("Kokoro returned non-finite audio")
            pcm_samples.append(int(round(max(-1.0, min(1.0, value)) * 32767.0)))
        if not pcm_samples:
            raise KokoroRuntimeError("Kokoro returned empty audio")
        if sys.byteorder != "little":
            pcm_samples.byteswap()
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(destination), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(KOKORO_SAMPLE_RATE)
            output.writeframes(pcm_samples.tobytes())

    @staticmethod
    def _validate_pcm16_wav(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as audio:
                channels = audio.getnchannels()
                width = audio.getsampwidth()
                rate = audio.getframerate()
                frames = audio.getnframes()
                compression = audio.getcomptype()
        except (OSError, EOFError, wave.Error) as error:
            raise KokoroRuntimeError(f"Kokoro did not write a valid WAV: {error}") from error
        if channels != 1 or width != 2 or rate != KOKORO_SAMPLE_RATE or frames <= 0 or compression != "NONE":
            raise KokoroRuntimeError("Kokoro did not write a valid 24 kHz mono PCM16 WAV")
        return frames / rate
