#!/usr/bin/env python3
"""Check updater lifecycle boundaries without downloading or replacing an Engine."""
from __future__ import annotations

import threading
import json
import tempfile
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from verify_local_engine import load_native_host_module, load_server_module


def main() -> None:
    server = load_server_module()
    status = {"enabled": True, "status": "ready", "availableVersion": "99.0.0"}
    calls = []
    updates = SimpleNamespace(
        get_update_status=lambda _root: status,
        is_check_running=lambda: False,
        has_native_work=lambda _root: False,
        start_background_check=lambda _root: calls.append("check"),
        begin_install_if_ready=lambda _root, _pid, _guard: calls.append("handoff") or True,
        installation_in_progress=lambda _root: True,
        native_work_lease=lambda _root: nullcontext(False),
    )
    with patch.object(server, "engine_updates", updates, create=True), \
         patch.object(server, "get_runtime_health", return_value={}):
        assert server.build_health_payload("native").get("updates") == status, \
            "passive health must expose the updater state"
        assert not calls, "passive health must never check or install updates"
        server.ENGINE_LAST_ACTIVITY = server.time.monotonic() - server.ENGINE_IDLE_SECONDS - 1
        updates.is_check_running = lambda: True
        assert not server.engine_is_idle(), "an active verified download must keep its owner alive"
        updates.is_check_running = lambda: False

        stopped, closed = threading.Event(), threading.Event()
        class HTTPServer:
            def serve_forever(self, **_kwargs):
                assert stopped.wait(3)

            def shutdown(self):
                assert calls == ["check", "handoff"], "mark update handoff before closing the listener"
                server.DUB_TRACK_CANCEL_EVENTS["accepted-at-idle-boundary"] = threading.Event()
                stopped.set()

            def server_close(self):
                closed.set()

        with patch.object(server, "LocalDubServer", return_value=HTTPServer()), \
             patch.object(server, "restore_completed_dub_tracks"), \
             patch.object(server, "ENGINE_IDLE_SECONDS", 0.1), \
             patch.object(server, "engine_is_idle", return_value=True):
            owner = threading.Thread(target=server.main)
            owner.start()
            try:
                assert stopped.wait(2)
                assert not closed.wait(0.1), "accepted jobs must drain before installer can replace the old process"
            finally:
                server.DUB_TRACK_CANCEL_EVENTS.clear()
                owner.join(3)
            assert closed.is_set() and not owner.is_alive()

    native = load_native_host_module()
    with patch.object(native, "engine_updates", updates, create=True), \
         patch.object(native, "start_http_engine", side_effect=AssertionError("work started during installation")), \
         patch.object(native, "build_health_payload", return_value={"ok": True, "updates": status}):
        assert native.handle_message({"type": "health"})["ok"]
        for operation in ("start-http", "restart-http", "tts", "install-whisper", "repair-autostart"):
            response = native.handle_message({"type": operation})
            assert response.get("code") == "ENGINE_UPDATING", operation
            assert not response["ok"]
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "engine-runtime"
        root.mkdir()
        (root / "release.json").write_text(json.dumps(dict(version="0.2.8", protocolVersion=2,
            platform="macos", architecture="arm64", autoUpdate=True, bundledRuntime=True)))
        owner_starts = []
        def direct_tts(*_args, **_kwargs):
            assert native.engine_updates.has_native_work(root), "direct Native TTS has no cross-process work lease"
            assert server.engine_has_work(), "HTTP owner ignores active Native work"
            return {"ok": True}
        with patch.object(native, "PROJECT_ROOT", root), patch.object(server, "ENGINE_ROOT", root), \
             patch.object(native, "start_http_engine", side_effect=lambda: owner_starts.append(True) or {"ok": True}), \
             patch.object(native, "build_tts_payload", direct_tts), \
             patch.object(native, "build_health_payload", return_value={"ok": True}):
            assert native.handle_message({"type": "health"})["ok"]
            assert not owner_starts, "passive Native health woke the update owner"
            assert native.handle_message({"type": "tts", "payload": {}})["ok"]
            assert owner_starts == [True], "direct Native use never starts the update owner"
            assert not native.engine_updates.has_native_work(root), "Native work lease leaked after completion"
        server.ENGINE_ACTIVE_WORK = 1
        try:
            with server.update_handoff_guard() as allowed:
                assert not allowed and server.ENGINE_ACCEPTING_WORK, "late HTTP work must postpone the update"
        finally:
            server.ENGINE_ACTIVE_WORK = 0
        server.ENGINE_LAST_ACTIVITY = server.time.monotonic() - server.ENGINE_IDLE_SECONDS - 1
        try:
            with server.update_handoff_guard() as allowed:
                assert allowed and not server.ENGINE_ACCEPTING_WORK
                raise OSError("helper launch failed")
        except OSError:
            pass
        assert server.ENGINE_ACCEPTING_WORK, "failed helper launch permanently closed HTTP admission"
    print("Automatic update integration checks passed: passive state, busy guard, drained handoff, Native exclusion.")


if __name__ == "__main__":
    main()
