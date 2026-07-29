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


PRODUCTION_ARCHIVE_ROOT = "kokoro-int8-multi-lang-v1_1"
PRODUCTION_ROOT_FILES = (
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
)
PRODUCTION_REQUIRED_FILES = (
    "date-zh.fst",
    "lexicon-gb-en.txt",
    "lexicon-us-en.txt",
    "lexicon-zh.txt",
    "model.int8.onnx",
    "number-zh.fst",
    "phone-zh.fst",
    "tokens.txt",
    "voices.bin",
)


def make_tar(root: Path, entries: dict[str, bytes]) -> Path:
    archive = root / "model.tar"
    with tarfile.open(archive, "w") as output:
        for name, contents in entries.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            output.addfile(member, io.BytesIO(contents))
    return archive


def production_like_entries() -> dict[str, bytes]:
    entries = {
        f"{PRODUCTION_ARCHIVE_ROOT}/{name}": f"root:{name}".encode("ascii")
        for name in PRODUCTION_ROOT_FILES
    }
    entries.update(
        {
            f"{PRODUCTION_ARCHIVE_ROOT}/dict/cmudict": b"dict",
            f"{PRODUCTION_ARCHIVE_ROOT}/dict/subdir/entries": b"dict-subdir",
            f"{PRODUCTION_ARCHIVE_ROOT}/espeak-ng-data/phontab": b"espeak",
            f"{PRODUCTION_ARCHIVE_ROOT}/espeak-ng-data/lang/en": b"english",
        }
    )
    return entries


def manifest_for_archive(archive: Path, entries: dict[str, bytes]) -> dict:
    return {
        "id": "test-model",
        "version": "test",
        "url": "https://example.invalid/test-model.tar",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archiveBytes": archive.stat().st_size,
        "installedBytes": sum(len(contents) for contents in entries.values()),
        "archiveRoot": PRODUCTION_ARCHIVE_ROOT,
        "allowedRootFiles": PRODUCTION_ROOT_FILES,
        "allowedPrefixes": ("dict", "espeak-ng-data"),
        "requiredFiles": PRODUCTION_REQUIRED_FILES,
        "fileCount": len(entries),
    }


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


def test_nested_layout_rejects_unapproved_prefix(tmp_path: Path) -> None:
    entries = production_like_entries()
    entries[f"{PRODUCTION_ARCHIVE_ROOT}/plugins/evil.bin"] = b"x"
    archive = make_tar(tmp_path, entries)
    manifest = manifest_for_archive(archive, entries)
    manager = kokoro.KokoroModelManager._for_tests(tmp_path / "models", manifest)

    result = manager._install_for_tests(lambda _url: archive)

    assert result["state"] == "failed"
    assert "unexpected archive prefix" in result["error"]
    assert not manager.active_path.exists()


def test_nested_layout_rejects_wrong_file_count_and_size(tmp_path: Path) -> None:
    entries = production_like_entries()
    archive = make_tar(tmp_path, entries)
    for field, expected_error in (("fileCount", "unexpected model file count"), ("installedBytes", "unexpected installed model size")):
        manifest = manifest_for_archive(archive, entries)
        manifest[field] += 1
        manager = kokoro.KokoroModelManager._for_tests(tmp_path / field, manifest)

        result = manager._install_for_tests(lambda _url: archive)

        assert result["state"] == "failed"
        assert expected_error in result["error"]
        assert not manager.active_path.exists()


