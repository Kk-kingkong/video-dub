#!/usr/bin/env python3
from __future__ import annotations

import io
import hashlib
import importlib
import math
import sys
import tarfile
import tempfile
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

kokoro = importlib.import_module("server.kokoro_tts")
local_server = importlib.import_module("server.local_dub_server")


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


class FakeAsyncModelManager:
    """Small deterministic model manager used only to test protocol scheduling."""

    def __init__(self) -> None:
        self.state = "not-installed"
        self.install_calls = 0
        self.cancel_calls = 0
        self.uninstall_calls = 0
        self.started = threading.Event()
        self.release = threading.Event()

    def status(self) -> dict:
        return {
            "state": self.state,
            "version": "test",
            "downloadedBytes": 0,
            "totalBytes": 100,
            "progress": 1 if self.state == "ready" else 0,
            "installedBytes": 0,
            "error": "",
        }

    def install(self) -> dict:
        self.install_calls += 1
        self.state = "installing"
        self.started.set()
        self.release.wait(2)
        if self.state == "installing":
            self.state = "ready"
        return self.status()

    def cancel(self) -> dict:
        self.cancel_calls += 1
        self.state = "not-installed"
        self.release.set()
        return self.status()

    def uninstall(self) -> dict:
        self.uninstall_calls += 1
        self.state = "not-installed"
        self.release.set()
        return self.status()


class LateActivationModelManager(FakeAsyncModelManager):
    """Simulates an installer that reports ready after cancellation was requested."""

    def install(self) -> dict:
        self.install_calls += 1
        self.state = "installing"
        self.started.set()
        self.release.wait(2)
        self.state = "ready"
        return self.status()

    def cancel(self) -> dict:
        self.cancel_calls += 1
        self.release.set()
        return self.status()


def test_protocol_status_schema_and_async_install_reuse() -> None:
    manager = FakeAsyncModelManager()
    service = local_server.KokoroModelService(manager)

    first = service.install("http")
    assert first["ok"] is True
    assert first["transport"] == "http"
    assert first["model"]["state"] == "installing"
    assert manager.started.wait(1)
    second = service.install("http")
    assert second["ok"] is True
    assert second["model"]["state"] == "installing"
    assert manager.install_calls == 1

    cancelled = service.cancel("http")
    assert cancelled["ok"] is True
    assert cancelled["model"]["state"] == "not-installed"
    assert manager.cancel_calls == 1
    assert service.uninstall("http")["model"]["state"] == "not-installed"
    assert service.uninstall("http")["model"]["state"] == "not-installed"
    assert manager.uninstall_calls >= 2
    ready_manager = FakeAsyncModelManager()
    ready_manager.state = "ready"
    ready_service = local_server.KokoroModelService(ready_manager)
    assert ready_service.install("http")["model"]["state"] == "ready"
    assert ready_manager.install_calls == 0


def test_cancel_or_uninstall_cleans_up_late_activation() -> None:
    manager = LateActivationModelManager()
    service = local_server.KokoroModelService(manager)
    assert service.install("native")["model"]["state"] == "installing"
    assert manager.started.wait(1)
    service.cancel("native")
    for _ in range(50):
        if manager.uninstall_calls:
            break
        threading.Event().wait(0.01)
    assert manager.uninstall_calls == 1
    assert service.status("native")["model"]["state"] == "not-installed"


