#!/usr/bin/env python3
"""Offline security and lifecycle checks for the signed Engine updater."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from unittest.mock import patch

from sign_engine_update import MANIFEST_NAME, SIGNATURE_NAME

ROOT = Path(__file__).resolve().parents[1]


def rejected(action):
    try:
        action()
    except (ValueError, RuntimeError, OSError, zipfile.BadZipFile):
        return
    raise AssertionError("unsafe update was accepted")


def main():
    path = ROOT / "server/engine_updates.py"
    assert path.is_file(), "signed Engine updater has not been implemented"
    spec = importlib.util.spec_from_file_location("engine_updates", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.MANIFEST_URL.rsplit("/", 1)[-1] == MANIFEST_NAME
    assert module.SIGNATURE_URL.rsplit("/", 1)[-1] == SIGNATURE_NAME, "updater requests a signature filename that publication never creates"
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        runtime = base / "product/engine-runtime"
        runtime.mkdir(parents=True)
        platform, arch = ("windows", "x64") if os.name == "nt" else ("macos", "arm64")
        release = dict(version="0.2.7", protocolVersion=2, platform=platform,
                       architecture=arch, bundledRuntime=True, autoUpdate=True)
        (runtime / "release.json").write_text(json.dumps(release))
        (runtime / "keep.txt").write_text("old runtime remains usable")
        name = f"LocalTube-Dub-Engine-v0.2.8-{'Windows' if platform == 'windows' else 'macOS'}-{arch}"
        archive = base / "package.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr(name + "/release.json", json.dumps({**release, "version": "0.2.8"}))
            output.writestr(name + "/.venv/" + ("python.exe" if os.name == "nt" else "bin/python"), b"fake test Python")
            output.writestr(name + "/" + ("install-engine.ps1" if os.name == "nt" else "Install LocalTube Dub Engine.command"), "exit 1")
        package = dict(platform=platform, architecture=arch,
                       url=f"https://github.com/Kk-kingkong/video-dub/releases/download/v0.2.8/{name}.zip",
                       size=archive.stat().st_size, sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
        manifest = dict(schemaVersion=1, channel="stable", version="0.2.8", protocolVersion=2,
                        packages=[package])
        manifest_path, signature, certificate = base / "update.json", base / "update.sig", base / "cert.cer"
        manifest_path.write_bytes(json.dumps(manifest).encode())
        env = {**os.environ, "UPDATE_TEST_DIR": str(base)}
        if os.name == "nt":
            script = """$ErrorActionPreference='Stop'; $d=$env:UPDATE_TEST_DIR;
            $rsa=[System.Security.Cryptography.RSA]::Create(2048);
            $request=[System.Security.Cryptography.X509Certificates.CertificateRequest]::new('CN=Updater test',$rsa,[System.Security.Cryptography.HashAlgorithmName]::SHA256,[System.Security.Cryptography.RSASignaturePadding]::Pkcs1);
            $cert=$request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddDays(-1),[DateTimeOffset]::UtcNow.AddDays(1));
            [IO.File]::WriteAllBytes((Join-Path $d 'cert.cer'),$cert.Export([System.Security.Cryptography.X509Certificates.X509ContentType]::Cert));
            [IO.File]::WriteAllBytes((Join-Path $d 'update.sig'),$rsa.SignData([IO.File]::ReadAllBytes((Join-Path $d 'update.json')),[System.Security.Cryptography.HashAlgorithmName]::SHA256,[System.Security.Cryptography.RSASignaturePadding]::Pkcs1));"""
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], env=env, check=True, capture_output=True)
        else:
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=Updater test", "-days", "1",
                            "-keyout", str(base / "private.pem"), "-outform", "DER", "-out", str(certificate)], check=True, capture_output=True)
            subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(base / "private.pem"), "-out", str(signature), str(manifest_path)], check=True, capture_output=True)
        with patch.object(module, "CERTIFICATE", certificate):
            module.verify_signature(manifest_path, signature)
            original = manifest_path.read_bytes()
            manifest_path.write_bytes(original + b" ")
            rejected(lambda: module.verify_signature(manifest_path, signature))
            manifest_path.write_bytes(original)
            assert module.select_package(manifest, release) == package
            for changes in ({"channel": "beta"}, {"protocolVersion": 3}, {"version": "0.2.8-rc1"}, {"version": "0.2.6"}):
                rejected(lambda changes=changes: module.select_package({**manifest, **changes}, release))
            for changes in ({"url": "https://attacker.invalid/package.zip"}, {"url": package["url"].replace("v0.2.8/", "v9.0.0/")},
                            {"size": 513 * 1024 ** 2}, {"sha256": "oops"}, {"platform": "linux"}):
                rejected(lambda changes=changes: module.select_package({**manifest, "packages": [{**package, **changes}]}, release))
            assert module.select_package({**manifest, "version": "0.2.7"}, release) is None
            module.check_archive(archive, package)
            rejected(lambda: module.check_archive(archive, {**package, "sha256": "0" * 64}))
            for url in ("http://github.com/Kk-kingkong/video-dub/releases/latest", "https://github.com/Kk-kingkong/video-dub/releases/../../elsewhere", "https://evil.invalid/github-production-release-asset/a", "https://user@github.com/Kk-kingkong/video-dub/releases/a"):
                rejected(lambda url=url: module.validate_download_url(url))
            module.extract_package(archive, base / "safe", name)
            for entries in ([name + "/../../escape"], [name + "/safe", name + "/SAFE"], [name + "/safe", "other/file"], [name + "/C:bad"], [name + "/CON"]):
                bad = base / "bad.zip"
                with zipfile.ZipFile(bad, "w") as output:
                    for entry in entries:
                        output.writestr(entry, b"bad")
                rejected(lambda: module.extract_package(bad, base / "bad-output", name))
                shutil.rmtree(base / "bad-output", ignore_errors=True)
            with zipfile.ZipFile(base / "links.zip", "w") as output:
                info = zipfile.ZipInfo(name + "/evil")
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                output.writestr(info, "../../escape")
            rejected(lambda: module.extract_package(base / "links.zip", base / "links", name))
            if os.name != "nt":
                with zipfile.ZipFile(base / "valid-links.zip", "w") as output:
                    output.writestr(name + "/bin/python3", b"python")
                    info = zipfile.ZipInfo(name + "/bin/python")
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    output.writestr(info, "python3")
                extracted = module.extract_package(base / "valid-links.zip", base / "valid-links", name)
                assert (extracted / "bin/python").read_bytes() == b"python"

            calls = []
            old_download = runtime.parent / "updates/0.2.6"
            old_download.mkdir(parents=True)
            (old_download / "package.zip").write_bytes(b"obsolete download")
            preserved = runtime.parent / "updates/unrelated"
            preserved.mkdir()
            def download(url, destination, limit, expected_size=None):
                calls.append(url)
                source = manifest_path if url == module.MANIFEST_URL else signature if url == module.SIGNATURE_URL else archive
                shutil.copyfile(source, destination)
            with patch.object(module, "download", download):
                module.start_background_check(runtime)
                while module.is_check_running():
                    time.sleep(0.01)
                assert module.get_update_status(runtime)["status"] == "ready"
                assert not old_download.exists(), "obsolete update packages accumulate across releases"
                assert preserved.exists(), "cleanup touched a non-version directory"
                assert (runtime / "keep.txt").read_text() == "old runtime remains usable"
                module.start_background_check(runtime)
                while module.is_check_running():
                    time.sleep(0.01)
                assert len(calls) == 3, "persisted throttle did not suppress the next request"
            with patch.object(module, "CHECK_INTERVAL", 0), patch.object(module, "download", side_effect=OSError("offline")):
                module.start_background_check(runtime)
                while module.is_check_running():
                    time.sleep(0.01)
                assert module.get_update_status(runtime)["status"] == "ready", "network failure discarded ready update"
                assert (runtime / "keep.txt").exists()
            module.write_state(runtime, dict(status="installing", installStartedAt=0, helperPid=0, parentPid=0))
            with patch.object(module, "download", download):
                module.start_background_check(runtime)
                while module.is_check_running():
                    time.sleep(0.01)
                assert module.get_update_status(runtime)["status"] == "ready", "HTTP-only startup remained stuck behind a stale install marker"
            with module.native_work_lease(runtime) as admitted:
                assert admitted and module.has_native_work(runtime), "Native work is invisible to idle update handoff"
                assert not module.begin_install_if_ready(runtime, os.getpid()), "update started during Native work"
            assert not module.has_native_work(runtime), "completed Native work kept Engine awake"
            started, finish = threading.Event(), threading.Event()
            def waiting_download(*_args, **_kwargs):
                started.set()
                assert finish.wait(3)
                raise OSError("offline")
            with patch.object(module, "CHECK_INTERVAL", 0), patch.object(module, "download", waiting_download):
                module.start_background_check(runtime)
                try:
                    assert started.wait(2)
                    with module.native_work_lease(runtime) as admitted:
                        assert admitted, "background downloading blocks new Native work"
                        assert not module.begin_install_if_ready(runtime, os.getpid())
                finally:
                    finish.set()
                    while module.is_check_running():
                        time.sleep(0.01)
            child = subprocess.Popen([sys.executable, "-c", "import sys;sys.stdin.read()"], stdin=subprocess.PIPE)
            try:
                with module.native_work_lease(runtime):
                    assert module.register_native_work(runtime, child.pid)
                assert module.has_native_work(runtime), "asynchronous installer lost its work lease when Native host returned"
            finally:
                child.communicate(timeout=3)
            assert not module.has_native_work(runtime), "dead child lease prevents future updates"
            @contextmanager
            def late_work_guard():
                yield False
            assert not module.begin_install_if_ready(runtime, os.getpid(), late_work_guard)
            assert module.get_update_status(runtime)["status"] == "ready", "late work discarded the pending update"
            actual_popen = subprocess.Popen
            def launch_error(command, **options):
                if "--install" in command:
                    assert options.get("cwd") == module.state_directory(runtime), "helper keeps the old runtime directory open during replacement"
                    raise OSError("launch failed")
                return actual_popen(command, **options)
            with patch.object(module.subprocess, "Popen", launch_error):
                assert not module.begin_install_if_ready(runtime, os.getpid())
            assert not module.installation_in_progress(runtime), "failed launch wedged Engine startup"
            assert module.get_update_status(runtime)["status"] == "failed"
            assert module.get_update_status(runtime)["error"] == "launch failed"
            assert (runtime / "keep.txt").exists()
            module.run_installer(runtime, base / "safe" / name, 0)
            assert module.get_update_status(runtime)["status"] == "failed", "failed installer must retain failure diagnostics"
            assert (runtime / "keep.txt").exists()
            module.write_state(runtime, dict(status="installing", installStartedAt=time.time(), helperPid=0, parentPid=0))
            assert not module.installation_in_progress(runtime)
            assert module.get_update_status(runtime)["status"] == "failed", "stale install marker was not cleared"
            module.write_state(runtime, dict(status="installing", installStartedAt=time.time(), helperPid=os.getpid(), parentPid=0))
            assert module.installation_in_progress(runtime), "live installer did not protect Native startup"
            with module.update_lock(runtime) as held:
                assert held
                child = subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,sys.argv[1]);from engine_updates import update_lock;from pathlib import Path\nwith update_lock(Path(sys.argv[2])) as held: assert not held", str(ROOT / "server"), str(runtime)], capture_output=True)
                assert child.returncode == 0, child.stderr
        (runtime / "release.json").write_text(json.dumps({**release, "autoUpdate": False}))
        with patch.object(module, "download", side_effect=AssertionError("disabled runtime used network")):
            module.start_background_check(runtime)
            assert not module.get_update_status(runtime)["enabled"]
    print("Signed Engine updater verification ok")


if __name__ == "__main__":
    main()
