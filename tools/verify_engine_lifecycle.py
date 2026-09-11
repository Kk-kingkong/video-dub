#!/usr/bin/env python3
"""Small isolated checks for Engine sleep, work protection, and on-demand startup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from unittest.mock import patch

from verify_local_engine import ROOT, load_native_host_module, load_server_module


def check_idle_exit() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryFile(mode="w+") as log:
        env = {**os.environ, "LOCAL_DUB_PORT": str(port), "LOCAL_DUB_ENGINE_IDLE_SECONDS": "2",
               "LOCAL_DUB_AUTO_UPDATE": "0",
               "LOCAL_DUB_OLLAMA_HEALTH_TIMEOUT": "0.01", "LOCAL_DUB_DATA_DIR": temporary,
               "LOCAL_DUB_CACHE_DIR": temporary}
        command = [sys.executable, "-u", "-c",
                   "import faulthandler, runpy, sys; faulthandler.dump_traceback_later(8); "
                   "runpy.run_path(sys.argv[1], run_name='__main__')",
                   str(ROOT / "server/local_dub_server.py")]
        process = subprocess.Popen(command,
                                   env=env, stdout=log, stderr=log)
        healthy = False
        deadline = time.monotonic() + 20
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        last_error = ""
        try:
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        healthy = json.load(response)["ok"] or healthy
                except OSError as error:
                    last_error = str(error)
                time.sleep(0.03)
            log.seek(0)
            diagnostic = f"exit={process.poll()}, request={last_error}\n{log.read()[-4000:]}"
            assert healthy, f"isolated Engine never became healthy: {diagnostic}"
            assert process.poll() == 0, f"health polling prevented the idle Engine from exiting: {diagnostic}"
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)


def check_busy_work() -> None:
    server = load_server_module()
    with patch.object(server.time, "monotonic", return_value=1000):
        server.ENGINE_LAST_ACTIVITY = 0
        assert server.engine_is_idle()
        with server.engine_activity():
            assert not server.engine_is_idle(), "active work must prevent idle exit"
            with server.engine_activity():
                assert server.ENGINE_ACTIVE_WORK == 2
        assert server.ENGINE_ACTIVE_WORK == 0
        assert not server.engine_is_idle(), "completed work must receive a fresh idle grace period"

    started, finish = threading.Event(), threading.Event()

    class InstallingModel:
        def install(self):
            started.set()
            assert finish.wait(3)

        def uninstall(self):
            pass

    service = server.KokoroModelService(InstallingModel())
    worker = threading.Thread(target=service._run_install, args=(0,))
    worker.start()
    try:
        assert started.wait(2)
        with patch.object(server.time, "monotonic", return_value=10000):
            assert not server.engine_is_idle(), "an in-progress model download must prevent idle exit"
    finally:
        finish.set()
        worker.join(timeout=3)

    server.ENGINE_LAST_ACTIVITY = 0
    received, finish = threading.Event(), threading.Event()
    failures = []

    def request_tts(port):
        try:
            request = urllib.request.Request(f"http://127.0.0.1:{port}/api/tts", data=b"{}", method="POST")
            with urllib.request.urlopen(request, timeout=3) as response:
                assert json.load(response)["ok"]
        except Exception as error:
            failures.append(error)

    def delayed_tts(*_args, **_kwargs):
        received.set()
        assert finish.wait(3)
        return {"ok": True}

    with patch("socket.getfqdn", side_effect=AssertionError("loopback binding must not wait for reverse DNS")), \
         server.LocalDubServer(("127.0.0.1", 0), server.LocalDubHandler) as http_server, \
         patch.object(server, "build_tts_payload", delayed_tts):
        handler = threading.Thread(target=http_server.handle_request)
        handler.start()
        client = threading.Thread(target=request_tts, args=(http_server.server_address[1],))
        client.start()
        try:
            assert received.wait(2)
            assert not server.engine_is_idle(), "HTTP/TTS work must prevent idle exit"
        finally:
            finish.set()
            client.join(timeout=3)
            handler.join(timeout=3)
    assert not failures, failures
    assert not server.engine_is_idle(), "HTTP work completion must refresh the idle timeout"


def check_passive_native_model_status() -> None:
    native = load_native_host_module()
    with patch.object(native, "http_engine_running", return_value=False), \
         patch.object(native, "start_http_engine", side_effect=AssertionError("passive status woke Engine")):
        response = native.handle_message({"type": "kokoro-model-status"})
    assert response["ok"] and isinstance(response["model"], dict)


def check_idle_shutdown_drains_queued_work() -> None:
    server = load_server_module()
    shutdown, closed = threading.Event(), threading.Event()

    class BoundaryServer:
        def serve_forever(self, **_kwargs):
            assert shutdown.wait(3)

        def shutdown(self):
            # A request was accepted after the idle decision and queued work
            # before the HTTP loop stopped accepting connections.
            server.DUB_TRACK_CANCEL_EVENTS["queued-at-shutdown"] = threading.Event()
            shutdown.set()

        def server_close(self):
            closed.set()

    with tempfile.TemporaryDirectory() as temporary, \
         patch.object(server, "DUB_TRACK_OUTPUT_DIR", Path(temporary)), \
         patch.object(server, "LocalDubServer", return_value=BoundaryServer()), \
         patch.object(server, "ENGINE_IDLE_SECONDS", 0.1), \
         patch.object(server, "engine_is_idle", return_value=True):
        main = threading.Thread(target=server.main)
        main.start()
        try:
            assert shutdown.wait(2)
            assert not closed.wait(0.2), "idle shutdown exited before queued work acquired its active counter"
        finally:
            server.DUB_TRACK_CANCEL_EVENTS.clear()
            main.join(timeout=3)
        assert not main.is_alive() and closed.is_set()


def check_macos_on_demand_registration() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "package"
        for name in ("scripts/install_engine_autostart_macos.sh", "scripts/uninstall_engine_autostart_macos.sh",
                     "companion/install_native_host_macos.sh", "companion/native_host_launcher_macos.sh",
                     "companion/native_host.py", "server/local_dub_server.py", "server/kokoro_tts.py",
                     "server/engine_updates.py", "server/update-signing-cert.cer"):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        (root / ".venv/bin").mkdir(parents=True)
        (root / ".venv/bin/python").symlink_to(sys.executable)
        fake_bin = root / "fake-bin"
        fake_bin.mkdir()
        launchctl = fake_bin / "launchctl"
        launchctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$LOCAL_DUB_TEST_LAUNCHCTL_LOG"\n')
        launchctl.chmod(0o755)
        plist, manifest, log = root / "legacy.plist", root / "native.json", root / "launchctl.log"
        env = {**os.environ, "LOCAL_DUB_RUNTIME_DIR": str(root), "LOCAL_DUB_PYTHON": sys.executable,
               "LOCAL_DUB_LAUNCH_AGENT_PATH": str(plist), "LOCAL_DUB_NATIVE_MANIFEST_PATH": str(manifest),
               "LOCAL_DUB_TEST_LAUNCHCTL_LOG": str(log), "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]}
        for upgrading in (False, True):
            if upgrading:
                plist.write_text("legacy login-start registration")
            subprocess.run([str(root / "companion/install_native_host_macos.sh"), "a" * 32],
                           env=env, check=True, capture_output=True, text=True, timeout=15)
            assert not plist.exists(), "install/upgrade left HTTP Engine registered at login"
            native = json.loads(manifest.read_text())
            assert native["allowed_origins"] == ["chrome-extension://" + "a" * 32 + "/"]
            assert Path(native["path"]) == (root / "companion/native_host_launcher_macos.sh").resolve()
        assert "bootout" in log.read_text()
        assert "bootstrap" not in log.read_text() and "kickstart" not in log.read_text()

        python_trap = Path(temporary) / "no-system-python"
        python_trap.mkdir()
        trap_script = python_trap / "python3"
        trap_script.write_text('#!/bin/sh\necho "System Python must not be needed for Native registration" >&2\nexit 37\n')
        trap_script.chmod(0o755)
        repaired = subprocess.run([str(root / "companion/install_native_host_macos.sh"), "b" * 32],
                                  env={**env, "PATH": str(python_trap) + os.pathsep + env["PATH"]},
                                  capture_output=True, text=True, timeout=15)
        assert repaired.returncode == 0, repaired.stdout + repaired.stderr
        assert json.loads(manifest.read_text())["allowed_origins"] == [
            "chrome-extension://" + identifier * 32 + "/" for identifier in "ab"], \
            "manual repair removed a previously approved extension"

        # Exercise the customer entry point, including re-registration for an unpacked ZIP.
        installer = root / "Install LocalTube Dub Engine.command"
        installer.write_text((ROOT / "packaging/macos/Install LocalTube Dub Engine.command.in")
                             .read_text().replace("__EXTENSION_ID__", "a" * 32)
                             .replace("__VERSION__", "test"))
        installer.chmod(0o755)
        deps = root / "scripts/install_engine_deps_macos.sh"
        deps.write_text("#!/bin/sh\nexit 0\n")
        deps.chmod(0o755)
        installed = Path(temporary) / "installed"
        env.update(LOCAL_DUB_INSTALL_DRY_RUN="1", LOCAL_DUB_RUNTIME_DIR=str(installed))
        for arguments, expected_ids in (([], "a"), (["b" * 32], "ab"), ([], "ab")):
            subprocess.run([str(installer), *arguments], env=env, check=True,
                           capture_output=True, text=True, timeout=15)
            assert json.loads(manifest.read_text())["allowed_origins"] == [
                f"chrome-extension://{identifier * 32}/" for identifier in expected_ids], \
                "manual migration removed existing bindings or ignored the requested extension ID"
        owned = json.loads(manifest.read_text())
        for untrusted in ({**owned, "allowed_origins": ["chrome-extension://*/"]},
                          {**owned, "name": "other.host"},
                          {**owned, "type": "other"},
                          {**owned, "path": str(root / "foreign-launcher")}):
            manifest.write_text(json.dumps(untrusted))
            subprocess.run([str(installer)], env=env, check=True, capture_output=True, text=True, timeout=15)
            assert json.loads(manifest.read_text())["allowed_origins"] == ["chrome-extension://" + "a" * 32 + "/"], \
                "manual migration trusted invalid or foreign extension bindings"
        unchanged = manifest.read_bytes()
        marker = installed / "keep.txt"
        marker.write_text("previous runtime")
        for invalid_id in ("", "A" * 32, "a" * 31, "a" * 33, "a" * 31 + "q", "a" * 32 + "\n", "*"):
            failed = subprocess.run([str(installer), invalid_id], env=env,
                                    capture_output=True, text=True, timeout=15)
            assert failed.returncode != 0, "release installer accepted an invalid extension ID"
            assert manifest.read_bytes() == unchanged and marker.read_text() == "previous runtime", \
                "invalid extension ID modified the existing installation"


def check_macos_unattended_update() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        package, installed = root / "package", root / "installed"
        shutil.copytree(ROOT / "server", package / "server", ignore=shutil.ignore_patterns("__pycache__"))
        (package / "companion").mkdir()
        (package / "companion/native_host_launcher_macos.sh").write_text("#!/bin/sh\nexit 0\n")
        (package / "scripts").mkdir()
        deps = package / "scripts/install_engine_deps_macos.sh"
        deps.write_text("#!/bin/sh\nexit 0\n")
        deps.chmod(0o755)
        (package / ".venv/bin").mkdir(parents=True)
        (package / ".venv/bin/python").symlink_to(sys.executable)
        release = package / "release.json"
        release.write_text(json.dumps({"version": "0.2.8", "protocolVersion": 2}))
        installer = package / "Install LocalTube Dub Engine.command"
        installer.write_text((ROOT / "packaging/macos/Install LocalTube Dub Engine.command.in")
                             .read_text().replace("__EXTENSION_ID__", "a" * 32)
                             .replace("__VERSION__", "0.2.8"))
        installer.chmod(0o755)
        shutil.copytree(package, installed, symlinks=True)
        (installed / "keep.txt").write_text("old runtime")
        model = root / "models/keep.bin"
        model.parent.mkdir()
        model.write_bytes(b"downloaded model")
        settings = root / "settings.json"
        settings.write_bytes(b'{"voice":"saved"}')
        manifest = root / "native.json"
        native = {"name": "com.localtube.dub.engine", "type": "stdio",
                  "path": str(installed / "companion/native_host_launcher_macos.sh"),
                  "allowed_origins": ["chrome-extension://" + identifier * 32 + "/" for identifier in "ab"]}
        manifest.write_text(json.dumps(native, indent=3) + "\n")
        preserved = manifest.read_bytes()
        env = {**os.environ, "LOCAL_DUB_RUNTIME_DIR": str(installed), "LOCAL_DUB_UPDATE_INSTALL": "1",
               "LOCAL_DUB_AUTO_UPDATE": "0", "LOCAL_DUB_NATIVE_MANIFEST_PATH": str(manifest),
               "LOCAL_DUB_DATA_DIR": str(root / "data"), "LOCAL_DUB_CACHE_DIR": str(root / "cache"),
               "LOCAL_DUB_OLLAMA_HEALTH_TIMEOUT": "0.01"}

        def install(extra_env=None):
            return subprocess.run([str(installer)], env={**env, **(extra_env or {})},
                                  stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=45)

        for malformed in ({**native, "allowed_origins": ["chrome-extension://*/"]},
                          {**native, "path": str(root / "foreign-launcher")},
                          {**native, "type": "other"}):
            manifest.write_text(json.dumps(malformed))
            before = manifest.read_bytes()
            result = install()
            assert result.returncode != 0, "automatic install accepted an unowned Native manifest"
            assert manifest.read_bytes() == before and (installed / "keep.txt").is_file()
        manifest.unlink()
        assert install().returncode != 0 and (installed / "keep.txt").is_file(), "missing registration was silently recreated"
        manifest.write_bytes(preserved)

        for failure in ("injected", "wrong-version"):
            release.write_text(json.dumps({"version": "0.2.9" if failure == "wrong-version" else "0.2.8",
                                           "protocolVersion": 2}))
            result = install({"LOCAL_DUB_INSTALL_FAIL_AFTER_MOVE": "1"} if failure == "injected" else {})
            assert result.returncode != 0, "unhealthy automatic upgrade unexpectedly succeeded"
            assert manifest.read_bytes() == preserved and (installed / "keep.txt").read_text() == "old runtime", \
                "failed automatic upgrade lost prior runtime or Native bindings"
        release.write_text(json.dumps({"version": "0.2.8", "protocolVersion": 2}))
        result = install()
        assert result.returncode == 0, result.stdout + result.stderr
        assert not (installed / "keep.txt").exists(), "automatic install did not activate new runtime"
        assert manifest.read_bytes() == preserved, "automatic install changed Native bindings"
        assert settings.read_bytes() == b'{"voice":"saved"}' and model.read_bytes() == b"downloaded model"
        assert not list(root.glob("installed.backup.*")) and not list(root.glob("installed.staging.*"))


if __name__ == "__main__":
    check_idle_exit()
    check_busy_work()
    check_passive_native_model_status()
    check_idle_shutdown_drains_queued_work()
    if sys.platform == "darwin":
        check_macos_on_demand_registration()
        check_macos_unattended_update()
    print("Engine lifecycle checks passed")