def test_http_model_routes_allow_only_empty_objects() -> None:
    manager = FakeAsyncModelManager()
    service = local_server.KokoroModelService(manager)
    original_service = local_server.KOKORO_MODEL_SERVICE
    local_server.KOKORO_MODEL_SERVICE = service
    try:
        captured: list[tuple[dict, int]] = []
        handler = object.__new__(local_server.LocalDubHandler)
        handler.path = "/api/tts-model/kokoro/status"
        handler.send_json = lambda payload, status=200: captured.append((payload, status))
        handler.do_GET()
        status, status_code = captured.pop()
        assert status["ok"] is True
        assert status_code == 200
        assert status["transport"] == "http"
        assert status["model"]["state"] == "not-installed"

        for endpoint in ("install", "cancel", "uninstall"):
            handler.path = f"/api/tts-model/kokoro/{endpoint}"
            handler.read_json = lambda: {"url": "https://evil.invalid/model"}
            handler.do_POST()
            rejected, rejected_status = captured.pop()
            assert rejected["ok"] is False
            assert rejected["code"] == "INVALID_MODEL_REQUEST"
            assert rejected_status == 400
        assert manager.install_calls == 0
        handler.path = "/api/tts-model/kokoro/install"
        handler.read_json = lambda: (_ for _ in ()).throw(ValueError("JSON body must be an object"))
        handler.do_POST()
        rejected, rejected_status = captured.pop()
        assert rejected["code"] == "INVALID_MODEL_REQUEST"
        assert rejected_status == 400
    finally:
        local_server.KOKORO_MODEL_SERVICE = original_service


class FakeKokoroModelManager:
    """Ready local model data without downloading a production model in tests."""

    def __init__(self, root: Path) -> None:
        self.active_path = root / "active"
        self.active_path.mkdir(parents=True)
        for name in (
            "model.int8.onnx",
            "voices.bin",
            "tokens.txt",
            "lexicon-us-en.txt",
            "lexicon-zh.txt",
        ):
            (self.active_path / name).write_bytes(b"fixture")
        (self.active_path / "espeak-ng-data").mkdir()
        self.state = "ready"

    def status(self) -> dict:
        return {
            "state": self.state,
            "version": "1.1-int8",
            "installedBytes": 1,
            "downloadedBytes": 1,
            "totalBytes": 1,
            "progress": 1,
            "error": "",
        }


class FakeKokoroAudio:
    def __init__(self, samples, sample_rate=24000) -> None:
        self.samples = samples
        self.sample_rate = sample_rate


class FakeSherpaRuntime:
    """Minimal sherpa-onnx shape which records the requested runtime config."""

    def __init__(self, voice_samples: dict[str, list[object]] | None = None) -> None:
        self.voice_samples = voice_samples or {}
        self.configs = []
        self.generate_calls = []

        outer = self

        class OfflineTtsKokoroModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class OfflineTtsModelConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class OfflineTtsConfig:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)
                outer.configs.append(self)

            def validate(self):
                return True

        class OfflineTts:
            def __init__(self, config):
                self.config = config

            def generate(self, *, text, sid, speed):
                outer.generate_calls.append({"text": text, "sid": sid, "speed": speed})
                voice_id = kokoro.KOKORO_VOICE_BY_SID[sid]["id"]
                samples = outer.voice_samples.get(voice_id, [0.0, 0.25, -0.25, 0.5])
                if isinstance(samples, Exception):
                    raise samples
                return FakeKokoroAudio(samples)

        self.OfflineTtsKokoroModelConfig = OfflineTtsKokoroModelConfig
        self.OfflineTtsModelConfig = OfflineTtsModelConfig
        self.OfflineTtsConfig = OfflineTtsConfig
        self.OfflineTts = OfflineTts


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_complete_kokoro_voice_catalog_has_stable_provider_ids() -> None:
    catalog = kokoro.kokoro_voice_catalog(available=True)
    assert len(catalog) == 103
    assert len({voice["id"] for voice in catalog}) == 103
    assert {voice["provider"] for voice in catalog} == {"kokoro"}
    assert [voice["id"] for voice in catalog[:3]] == ["zf_002", "zf_001", "zf_003"]
    assert all(voice["available"] is True for voice in catalog)
    assert all(voice["locale"] == voice["language"] for voice in catalog)
    assert {voice["sid"] for voice in catalog} == set(range(103))
    for voice in catalog:
        if voice["id"].startswith("zf_"):
            assert voice["language"] == "zh-CN"
            assert voice["gender"] == "female"
            assert 3 <= voice["sid"] <= 57
        elif voice["id"].startswith("zm_"):
            assert voice["language"] == "zh-CN"
            assert voice["gender"] == "male"
            assert 58 <= voice["sid"] <= 102
        else:
            assert voice["id"] in {"af_maple", "af_sol", "bf_vale"}


