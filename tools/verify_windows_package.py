#!/usr/bin/env python3
"""Verify the Windows x64 Engine release source and installed package.

The source checks intentionally run on every development platform. The
install smoke check is Windows-only and exercises a per-user installation
under a LocalAppData path containing spaces and non-ASCII characters.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
STORE_EXTENSION_ID = "ikoenamldegccnhmjjnlkffocdkbbbmo"
NATIVE_HOST_NAME = "com.localtube.dub.engine"
REGISTRY_ROOT = (
    r"HKCU\Software\Google\Chrome\NativeMessagingHosts"
    rf"\{NATIVE_HOST_NAME}"
)
WINDOWS_PACKAGE_NAME = "LocalTube-Dub-Engine-v0.2.0-Windows-x64.zip"
WINDOWS_TEMPLATES = {
    "launcher": ROOT_DIR / "packaging" / "windows" / "Install LocalTube Dub Engine.cmd.in",
    "installer": ROOT_DIR / "packaging" / "windows" / "install-engine.ps1.in",
    "uninstaller": ROOT_DIR / "packaging" / "windows" / "uninstall-engine.ps1.in",
}


class VerificationError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def read_source(path: Path) -> str:
    require(path.is_file(), f"missing required source file: {path.relative_to(ROOT_DIR)}")
    return path.read_text(encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(read_source(path))
    except json.JSONDecodeError as error:
        raise VerificationError(f"invalid JSON: {path.relative_to(ROOT_DIR)}: {error}") from error
    require(isinstance(payload, dict), f"{path.relative_to(ROOT_DIR)} must contain an object")
    return payload


def artifact_for_windows(package: dict[str, Any]) -> dict[str, Any]:
    if isinstance(package.get("artifact"), dict):
        return package["artifact"]
    platform_artifacts = package.get("platformArtifacts")
    require(
        isinstance(platform_artifacts, dict)
        and isinstance(platform_artifacts.get("windows"), dict)
        and isinstance(platform_artifacts["windows"].get("x64"), dict),
        f"package {package.get('id')} is missing a Windows x64 artifact",
    )
    return platform_artifacts["windows"]["x64"]


def verify_artifact(artifact: dict[str, Any], label: str) -> None:
    parsed = urllib.parse.urlsplit(str(artifact.get("url") or ""))
    require(parsed.scheme == "https" and bool(parsed.netloc), f"{label} must use an HTTPS URL")
    require(
        Path(str(artifact.get("name") or "")).name == str(artifact.get("name") or ""),
        f"{label} has an unsafe filename",
    )
    require(int(artifact.get("bytes") or 0) > 0, f"{label} must pin an exact byte size")
    digest = str(artifact.get("sha256") or "").lower()
    require(
        len(digest) == 64 and all(character in "0123456789abcdef" for character in digest),
        f"{label} must pin a SHA-256 digest",
    )


def verify_runtime_manifest() -> None:
    manifest = load_json(ROOT_DIR / "packaging" / "runtime-manifest.json")
    platforms = manifest.get("platforms")
    require(isinstance(platforms, dict), "runtime manifest is missing platforms")
    windows = platforms.get("windows")
    require(isinstance(windows, dict), "runtime manifest is missing Windows")
    architectures = windows.get("architectures")
    require(
        isinstance(architectures, dict) and set(architectures) == {"x64"},
        "Windows runtime must support exactly x64",
    )
    target = architectures["x64"]
    require(target.get("pythonVersion") == "3.11.15", "Windows Python must be pinned to 3.11.15")
    verify_artifact(target.get("python") or {}, "Windows Python")
    executables = target.get("executables")
    require(isinstance(executables, list) and executables, "Windows runtime is missing ffmpeg")
    for executable in executables:
        require(executable.get("installAs") == "ffmpeg.exe", "Windows ffmpeg install name is invalid")
        verify_artifact(executable, "Windows ffmpeg")

    packages = manifest.get("packages")
    require(isinstance(packages, list) and packages, "runtime manifest is missing packages")
    package_ids = [str(package.get("id") or "") for package in packages]
    require(len(package_ids) == len(set(package_ids)), "runtime manifest has duplicate package IDs")
    require(
        {"sherpa-onnx", "sherpa-onnx-core", "yt-dlp", "edge-tts"}.issubset(package_ids),
        "Windows runtime is missing required pinned dependencies",
    )
    for package in packages:
        require(bool(package.get("version")), f"package {package.get('id')} has no pinned version")
        verify_artifact(artifact_for_windows(package), f"package {package.get('id')}")

    assembler_path = ROOT_DIR / "scripts" / "assemble_engine_runtime.py"
    spec = importlib.util.spec_from_file_location("localtube_windows_runtime_assembler", assembler_path)
    require(spec is not None and spec.loader is not None, "cannot load runtime assembler")
    assembler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assembler)
    loaded = assembler.load_runtime_manifest()
    selected = assembler._selected_artifacts(loaded, "windows", "x64")
    selected_names = [str(item.get("name") or "") for item in selected]
    require(
        any(name.endswith("win_amd64.whl") for name in selected_names),
        "runtime assembler does not select Windows x64 wheels",
    )


def verify_native_host_source() -> None:
    source = read_source(ROOT_DIR / "companion" / "native_host.py")
    require("import msvcrt" in source, "Native Host does not import msvcrt on Windows")
    require("os.O_BINARY" in source, "Native Host does not use O_BINARY")
    require(
        source.count("msvcrt.setmode") >= 2,
        "Native Host must switch both stdin and stdout to binary mode",
    )
    require(
        "configure_native_stdio()" in source,
        "Native Host does not configure binary stdio before entering its message loop",
    )
    require(
        (
            "creationflags=" in source
            or 'popen_options["creationflags"]' in source
        )
        and "CREATE_NEW_PROCESS_GROUP" in source,
        "Native Host does not detach the Windows HTTP Engine safely",
    )
    require(
        "def default_engine_pid_path(" in source
        and "LOCALAPPDATA" in source
        and '"LocalTube Dub"' in source
        and '"state"' in source,
        "Native Host does not share the per-user Windows Engine PID path",
    )


def verify_server_paths() -> None:
    source = read_source(ROOT_DIR / "server" / "local_dub_server.py")
    require("def user_data_dir(" in source, "Engine has no cross-platform user data helper")
    require("def user_cache_dir(" in source, "Engine has no cross-platform user cache helper")
    require(
        "WHISPER_CPP_MODEL = user_data_dir()" in source,
        "Whisper model default is not cross-platform",
    )
    require(
        "DUB_TRACK_OUTPUT_DIR = user_cache_dir()" in source,
        "dub export default is not cross-platform",
    )


def verify_packaging_sources() -> None:
    launcher = read_source(WINDOWS_TEMPLATES["launcher"])
    installer = read_source(WINDOWS_TEMPLATES["installer"])
    uninstaller = read_source(WINDOWS_TEMPLATES["uninstaller"])
    builder = read_source(ROOT_DIR / "scripts" / "build_release_windows.py")
    launcher_source = read_source(
        ROOT_DIR / "packaging" / "windows" / "native-host-launcher.cs"
    )

    require(
        "powershell.exe" in launcher.lower()
        and "-ExecutionPolicy Bypass" in launcher
        and "install-engine.ps1" in launcher,
        "double-click launcher does not invoke the pinned installer",
    )
    for placeholder in ("__EXTENSION_ID__", "__VERSION__"):
        require(placeholder in installer, f"installer is missing {placeholder}")
        require(placeholder in builder, f"builder does not render {placeholder}")
    require(STORE_EXTENSION_ID in builder, "builder is not bound to the Chrome Web Store extension ID")
    require(WINDOWS_PACKAGE_NAME in builder, "builder does not produce the required package name")
    require(
        "assemble_engine_runtime" in builder and '"windows"' in builder and '"x64"' in builder,
        "builder does not assemble the pinned Windows x64 runtime",
    )
    require(
        "runtime-lock.json" in installer and "runtimeContract" in installer,
        "installer does not verify the offline runtime integrity contract",
    )
    require(
        not re.search(r"\b(?:pip|winget|choco|curl|wget|Invoke-WebRequest)\b", installer, re.IGNORECASE),
        "customer installer must not download dependencies or invoke package managers",
    )
    require(
        r"HKCU:\Software\Google\Chrome\NativeMessagingHosts\com.localtube.dub.engine"
        in installer,
        "installer does not register the HKCU Native Host",
    )
    require("Register-ScheduledTask" in installer, "installer does not create per-user startup")
    require("/api/health" in installer, "installer does not verify Engine health")
    require(
        "LOCAL_DUB_INSTALL_DRY_RUN" in installer and "LOCAL_DUB_RUNTIME_DIR" in installer,
        "installer has no isolated dry-run contract",
    )
    require(
        "Repair" in installer and "Rollback" in installer,
        "installer does not expose repair and rollback behavior",
    )
    require(
        "LOCAL_DUB_INSTALL_FAIL_AFTER_MOVE" in installer,
        "installer has no rollback fault-injection contract",
    )
    require(
        "UTF8Encoding($false)" in installer,
        "installer may write a BOM into the Native Messaging manifest",
    )
    require(
        "[Environment]::OSVersion.Version.Major" in installer,
        "installer does not enforce Windows 10/11",
    )
    require(
        "Unregister-ScheduledTask" in uninstaller
        and "Remove-ItemProperty" in uninstaller
        and "LOCAL_DUB_UNINSTALL_DRY_RUN" in uninstaller,
        "uninstaller does not remove per-user startup and Native Host registration",
    )
    require(
        "RedirectStandardInput = true" in launcher_source
        and "RedirectStandardOutput = true" in launcher_source
        and r'Path.Combine(runtimeRoot, ".venv", "python.exe")' in launcher_source,
        "Native Messaging launcher does not bridge Chrome to the bundled Python host",
    )


def verify_source() -> None:
    verify_runtime_manifest()
    verify_native_host_source()
    verify_server_paths()
    verify_packaging_sources()
    probe = PureWindowsPath(
        r"C:\Users\Test User\AppData\Local",
        "LocalTube Dub",
        "测试 用户",
        "engine-runtime",
    )
    require(" " in str(probe) and "测试 用户" in str(probe), "path smoke fixture is invalid")
    print("Windows package source verification ok")


def powershell_executable() -> str:
    return "powershell.exe"


def run_checked(command: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise VerificationError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed


def verify_install_smoke(package: Path) -> None:
    require(os.name == "nt", "--install-smoke must run on Windows")
    require(package.is_file(), f"Windows package does not exist: {package}")
    with tempfile.TemporaryDirectory(prefix="LocalTube Dub 测试 ") as temporary:
        root = Path(temporary)
        extract_root = root / "解压 目录"
        local_app_data = root / "Local App Data 测试"
        with zipfile.ZipFile(package) as archive:
            archive.extractall(extract_root)
        installers = list(extract_root.rglob("install-engine.ps1"))
        uninstallers = list(extract_root.rglob("uninstall-engine.ps1"))
        require(len(installers) == 1 and len(uninstallers) == 1, "package installer layout is invalid")

        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(local_app_data)
        env["LOCAL_DUB_INSTALL_DRY_RUN"] = "1"
        env["LOCAL_DUB_RUNTIME_DIR"] = str(local_app_data / "LocalTube Dub" / "测试 用户" / "engine-runtime")
        run_checked(
            [
                powershell_executable(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(installers[0]),
                "-Repair",
            ],
            env,
        )
        runtime_root = Path(env["LOCAL_DUB_RUNTIME_DIR"])
        require((runtime_root / "release.json").is_file(), "dry-run install did not stage release metadata")
        native_manifest_path = (
            local_app_data
            / "LocalTube Dub"
            / "native-messaging"
            / "com.localtube.dub.engine.json"
        )
        require(native_manifest_path.is_file(), "dry-run install did not write the Native Messaging manifest")
        manifest_bytes = native_manifest_path.read_bytes()
        require(not manifest_bytes.startswith(b"\xef\xbb\xbf"), "Native Messaging manifest contains a UTF-8 BOM")
        native_manifest = json.loads(manifest_bytes)
        require(
            native_manifest.get("allowed_origins")
            == [f"chrome-extension://{STORE_EXTENSION_ID}/"],
            "installed Native Messaging manifest has the wrong allowed origin",
        )
        require(
            Path(native_manifest.get("path", "")).resolve()
            == (runtime_root / "companion" / "native_host_launcher.exe").resolve(),
            "installed Native Messaging manifest has the wrong launcher path",
        )

        run_checked(
            [
                powershell_executable(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(runtime_root / "install-engine.ps1"),
                "-Repair",
            ],
            env,
        )

        server = subprocess.Popen(
            [
                str(runtime_root / ".venv" / "python.exe"),
                str(runtime_root / "server" / "local_dub_server.py"),
            ],
            cwd=runtime_root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(40):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8787/api/health", timeout=1) as response:
                        health = json.loads(response.read())
                    if (
                        int(health.get("protocolVersion") or 0) >= 2
                        and health.get("ytDlp")
                        and health.get("edgeTts")
                    ):
                        break
                except OSError:
                    time.sleep(0.25)
            else:
                raise VerificationError("installed Windows Engine did not pass /api/health")
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)

        previous_marker = runtime_root / "previous-working-runtime.txt"
        previous_marker.write_text("working", encoding="utf-8")
        source_lock = installers[0].parent / ".venv" / "runtime-lock.json"
        source_lock.unlink()
        failed = subprocess.run(
            [
                powershell_executable(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(installers[0]),
                "-Repair",
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        require(failed.returncode != 0, "installer accepted a package with a missing runtime lock")
        require(previous_marker.read_text(encoding="utf-8") == "working", "failed install replaced the working runtime")

        env["LOCAL_DUB_UNINSTALL_DRY_RUN"] = "1"
        run_checked(
            [
                powershell_executable(),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(uninstallers[0]),
                "-Yes",
            ],
            env,
        )
        require(not runtime_root.exists(), "dry-run uninstall left the runtime installed")
    print("Windows package install smoke ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", action="store_true")
    mode.add_argument(
        "--install-smoke",
        type=Path,
        nargs="?",
        const=ROOT_DIR / "dist" / WINDOWS_PACKAGE_NAME,
        metavar="PACKAGE",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.source:
            verify_source()
        else:
            verify_install_smoke(args.install_smoke)
        return 0
    except (OSError, VerificationError, ValueError, zipfile.BadZipFile) as error:
        print(f"Windows package verification failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
