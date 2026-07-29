"""Pinned Kokoro model installation with local-only state management."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.parse
import urllib.request
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
        "installedBytes": 0,
        "requiredFiles": (
            "model.int8.onnx",
            "voices.bin",
            "tokens.txt",
            "lexicon-zh.txt",
            "date-zh.fst",
            "number-zh.fst",
            "phone-zh.fst",
        ),
    }
)


class KokoroModelError(RuntimeError):
    """A downloaded Kokoro model failed a local validation boundary."""


class KokoroModelCancelled(KokoroModelError):
    """A model installation was cancelled before activation."""


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


def extract_verified_archive(archive: Path, destination: Path, required_files: Set[str]) -> int:
    """Extract an exact set of regular files without following archive links."""

    expected_files = _normalized_required_files(required_files)
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=False)
    destination_root = destination.resolve()

    try:
        with tarfile.open(archive, "r:*") as input_archive:
            members = input_archive.getmembers()
            regular_members = [member for member in members if member.isfile()]
            parsed_paths = [_safe_relative_path(member.name) for member in regular_members]
            common_prefix: Optional[str] = None
            if parsed_paths and all(len(path.parts) > 1 for path in parsed_paths):
                first_parts = {path.parts[0] for path in parsed_paths}
                if len(first_parts) == 1:
                    common_prefix = next(iter(first_parts))

            extracted: Set[PurePosixPath] = set()
            total_bytes = 0
            for member in members:
                member_path = _safe_relative_path(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise KokoroModelError("unsafe archive member")

                relative_path = member_path
                if common_prefix is not None:
                    relative_path = PurePosixPath(*member_path.parts[1:])
                if relative_path not in expected_files:
                    raise KokoroModelError("unexpected archive file")
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
        shutil.rmtree(destination, ignore_errors=True)
        raise KokoroModelError("model archive is missing required files")
    return total_bytes


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise KokoroModelError("model download redirect must use HTTPS")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class KokoroModelManager:
    """Own the fixed model's staging, validation, and atomic activation."""

    def __init__(self, root: Path, manifest: Optional[dict] = None) -> None:
        self.root = Path(root).expanduser().resolve()
        source_manifest = KOKORO_MODEL_MANIFEST if manifest is None else manifest
        self.manifest = MappingProxyType(dict(source_manifest))
        self._required_files = _normalized_required_files(set(self.manifest["requiredFiles"]))
        self.active_path = self.root / "active"
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._state = "not-installed"
        self._error = ""
        self._downloaded_bytes = 0

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

    def install(self, fetcher: Optional[Fetcher] = None) -> dict[str, Any]:
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
        }
        (extracted / ".kokoro-model.json").write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")

    def _activate(self, extracted: Path) -> None:
        replacement = self.root / ".kokoro-active-next"
        backup = self.root / ".kokoro-active-previous"
        shutil.rmtree(replacement, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
        os.replace(extracted, replacement)
        try:
            if self.active_path.exists():
                os.replace(self.active_path, backup)
            os.replace(replacement, self.active_path)
        except OSError:
            if backup.exists() and not self.active_path.exists():
                os.replace(backup, self.active_path)
            raise
        finally:
            shutil.rmtree(backup, ignore_errors=True)
            shutil.rmtree(replacement, ignore_errors=True)

    def _active_model_is_valid(self) -> bool:
        try:
            metadata_path = self.active_path / ".kokoro-model.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("id") != self.manifest["id"] or metadata.get("version") != self.manifest["version"]:
                return False
            active_root = self.active_path.resolve()
            for relative_path in self._required_files:
                candidate = self.active_path.joinpath(*relative_path.parts)
                if candidate.is_symlink() or not candidate.is_file():
                    return False
                candidate.resolve().relative_to(active_root)
            return True
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def _installed_bytes(self) -> int:
        return sum((self.active_path.joinpath(*path.parts)).stat().st_size for path in self._required_files)

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise KokoroModelCancelled("model installation cancelled")