def test_kokoro_runtime_is_lazy_uses_two_threads_and_releases_after_idle() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        clock = FakeClock()
        fake_sherpa = FakeSherpaRuntime()
        runtime = kokoro.KokoroRuntime(
            FakeKokoroModelManager(Path(temp_dir_name)),
            clock=clock,
            sherpa_loader=lambda: fake_sherpa,
            schedule_idle_release=False,
        )
        assert runtime.loaded is False
        assert runtime.status()["state"] == "ready"
        output = Path(temp_dir_name) / "voice.wav"
        result = runtime.synthesize("你好", "zh-CN", "auto", 1.0, output)
        assert runtime.loaded is True
        assert result["requestedVoice"] == "zf_002"
        assert result["actualVoice"] == "zf_002"
        assert result["voiceFallback"] is False
        assert fake_sherpa.configs[0].model.num_threads == 2
        assert fake_sherpa.configs[0].model.provider == "cpu"
        assert fake_sherpa.configs[0].max_num_sentences == 1
        assert fake_sherpa.configs[0].silence_scale == 0.2
        assert runtime.max_concurrent_jobs == 1
        assert runtime.num_threads == 2
        with wave.open(str(output), "rb") as audio:
            assert audio.getnchannels() == 1
            assert audio.getsampwidth() == 2
            assert audio.getframerate() == 24000
            assert audio.getnframes() == 4
        clock.advance(301)
        assert runtime.release_if_idle() is True
        assert runtime.loaded is False


def test_kokoro_voice_failure_retries_once_then_uses_one_same_provider_fallback() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        fake_sherpa = FakeSherpaRuntime(
            {
                "zf_001": RuntimeError("selected voice failed"),
                "zf_002": [0.1, -0.1, 0.2],
            }
        )
        runtime = kokoro.KokoroRuntime(
            FakeKokoroModelManager(Path(temp_dir_name)),
            sherpa_loader=lambda: fake_sherpa,
            schedule_idle_release=False,
        )
        result = runtime.synthesize("测试", "zh-CN", "zf_001", 1.0, Path(temp_dir_name) / "voice.wav")
        assert result["requestedVoice"] == "zf_001"
        assert result["actualVoice"] == "zf_002"
        assert result["voiceFallback"] is True
        assert "zf_002" in result["voiceFallbackMessage"]
        assert [call["sid"] for call in fake_sherpa.generate_calls] == [3, 3, 4]
        assert all(call["sid"] in {3, 4} for call in fake_sherpa.generate_calls)


def test_kokoro_rejects_empty_or_non_finite_output_without_cross_provider_fallback() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        fake_sherpa = FakeSherpaRuntime({"zf_002": [], "zf_003": [math.inf]})
        runtime = kokoro.KokoroRuntime(
            FakeKokoroModelManager(Path(temp_dir_name)),
            sherpa_loader=lambda: fake_sherpa,
            schedule_idle_release=False,
        )
        try:
            runtime.synthesize("测试", "zh-CN", "auto", 1.0, Path(temp_dir_name) / "voice.wav")
        except kokoro.KokoroRuntimeError as error:
            assert "Kokoro" in str(error)
        else:
            raise AssertionError("Kokoro errors must remain explicit when no Kokoro voice works")
        assert len(fake_sherpa.generate_calls) == 3