def test_archive_links_and_duplicate_members_are_rejected(tmp_path: Path) -> None:
    for link_type in (tarfile.SYMTYPE, tarfile.LNKTYPE):
        archive = tmp_path / f"link-{link_type.decode('ascii')}.tar"
        with tarfile.open(archive, "w") as output:
            regular = tarfile.TarInfo("model.int8.onnx")
            regular.size = 1
            output.addfile(regular, io.BytesIO(b"m"))
            link = tarfile.TarInfo("linked-model")
            link.type = link_type
            link.linkname = "model.int8.onnx"
            output.addfile(link)
        try:
            kokoro.extract_verified_archive(archive, tmp_path / f"stage-{link_type.decode('ascii')}", {"model.int8.onnx"})
        except kokoro.KokoroModelError as error:
            assert "unsafe archive member" in str(error)
        else:
            raise AssertionError("archive links must be rejected")

    duplicate_archive = tmp_path / "duplicate.tar"
    with tarfile.open(duplicate_archive, "w") as output:
        for contents in (b"first", b"second"):
            member = tarfile.TarInfo("model.int8.onnx")
            member.size = len(contents)
            output.addfile(member, io.BytesIO(contents))
    try:
        kokoro.extract_verified_archive(duplicate_archive, tmp_path / "duplicate-stage", {"model.int8.onnx"})
    except kokoro.KokoroModelError as error:
        assert "duplicate archive file" in str(error)
    else:
        raise AssertionError("duplicate archive members must be rejected")


def test_nested_production_layout_installs_only_fixed_runtime_content(tmp_path: Path) -> None:
    entries = production_like_entries()
    archive = make_tar(tmp_path, entries)
    manager = kokoro.KokoroModelManager._for_tests(tmp_path / "models", manifest_for_archive(archive, entries))

    result = manager._install_for_tests(lambda _url: archive)

    assert result["state"] == "ready"
    assert (manager.active_path / "lexicon-us-en.txt").is_file()
    assert (manager.active_path / "dict" / "subdir" / "entries").read_bytes() == b"dict-subdir"
    assert (manager.active_path / "espeak-ng-data" / "lang" / "en").read_bytes() == b"english"


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
    manager = kokoro.KokoroModelManager._for_tests(tmp_path / "models", manifest)

    result = manager._install_for_tests(lambda _url: archive)

    assert result["state"] == "ready"
    assert manager.status()["installedBytes"] == len(b"modelvoices")
    assert (manager.active_path / "model.int8.onnx").read_bytes() == b"model"
    assert manager.uninstall()["state"] == "not-installed"
    assert manager.uninstall()["state"] == "not-installed"


def test_failed_activation_keeps_backup_when_rollback_fails(tmp_path: Path) -> None:
    manager = kokoro.KokoroModelManager(tmp_path / "models")
    manager.root.mkdir(parents=True)
    manager.active_path.mkdir()
    (manager.active_path / "known-good").write_bytes(b"old")
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    (extracted / "candidate").write_bytes(b"new")
    replacement = manager.root / ".kokoro-active-next"
    backup = manager.root / ".kokoro-active-previous"
    original_replace = kokoro.os.replace

    def fail_activation_and_rollback(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path == manager.active_path and source_path in {replacement, backup}:
            raise OSError("injected activation failure")
        return original_replace(source, destination)

    kokoro.os.replace = fail_activation_and_rollback
    try:
        try:
            manager._activate(extracted)
        except OSError:
            pass
        else:
            raise AssertionError("activation failure must be surfaced")
    finally:
        kokoro.os.replace = original_replace

    assert backup.exists()
    assert (backup / "known-good").read_bytes() == b"old"


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
    manager = kokoro.KokoroModelManager._for_tests(tmp_path / "models", manifest)

    result = manager._install_for_tests(lambda _url: archive)

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
    manager = kokoro.KokoroModelManager._for_tests(tmp_path / "models", manifest)
    original_write_metadata = manager._write_activation_metadata

    def cancel_before_activation(extracted, installed_bytes):
        original_write_metadata(extracted, installed_bytes)
        manager.cancel()

    manager._write_activation_metadata = cancel_before_activation
    result = manager._install_for_tests(lambda _url: archive)

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
        test_nested_layout_rejects_unapproved_prefix(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_nested_layout_rejects_wrong_file_count_and_size(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_archive_links_and_duplicate_members_are_rejected(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_nested_production_layout_installs_only_fixed_runtime_content(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_verified_install_activates_atomically_and_uninstall_is_idempotent(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_failed_activation_keeps_backup_when_rollback_fails(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_digest_failure_never_activates_a_model(Path(temp_dir_name))
    with tempfile.TemporaryDirectory() as temp_dir_name:
        test_cancellation_before_activation_never_installs_a_model(Path(temp_dir_name))
    print("kokoro engine checks ok")


if __name__ == "__main__":
    main()
