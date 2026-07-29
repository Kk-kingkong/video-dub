#!/usr/bin/env python3
from __future__ import annotations

import io
import hashlib
import importlib
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

kokoro = importlib.import_module("server.kokoro_tts")


def make_tar(root: Path, entries: dict[str, bytes]) -> Path:
    archive = root / "model.tar"
    with tarfile.open(archive, "w") as output:
        for name, contents in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            output.addfile(member, io.BytesIO(contents))
    return archive


def test_model_manifest_is_immutable() -> None:
    try:
        kokoro.KOKORO_MODEL_MANIFEST["url"] = "https://evil.invalid/model"  # type: ignore[index]
    except TypeError:
        return
    raise AssertionError("the fixed model manifest must be immutable")


def test_model_manifest_is_fixed_and_callers_cannot_override_url(tmp_path: Path) -> None:
    manager = kokoro.KokoroModelManager(tmp_path)
    assert manager.status()["state"] == "not-installed"
    assert manager.install_request({"url": "https://evil.invalid/model"})["code"] == "INVALID_MODEL_REQUEST"


def test_archive_traversal_is_rejected(tmp_path: Path) -> None:
    archive = make_tar(tmp_path, {"../escape": b"x"})
    try:
        kokoro.extract_verified_archive(archive, tmp_path / "stage", {"model.int8.onnx"})
    except kokoro.KokoroModelError as error:
        assert "unsafe archive path" in str(error)
    else:
        raise AssertionError("archive traversal must be rejected")


def test_archive_unexpected_file_is_rejected(tmp_path: Path) -> None:
    archive = make_tar(tmp_path, {"model.int8.onnx": b"model", "surprise.bin": b"x"})
    try:
        kokoro.extract_verified_archive(archive, tmp_path / "stage", {"model.int8.onnx"})
    except kokoro.KokoroModelError as error:
        assert "unexpected archive file" in str(error)
    else:
        raise AssertionError("unexpected archive files must be rejected")


def test_verified_install_activates_atomically_and_uninstall_is_idempotent(tmp_path: Path) -> None:
    archive = make_tar(tmp_path, {"model.int8.onnx": b"model", "voices.bin": b"voices"})
    manifest = {
        "id": "test-model",
        "version": "test",
        "url": "https://example.invalid/test-model.tar",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archiveBytes": archive.stat().st_size,
        "installedBytes": len(b"modelvoices"),
        "requiredFiles": ("model.int8.onnx", "voices.bin"),
    }
    manager = kokoro.KokoroModelManager(tmp_path / "models", manifest)

    result = manager.install(lambda _url: archive)

    assert result["state"] == "ready"
    assert manager.status()["installedBytes"] == len(b"modelvoices")
    assert (manager.active_path / "model.int8.onnx").read_bytes() == b"model"
    assert manager.uninstall()["state"] == "not-installed"
    assert manager.uninstall()["state"] == "not-installed"


def test_digest_failure_never_activates_a_model(tmp_path: Path) -> None:
    archive = make_tar(tmp_path, {"model.int8.onnx": b"model"})
    manifest = {
        "id": "test-model",
        "version": "test",
        "url": "https://example.invalid/test-model.tar",
        "sha256": "0" * 64,
        "archiveBytes": archive.stat().st_size,
        "installedBytes": len(b"model"),
        "requiredFiles": ("model.int8.onnx",),
    }
    manager = kokoro.KokoroModelManager(tmp_path / "models", manifest)

    result = manager.install(lambda _url: archive)

    assert result["state"] == "failed"
    assert not manager.active_path.exists()


def test_cancellation_before_activation_never_installs_a_model(tmp_path: Path) -> None:
    archive = make_tar(tmp_path, {"model.int8.onnx": b"model"})
    manifest = {
        "id": "test-model",
        "version": "test",
        "url": "https://example.invalid/test-model.tar",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archiveBytes": archive.stat().st_size,
        "installedBytes": len(b"model"),
        "requiredFiles": ("model.int8.onnx",),
    }
    manager = kokoro.KokoroModelManager(tmp_path / "models", manifest)
    original_write_metadata = manager._write_activation_metadata

    def cancel_before_activation(extracted, installed_bytes):
        original_write_metadata(extracted, installed_bytes)
        manager.cancel()

    manager._write_activation_metadata = cancel_before_activation
    result = manager.install(lambda _url: archive)

    assert result["state"] == "not-installed"
    assert not manager.active_path.exists()


def main() -> None:
    test_model_manifest_is_immutable()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        test_model_manifest_is_fixed_and_callers_cannot_override_url(temp_dir / "model")
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_archive_traversal_is_rejected(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_archive_unexpected_file_is_rejected(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_verified_install_activates_atomically_and_uninstall_is_idempotent(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_digest_failure_never_activates_a_model(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_cancellation_before_activation_never_installs_a_model(Path(temp_dir_name))
    print("kokoro engine checks ok")


if __name__ == "__main__":
    main()