def test_kokoro_runtime_reports_model_and_runtime_failures_without_loading_inference() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        manager = FakeKokoroModelManager(Path(temp_dir_name))
        manager.state = "not-installed"
        loader_calls = 0

        def missing_loader():
            nonlocal loader_calls
            loader_calls += 1
            raise ImportError("missing sherpa")

        runtime = kokoro.KokoroRuntime(manager, sherpa_loader=missing_loader, schedule_idle_release=False)
        assert runtime.status()["state"] == "model-not-installed"
        try:
            runtime.synthesize("测试", "zh-CN", "auto", 1.0, Path(temp_dir_name) / "voice.wav")
        except kokoro.KokoroRuntimeError as error:
            assert "model" in str(error).lower()
        else:
            raise AssertionError("missing model must remain an explicit Kokoro error")
        assert loader_calls == 0

    with tempfile.TemporaryDirectory() as temp_dir_name:
        fake_sherpa = FakeSherpaRuntime()
        fake_sherpa.__version__ = "1.12.0"
        runtime = kokoro.KokoroRuntime(
            FakeKokoroModelManager(Path(temp_dir_name)),
            sherpa_loader=lambda: fake_sherpa,
            schedule_idle_release=False,
        )
        try:
            runtime.synthesize("测试", "zh-CN", "auto", 1.0, Path(temp_dir_name) / "voice.wav")
        except kokoro.KokoroRuntimeError as error:
            assert "requires sherpa-onnx" in str(error)
        else:
            raise AssertionError("incompatible runtimes must return a Kokoro error")
        assert runtime.status()["state"] == "runtime-incompatible"


def test_runtime_lock_allows_only_one_kokoro_job() -> None:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        started = threading.Event()
        release = threading.Event()
        active = 0
        peak = 0
        active_lock = threading.Lock()

        class BlockingSherpa(FakeSherpaRuntime):
            def __init__(self):
                super().__init__()
                original_tts = self.OfflineTts

                outer = self

                class OfflineTts(original_tts):
                    def generate(inner, *, text, sid, speed):
                        nonlocal active, peak
                        with active_lock:
                            active += 1
                            peak = max(peak, active)
                        try:
                            started.set()
                            release.wait(2)
                            return super(OfflineTts, inner).generate(text=text, sid=sid, speed=speed)
                        finally:
                            with active_lock:
                                active -= 1

                self.OfflineTts = OfflineTts

        fake_sherpa = BlockingSherpa()
        runtime = kokoro.KokoroRuntime(
            FakeKokoroModelManager(Path(temp_dir_name)),
            sherpa_loader=lambda: fake_sherpa,
            schedule_idle_release=False,
        )
        errors: list[Exception] = []

        def worker(index):
            try:
                runtime.synthesize("测试", "zh-CN", "auto", 1.0, Path(temp_dir_name) / f"voice-{index}.wav")
            except Exception as error:  # pragma: no cover - test assertion below.
                errors.append(error)

        first = threading.Thread(target=worker, args=(1,))
        second = threading.Thread(target=worker, args=(2,))
        first.start()
        assert started.wait(1)
        second.start()
        time.sleep(0.05)
        assert peak == 1
        release.set()
        first.join(2)
        second.join(2)
        assert not errors
        assert peak == 1


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
    test_protocol_status_schema_and_async_install_reuse()
    test_cancel_or_uninstall_cleans_up_late_activation()
    test_http_model_routes_allow_only_empty_objects()
    test_complete_kokoro_voice_catalog_has_stable_provider_ids()
    test_kokoro_runtime_is_lazy_uses_two_threads_and_releases_after_idle()
    test_kokoro_voice_failure_retries_once_then_uses_one_same_provider_fallback()
    test_kokoro_rejects_empty_or_non_finite_output_without_cross_provider_fallback()
    test_kokoro_runtime_reports_model_and_runtime_failures_without_loading_inference()
    test_runtime_lock_allows_only_one_kokoro_job()
    print("kokoro engine checks ok")


if __name__ == "__main__":
    main()
