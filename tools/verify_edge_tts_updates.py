#!/usr/bin/env python3
"""Offline regression checks for guarded speech-client updates and playback fallback."""
from contextlib import ExitStack, nullcontext
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch
import wave
import zipfile

from verify_local_engine import load_server_module


def rejects(call):
    try:
        call()
    except (ValueError, RuntimeError):
        return
    raise AssertionError("unsafe candidate was accepted")


def make_wheel(path, version="7.3.1", metadata="", extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        for name in ("edge_tts/__init__.py", "edge_tts/__main__.py", "edge_playback/__init__.py"):
            archive.writestr(name, "")
        archive.writestr(f"edge_tts-{version}.dist-info/METADATA",
                         f"Name: edge-tts\nVersion: {version}\n" + metadata)
        if extra:
            archive.writestr(*extra)
    return {"version": version, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}


def verify_updates(server, root):
    updates = server.edge_tts_updates
    helpers = server.engine_updates
    runtime = root / "runtime"
    runtime.mkdir()
    (runtime / "release.json").write_text(json.dumps({"autoUpdate": True, "bundledRuntime": True,
                                                    "platform": "macos", "architecture": "arm64"}))
    updater = updates.EdgeTtsUpdater(runtime, helpers)
    source = root / "source.whl"
    record = make_wheel(source)
    document = {"info": {"name": "edge-tts", "version": "7.3.1"}, "urls": [{
        "filename": "edge_tts-7.3.1-py3-none-any.whl", "packagetype": "bdist_wheel", "yanked": False,
        "url": "https://files.pythonhosted.org/packages/test.whl", "digests": {"sha256": record["sha256"]},
        "size": record["size"]}]}
    downloads = []

    def download(url, path, limit):
        updates.validate_url(url)
        downloads.append(url)
        path.write_bytes(json.dumps(document).encode() if url == updates.INDEX_URL else source.read_bytes())

    def smoke(command, **kwargs):
        assert kwargs["timeout"] <= 30
        if "--write-media" in command:
            assert command[command.index("--text") + 1] == "语音连接测试。"
            Path(command[-1]).write_bytes(b"audio" * 300)
        return subprocess.CompletedProcess(command, 0)

    with patch.object(updates, "bundled_version", return_value="7.2.8"), patch.dict(os.environ, {"LOCAL_DUB_AUTO_UPDATE": "1"}):
        updates.validate_wheel(source, record)
        for url in ("http://pypi.org/pypi/edge-tts/json", "https://pypi.org/pypi/another/json",
                    "https://files.pythonhosted.org.evil/packages/a", "https://user@files.pythonhosted.org/packages/a",
                    "https://files.pythonhosted.org/packages/a?token=x", "https://files.pythonhosted.org:444/packages/a"):
            rejects(lambda: updates.validate_url(url))
        rejects(lambda: updates.validate_wheel(source, {**record, "sha256": "0" * 64}))
        invalid = root / "invalid.whl"
        for metadata, extra in (("", ("../escape.py", "")), ("", ("sitecustomize.py", "")),
                                ("Requires-Python: >=99\n", None), ("Requires-Dist: pip>=999\n", None),
                                ("Requires-Dist: pip @ https://example.org/pip.whl\n", None)):
            bad = make_wheel(invalid, metadata=metadata, extra=extra)
            rejects(lambda: updates.validate_wheel(invalid, bad))
        bad = make_wheel(invalid, version="7.3.2")
        rejects(lambda: updates.validate_wheel(invalid, {**bad, "version": "7.3.1"}))
        with patch.object(updates, "download", side_effect=download), patch.object(updates.subprocess, "run", side_effect=smoke):
            updater.check()
            assert updater.status()["status"] == "updated", updater.status()
            assert updater.choices() == [record]
            assert updater.path_for(record).read_bytes() == source.read_bytes()
            updater.check()
            assert len(downloads) == 2, "six-hour throttle failed"
            other = updates.EdgeTtsUpdater(runtime, helpers)
            state = updater.read_state()
            state["checkedAt"] = 0
            updater.write_state(state)
            with helpers.update_lock(runtime, "edge-tts-check.lock") as held:
                assert held
                other.check()
            assert len(downloads) == 2, "second checker bypassed process lock"
            document["info"]["version"] = "7.3.2"
            next_record = make_wheel(source, "7.3.2")
            document["urls"][0].update(filename="edge_tts-7.3.2-py3-none-any.whl", size=next_record["size"],
                                        digests={"sha256": next_record["sha256"]})
            for failure in ("download", "synthesis", "decode"):
                updater.write_state({"active": record, "checkedAt": 0})
                def failing_smoke(command, **kwargs):
                    if (failure == "synthesis" and "--write-media" in command or
                            failure == "decode" and "--write-media" not in command):
                        raise subprocess.CalledProcessError(1, command)
                    return smoke(command, **kwargs)
                with ExitStack() as stack:
                    stack.enter_context(patch.object(updates.subprocess, "run", side_effect=failing_smoke))
                    if failure == "download":
                        stack.enter_context(patch.object(updates, "download", side_effect=TimeoutError("offline")))
                    updater.check()
                assert updater.read_state()["active"] == record
                assert updater.status()["status"] == "failed"
                assert not updater.path_for(next_record).exists()
            updater.write_state({"active": record, "checkedAt": 0})
            updater.check()
            assert updater.choices() == [next_record, record]
            updater.rollback(record)
            assert updater.choices()[0] == next_record, "stale failure replaced newer active wheel"
            updater.rollback(next_record)
            assert updater.choices() == [record]
            assert updater.read_state()["failedVersion"] == "7.3.2"
            saved = updater.read_state()
            with patch.object(helpers, "update_lock", return_value=nullcontext(False)):
                updater.rollback(record)
            assert updater.read_state() == saved, "rollback wrote without owning its state lock"
            updater.write_state({**updater.read_state(), "checkedAt": 0})
            updater.check()
            assert updater.choices() == [record], "known failed version was retried"
        with patch.object(updates, "bundled_version", return_value="7.3.1"):
            assert updater.choices() == [], "bundle must supersede equal/older override"
        updater.path_for(record).write_bytes(b"corrupt")
        assert updater.choices() == [], "tampered installed wheel remained executable"
        with patch.dict(os.environ, {"LOCAL_DUB_AUTO_UPDATE": "0"}), patch.object(updater, "check") as check:
            updater.start_check()
            assert not check.called and updater.choices() == []
        assert not helpers.has_native_work(runtime), "HTTP checker must not leave native PID leases"


def verify_playback(server, root):
    updater = server.EDGE_TTS_UPDATER
    candidate = {"version": "7.3.1", "sha256": "1" * 64, "size": 1}
    calls = []
    def command(cmd, timeout, cancel_event):
        calls.append(cmd)
        if cmd[0] == "candidate":
            return subprocess.CompletedProcess(cmd, 1, "", "upstream failure")
        if cmd[0] == "bundled":
            Path(cmd[-1]).write_bytes(b"audio")
        else:
            with wave.open(cmd[-1], "wb") as audio:
                audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\x00\x10" * 24000)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    with (patch.object(server, "find_edge_tts_command", return_value=["bundled"]),
          patch.object(server, "find_ffmpeg_command", return_value="ffmpeg"),
          patch.object(updater, "choices", return_value=[candidate]),
          patch.object(server.edge_tts_updates, "wheel_command", return_value=["candidate"]),
          patch.object(server, "run_cancellable_command", side_effect=command),
          patch.object(updater, "rollback") as rollback):
        result = server.synthesize_edge_speech_to_wav_file("-测试", "zh-CN", 1, "auto", 0, root / "audio")
        assert result["duration"] == 1
        assert [c[0] for c in calls] == ["candidate", "bundled", "ffmpeg"]
        assert all("--text=-测试" in cmd and "--text" not in cmd for cmd in calls[:2])
        rollback.assert_called_once_with(candidate)
        rollback.reset_mock()
        with patch.object(updater, "rollback", side_effect=OSError("disk full")):
            result = server.synthesize_edge_speech_to_wav_file("测试", "zh-CN", 1, "auto", 0, root / "state-error")
            assert result["duration"] == 1, "state write failure discarded valid fallback audio"
        with patch.object(server, "run_cancellable_command", side_effect=TimeoutError("offline")) as runner:
            try:
                server.synthesize_edge_speech_to_wav_file("测试", "zh-CN", 1, "auto", 0, root / "offline")
            except TimeoutError:
                pass
            else:
                raise AssertionError("total outage was hidden")
            assert runner.call_count == 2 and not rollback.called
        with patch.object(server, "run_cancellable_command", side_effect=server.FullTranscriptCancelled("cancel")) as runner:
            try:
                server.synthesize_edge_speech_to_wav_file("测试", "zh-CN", 1, "auto", 0, root / "cancel")
            except server.FullTranscriptCancelled:
                pass
            else:
                raise AssertionError("cancellation was swallowed")
            assert runner.call_count == 1 and not rollback.called
    with (patch.object(updater, "start_check") as check,
          patch.object(server, "synthesize_speech_with_system", return_value={"engine": "test", "mimeType": "audio/wav", "dataUrl": "data:"})):
        server.build_health_payload("http")
        server.build_tts_payload({"text": "a", "ttsEngine": "edge"}, "native")
        server.build_tts_payload({"text": "a", "ttsEngine": "system"}, "http")
        server.build_tts_payload({"text": "", "ttsEngine": "edge"}, "http")
        assert not check.called
        assert server.build_tts_payload({"text": "a", "ttsEngine": "edge"}, "http")["ok"]
        check.assert_called_once()
    with patch.object(updater, "is_check_running", return_value=True):
        assert server.engine_has_work(), "updater must protect HTTP Engine from idle shutdown"


def main():
    server = load_server_module()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        verify_updates(server, root)
        verify_playback(server, root)
    print("Edge speech update checks passed: integrity, compatibility, activation, throttle, locks, rollback, cancellation, triggers")


if __name__ == "__main__":
    main()
