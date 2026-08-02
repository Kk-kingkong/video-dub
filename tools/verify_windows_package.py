#!/usr/bin/env python3
"""Verify the Windows x64 Engine release source and installed package.

The source checks intentionally run on every development platform. The
install smoke check is Windows-only and exercises a per-user installation
under a LocalAppData path containing spaces and non-ASCII characters.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import inspect
import json
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.parse
import uuid
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
WINDOWS_PACKAGE_NAME = "LocalTube-Dub-Engine-v0.2.2-Windows-x64.zip"
WINDOWS_CHECKSUM_NAME = "LocalTube-Dub-v0.2.2-Windows-x64-SHA256SUMS.txt"
WINDOWS_TEMPLATES = {
    "launcher": ROOT_DIR / "packaging" / "windows" / "Install LocalTube Dub Engine.cmd.in",
    "installer": ROOT_DIR / "packaging" / "windows" / "install-engine.ps1.in",
    "manager": ROOT_DIR / "packaging" / "windows" / "manage-engine.ps1.in",
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
        "normalize_initial_native_length_header" in source
        and "NATIVE_INPUT_FIRST_FRAME" in source
        and "LOCAL_DUB_NATIVE_INPUT_UTF8_BOM_COMPAT" in source,
        "Native Host does not handle the Windows launcher's text preamble",
    )
    require(
        "manage-engine.ps1" in source
        and "run_windows_engine_manager" in source,
        "Native Host does not use the shared Windows Engine lifecycle manager",
    )
    require(
        "tempfile.TemporaryFile" in source
        and "stdin=subprocess.DEVNULL" in source
        and "process.kill()" in source,
        "Native Host Windows lifecycle calls are not bounded against inherited pipe stalls",
    )
    require(
        "load_expected_engine_identity" in source
        and "health_matches_expected_engine" in source
        and '"engineVersion"' in source
        and '"instanceId"' in source
        and '"runtimeRoot"' in source,
        "Native Host does not require the installed Engine identity",
    )
    require(
        "taskkill.exe" not in source,
        "Native Host must not trust a PID or terminate Windows processes directly",
    )


def verify_native_health_identity() -> None:
    native_host_path = ROOT_DIR / "companion" / "native_host.py"
    spec = importlib.util.spec_from_file_location(
        "localtube_windows_native_host_verifier",
        native_host_path,
    )
    require(spec is not None and spec.loader is not None, "cannot load Native Host")
    native_host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(native_host)
    runtime_root = ROOT_DIR / "Windows Runtime 路径"
    identity = {
        "service": "localtube-dub",
        "engineVersion": "0.2.2",
        "protocolVersion": 2,
        "platform": "windows",
        "architecture": "x64",
        "runtimeRoot": str(runtime_root),
        "instanceId": "expected-instance",
    }
    require(
        native_host.health_matches_expected_engine(dict(identity), identity),
        "Native Host rejects the exact installed Engine identity",
    )
    for field, wrong_value in (
        ("service", "other"),
        ("engineVersion", "0.1.99"),
        ("protocolVersion", 3),
        ("platform", "macos"),
        ("architecture", "arm64"),
        ("runtimeRoot", str(runtime_root / "old")),
        ("instanceId", "stale-instance"),
    ):
        stale = {**identity, field: wrong_value}
        require(
            not native_host.health_matches_expected_engine(stale, identity),
            f"Native Host accepted mismatched Engine identity field: {field}",
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
    require(
        '"instanceId"' in source
        and '"runtimeRoot"' in source
        and "LOCAL_DUB_ENGINE_INSTANCE_ID" in source
        and "LOCAL_DUB_ENGINE_RUNTIME_ROOT" in source,
        "Engine health does not expose its installed runtime instance",
    )


def verify_packaging_sources() -> None:
    launcher = read_source(WINDOWS_TEMPLATES["launcher"])
    installer = read_source(WINDOWS_TEMPLATES["installer"])
    manager = read_source(WINDOWS_TEMPLATES["manager"])
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
    require("__VERSION__" in manager, "Engine lifecycle manager is missing __VERSION__")
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
        r"HKCU:\Software\Google\Chrome\NativeMessagingHosts" in installer
        and "com.localtube.dub.engine" in installer,
        "installer does not register the HKCU Native Host",
    )
    require("Register-ScheduledTask" in installer, "installer does not create per-user startup")
    require(
        "manage-engine.ps1" in installer
        and "-Action Start" in installer
        and "-Action Stop" in installer,
        "installer does not use the shared lifecycle manager",
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
        and "manage-engine.ps1" in uninstaller
        and "-Action Stop" in uninstaller,
        "uninstaller does not remove per-user startup and Native Host registration",
    )
    require(
        "Get-CimInstance Win32_Process" in manager
        and "Get-NetTCPConnection" in manager
        and "ExecutablePath" in manager
        and "CommandLine" in manager
        and "OwningProcess" in manager,
        "lifecycle manager does not prove process and listener ownership",
    )
    require(
        "engine-state.json" in manager
        and "ConvertFrom-Json" in manager
        and "instanceId" in manager
        and "runtimeRoot" in manager,
        "lifecycle manager does not use a verifiable instance record",
    )
    require(
        "System.Threading.Mutex" in manager
        and "WaitOne" in manager
        and "ReleaseMutex" in manager,
        "lifecycle manager does not serialize concurrent Task/installer/Native Host operations",
    )
    require(
        "Start-Process" in manager
        and "-RedirectStandardOutput" in manager
        and "-RedirectStandardError" in manager
        and "Quote-WindowsArgument" in manager,
        "lifecycle manager does not detach Engine output from caller pipes",
    )
    for identity_check in (
        '$Health.service -eq "localtube-dub"',
        "$Health.engineVersion -eq $ExpectedVersion",
        "$Health.protocolVersion -eq $ExpectedProtocol",
        '$Health.platform -eq "windows"',
        '$Health.architecture -eq "x64"',
        "$Health.instanceId -eq $ExpectedInstanceId",
        "$Health.runtimeRoot",
    ):
        require(identity_check in manager, f"health gate is missing: {identity_check}")
    require(
        "manage-engine.ps1" in builder,
        "Windows builder does not package the lifecycle manager",
    )
    require(
        "Windows-x64-SHA256SUMS.txt" in builder
        and "sha256" in builder
        and "checksum" in builder.casefold(),
        "Windows builder does not create a publishable SHA-256 file",
    )
    require(
        "UseShellExecute = false" in launcher_source
        and "RedirectStandardInput = true" in launcher_source
        and "RedirectStandardOutput = true" in launcher_source
        and "CopyToAsync" not in launcher_source
        and "ReadNativeFrame" in launcher_source
        and "LOCAL_DUB_NATIVE_INPUT_UTF8_BOM_COMPAT" in launcher_source
        and r'Path.Combine(runtimeRoot, ".venv", "python.exe")' in launcher_source,
        "Native Messaging launcher does not bridge one bounded binary request to Python",
    )


def verify_source() -> None:
    verify_runtime_manifest()
    verify_native_host_source()
    verify_native_health_identity()
    verify_server_paths()
    verify_packaging_sources()
    probe = PureWindowsPath(
        r"C:\Users\Test User\AppData\Local",
        "LocalTube Dub",
        "测试 用户",
        "engine-runtime",
    )
    require(" " in str(probe) and "测试 用户" in str(probe), "path smoke fixture is invalid")
    smoke_source = inspect.getsource(verify_install_smoke)
    require(
        "LOCAL_DUB_INSTALL_DRY_RUN" not in smoke_source
        and "LOCAL_DUB_UNINSTALL_DRY_RUN" not in smoke_source,
        "Windows install smoke must execute the real installer and uninstaller",
    )
    for expected in (
        "read_task_fixture",
        "Start-ScheduledTask",
        "winreg",
        "LOCAL_DUB_INSTALL_FAIL_AFTER_MOVE",
        "native_host_launcher.exe",
    ):
        require(expected in smoke_source, f"Windows install smoke does not exercise {expected}")
    print("Windows package source verification ok")


def powershell_executable() -> str:
    return "powershell.exe"


def run_captured(
    command: list[str],
    env: dict[str, str],
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stdout_file:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as stderr_file:
            process = subprocess.Popen(
                command,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=15,
                    )
                else:
                    process.kill()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                stdout_file.flush()
                stderr_file.flush()
                stdout_file.seek(0)
                stderr_file.seek(0)
                raise VerificationError(
                    f"command timed out after {timeout:.0f}s: {' '.join(command)}\n"
                    f"{stdout_file.read()}\n{stderr_file.read()}"
                )
            stdout_file.flush()
            stderr_file.flush()
            stdout_file.seek(0)
            stderr_file.seek(0)
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout_file.read(),
                stderr_file.read(),
            )


def run_checked(
    command: list[str],
    env: dict[str, str],
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    completed = run_captured(command, env, timeout)
    if completed.returncode != 0:
        raise VerificationError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n"
            f"{completed.stdout}\n{completed.stderr}"
        )
    return completed


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def read_engine_state(state_path: Path) -> dict[str, Any]:
    require(state_path.is_file(), f"Engine state does not exist: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    require(isinstance(state, dict), "Engine state is not an object")
    require(int(state.get("pid") or 0) > 0, "Engine state has no PID")
    require(bool(state.get("instanceId")), "Engine state has no instance ID")
    return state


def wait_for_exact_health(
    port: int,
    runtime_root: Path,
    state_path: Path,
    timeout: float = 30,
) -> tuple[dict[str, Any], dict[str, Any]]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            state = read_engine_state(state_path)
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health",
                timeout=1,
            ) as response:
                health = json.loads(response.read())
            expected = {
                "service": "localtube-dub",
                "engineVersion": "0.2.2",
                "protocolVersion": 2,
                "platform": "windows",
                "architecture": "x64",
                "instanceId": state["instanceId"],
            }
            if all(health.get(key) == value for key, value in expected.items()) and (
                Path(str(health.get("runtimeRoot") or "")).resolve()
                == runtime_root.resolve()
            ):
                return health, state
            last_error = f"identity mismatch: {health}"
        except Exception as error:
            last_error = str(error)
        time.sleep(0.25)
    raise VerificationError(f"installed Engine did not pass exact health: {last_error}")


def invoke_manager(
    manager: Path,
    action: str,
    runtime_root: Path,
    state_root: Path,
    port: int,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return run_checked(
        [
            powershell_executable(),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(manager),
            "-Action",
            action,
            "-ExpectedVersion",
            "0.2.2",
            "-ExpectedRuntimeRoot",
            str(runtime_root),
            "-StateRootOverride",
            str(state_root),
            "-LocalAppDataOverride",
            str(Path(env["LOCALAPPDATA"])),
            "-Port",
            str(port),
            "-Json",
        ],
        env,
    )


def read_task_fixture(task_name: str, env: dict[str, str]) -> dict[str, Any]:
    script = (
        "$Task=Get-ScheduledTask -TaskName $env:LOCAL_DUB_TASK_NAME "
        "-ErrorAction Stop;"
        "$Action=$Task.Actions[0];"
        "[ordered]@{"
        "execute=$Action.Execute;"
        "arguments=$Action.Arguments;"
        "workingDirectory=$Action.WorkingDirectory;"
        "userId=$Task.Principal.UserId;"
        "runLevel=[string]$Task.Principal.RunLevel"
        "}|ConvertTo-Json -Compress"
    )
    completed = run_checked(
        [powershell_executable(), "-NoProfile", "-Command", script],
        env,
    )
    payload = json.loads(completed.stdout.strip())
    require(isinstance(payload, dict), f"scheduled task {task_name} is invalid")
    return payload


def task_fixture_exists(env: dict[str, str]) -> bool:
    completed = subprocess.run(
        [
            powershell_executable(),
            "-NoProfile",
            "-Command",
            "if(Get-ScheduledTask -TaskName $env:LOCAL_DUB_TASK_NAME "
            "-ErrorAction SilentlyContinue){exit 0}else{exit 1}",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def invoke_native_launcher(launcher: Path, env: dict[str, str]) -> dict[str, Any]:
    request = json.dumps({"type": "start"}).encode("utf-8")
    framed = struct.pack("<I", len(request)) + request
    timed_out = False
    with tempfile.TemporaryFile(mode="w+b") as stdin_file:
        with tempfile.TemporaryFile(mode="w+b") as stdout_file:
            with tempfile.TemporaryFile(mode="w+b") as stderr_file:
                stdin_file.write(framed)
                stdin_file.seek(0)
                process = subprocess.Popen(
                    [str(launcher)],
                    env=env,
                    stdin=stdin_file,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    subprocess.run(
                        ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=15,
                    )
                    process.wait(timeout=10)
                    timed_out = True
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read()
                stderr = stderr_file.read()
    if timed_out:
        native_log_path = Path(tempfile.gettempdir()) / "localtube-dub-native-host.log"
        native_log = (
            native_log_path.read_text(encoding="utf-8", errors="replace")
            if native_log_path.is_file()
            else ""
        )
        raise VerificationError(
            "compiled Native Messaging launcher timed out: "
            f"stdout={stdout[:512].hex()}, "
            f"stderr={stderr[:1024].decode(errors='replace')}, "
            f"nativeLog={native_log[-4000:]}"
        )
    require(
        process.returncode == 0,
        f"compiled Native Messaging launcher failed: {stderr.decode(errors='replace')}",
    )
    require(len(stdout) >= 4, "compiled Native Messaging launcher returned no frame")
    length = struct.unpack("<I", stdout[:4])[0]
    require(
        len(stdout) == length + 4,
        "compiled Native Messaging launcher returned a broken frame: "
        f"declared={length}, actual={len(stdout) - 4}, "
        f"head={stdout[:64].hex()}, trailing={stdout[length + 4:length + 68].hex()}, "
        f"stderr={stderr.decode(errors='replace')}",
    )
    payload = json.loads(stdout[4:].decode("utf-8"))
    require(isinstance(payload, dict), "compiled Native Messaging response is invalid")
    return payload


def verify_install_smoke(package: Path) -> None:
    require(os.name == "nt", "--install-smoke must run on Windows")
    require(package.is_file(), f"Windows package does not exist: {package}")
    print("Windows smoke: validating package", flush=True)
    checksum_path = package.with_name(WINDOWS_CHECKSUM_NAME)
    require(checksum_path.is_file(), f"Windows checksum does not exist: {checksum_path}")
    checksum_parts = checksum_path.read_text(encoding="ascii").strip().split()
    require(
        len(checksum_parts) == 2 and checksum_parts[1] == package.name,
        "Windows checksum file has an invalid format or filename",
    )
    digest = hashlib.sha256()
    with package.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    require(
        digest.hexdigest() == checksum_parts[0].lower(),
        "Windows package SHA-256 does not match its published checksum",
    )
    import winreg

    with tempfile.TemporaryDirectory(prefix="LocalTube Dub 测试 ") as temporary:
        root = Path(temporary)
        extract_root = root / "解压 目录"
        local_app_data = root / "Local App Data 测试"
        with zipfile.ZipFile(package) as archive:
            archive.extractall(extract_root)
        print("Windows smoke: package extracted", flush=True)
        installers = list(extract_root.rglob("install-engine.ps1"))
        uninstallers = list(extract_root.rglob("uninstall-engine.ps1"))
        managers = list(extract_root.rglob("manage-engine.ps1"))
        require(
            len(installers) == 1 and len(uninstallers) == 1 and len(managers) == 1,
            "package installer layout is invalid",
        )

        env = os.environ.copy()
        test_id = uuid.uuid4().hex
        native_host_name = f"{NATIVE_HOST_NAME}.task7_{test_id}"
        registry_subkey = (
            r"Software\Google\Chrome\NativeMessagingHosts" + f"\\{native_host_name}"
        )
        task_name = f"LocalTube Dub Engine Task7 {test_id}"
        port = unused_loopback_port()
        runtime_root = local_app_data / "LocalTube Dub" / "测试 用户" / "engine-runtime"
        state_root = local_app_data / "LocalTube Dub" / "测试 用户" / "state"
        state_path = state_root / "engine-state.json"
        native_manifest_path = (
            local_app_data
            / "LocalTube Dub"
            / "测试 用户"
            / "native-messaging"
            / f"{native_host_name}.json"
        )
        env["LOCALAPPDATA"] = str(local_app_data)
        env["LOCAL_DUB_RUNTIME_DIR"] = str(runtime_root)
        env["LOCAL_DUB_STATE_DIR"] = str(state_root)
        env["LOCAL_DUB_NATIVE_MANIFEST_PATH"] = str(native_manifest_path)
        env["LOCAL_DUB_NATIVE_HOST_NAME"] = native_host_name
        env["LOCAL_DUB_REGISTRY_PATH"] = "HKCU:\\" + registry_subkey
        env["LOCAL_DUB_TASK_NAME"] = task_name
        env["LOCAL_DUB_PORT"] = str(port)

        def run_installer(
            extra_env: dict[str, str] | None = None,
            expect_success: bool = True,
        ) -> subprocess.CompletedProcess[str]:
            install_env = {**env, **(extra_env or {})}
            completed = run_captured(
                [
                    powershell_executable(),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(installers[0]),
                    "-Repair",
                ],
                install_env,
                180,
            )
            if expect_success:
                require(
                    completed.returncode == 0,
                    f"real installer failed:\n{completed.stdout}\n{completed.stderr}",
                )
            else:
                require(completed.returncode != 0, "fault-injected installer unexpectedly passed")
            return completed

        def cleanup() -> None:
            for manager in (runtime_root / "manage-engine.ps1", managers[0]):
                if not manager.is_file():
                    continue
                completed = subprocess.run(
                    [
                        powershell_executable(),
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(manager),
                        "-Action",
                        "Stop",
                        "-ExpectedVersion",
                        "0.2.2",
                        "-ExpectedRuntimeRoot",
                        str(runtime_root),
                        "-StateRootOverride",
                        str(state_root),
                        "-LocalAppDataOverride",
                        str(local_app_data),
                        "-Port",
                        str(port),
                        "-Json",
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )
                if completed.returncode == 0:
                    break
            env["LOCAL_DUB_CLEANUP_PYTHON"] = str(runtime_root / ".venv" / "python.exe")
            env["LOCAL_DUB_CLEANUP_SERVER"] = str(
                runtime_root / "server" / "local_dub_server.py"
            )
            subprocess.run(
                [
                    powershell_executable(),
                    "-NoProfile",
                    "-Command",
                    "Stop-ScheduledTask -TaskName $env:LOCAL_DUB_TASK_NAME "
                    "-ErrorAction SilentlyContinue;"
                    "$Python=[IO.Path]::GetFullPath($env:LOCAL_DUB_CLEANUP_PYTHON);"
                    "$Server=[IO.Path]::GetFullPath($env:LOCAL_DUB_CLEANUP_SERVER);"
                    "$QuotedServer='\"'+$Server+'\"';"
                    "foreach($Connection in @(Get-NetTCPConnection "
                    "-LocalPort ([int]$env:LOCAL_DUB_PORT) -State Listen "
                    "-ErrorAction SilentlyContinue)){"
                    "$Process=Get-CimInstance Win32_Process "
                    "-Filter ('ProcessId = '+$Connection.OwningProcess) "
                    "-ErrorAction SilentlyContinue;"
                    "if($Process -and $Process.ExecutablePath -and $Process.CommandLine "
                    "-and [string]::Equals([IO.Path]::GetFullPath($Process.ExecutablePath),"
                    "$Python,[StringComparison]::OrdinalIgnoreCase) "
                    "-and $Process.CommandLine.IndexOf($QuotedServer,"
                    "[StringComparison]::OrdinalIgnoreCase) -ge 0){"
                    "Stop-Process -Id $Connection.OwningProcess -Force "
                    "-ErrorAction SilentlyContinue"
                    "}};"
                    "Unregister-ScheduledTask -TaskName $env:LOCAL_DUB_TASK_NAME "
                    "-Confirm:$false -ErrorAction SilentlyContinue;"
                    "Remove-Item -LiteralPath $env:LOCAL_DUB_REGISTRY_PATH "
                    "-Recurse -Force -ErrorAction SilentlyContinue",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

        try:
            print("Windows smoke: initial install", flush=True)
            run_installer()
            print("Windows smoke: initial health", flush=True)
            require((runtime_root / "release.json").is_file(), "real install did not activate runtime")
            health, initial_state = wait_for_exact_health(
                port,
                runtime_root,
                state_path,
            )
            require(health["engineVersion"] == "0.2.2", "wrong Engine version accepted")

            stale_state = dict(initial_state)
            stale_state["pid"] = os.getpid()
            state_path.write_text(json.dumps(stale_state), encoding="utf-8")
            print("Windows smoke: stale-state stop and restart", flush=True)
            invoke_manager(
                runtime_root / "manage-engine.ps1",
                "Stop",
                runtime_root,
                state_root,
                port,
                env,
            )
            require(
                not state_path.exists(),
                "verified listener fallback left the stale lifecycle record",
            )
            invoke_manager(
                runtime_root / "manage-engine.ps1",
                "Start",
                runtime_root,
                state_root,
                port,
                env,
            )
            _, initial_state = wait_for_exact_health(port, runtime_root, state_path)

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_subkey) as registry_key:
                registered_manifest, registry_type = winreg.QueryValueEx(registry_key, None)
            require(registry_type == winreg.REG_SZ, "HKCU Native Host value is not REG_SZ")
            require(
                Path(registered_manifest).resolve() == native_manifest_path.resolve(),
                "HKCU Native Host points to the wrong manifest",
            )
            manifest_bytes = native_manifest_path.read_bytes()
            require(
                not manifest_bytes.startswith(b"\xef\xbb\xbf"),
                "Native Messaging manifest contains a UTF-8 BOM",
            )
            native_manifest = json.loads(manifest_bytes)
            require(
                native_manifest.get("name") == native_host_name
                and native_manifest.get("allowed_origins")
                == [f"chrome-extension://{STORE_EXTENSION_ID}/"],
                "installed Native Messaging manifest lost Store ID binding",
            )
            require(
                Path(native_manifest.get("path", "")).resolve()
                == (runtime_root / "companion" / "native_host_launcher.exe").resolve(),
                "installed Native Messaging manifest has the wrong launcher path",
            )

            task = read_task_fixture(task_name, env)
            require(
                str(task.get("execute") or "").lower().endswith("powershell.exe"),
                "scheduled task does not execute PowerShell",
            )
            task_arguments = str(task.get("arguments") or "").replace("/", "\\").casefold()
            expected_task_paths = (
                (runtime_root / "manage-engine.ps1").resolve(),
                runtime_root.resolve(),
                state_root.resolve(),
            )
            require(
                all(
                    str(path).replace("/", "\\").casefold() in task_arguments
                    for path in expected_task_paths
                ),
                f"scheduled task did not preserve paths with spaces/Chinese: {task}",
            )
            require(
                str(task.get("runLevel") or "").lower() == "limited",
                "scheduled task is not a limited per-user task",
            )
            require(
                bool(task.get("userId"))
                and str(task.get("userId") or "").lower() != "system",
                "scheduled task is not bound to the current user",
            )

            print("Windows smoke: scheduled-task startup", flush=True)
            invoke_manager(
                runtime_root / "manage-engine.ps1",
                "Stop",
                runtime_root,
                state_root,
                port,
                env,
            )
            run_checked(
                [
                    powershell_executable(),
                    "-NoProfile",
                    "-Command",
                    "Start-ScheduledTask -TaskName $env:LOCAL_DUB_TASK_NAME",
                ],
                env,
            )
            _, task_state = wait_for_exact_health(port, runtime_root, state_path)
            require(
                task_state["instanceId"] != initial_state["instanceId"],
                "Scheduled Task did not create a fresh Engine instance",
            )

            print("Windows smoke: compiled Native Messaging startup", flush=True)
            invoke_manager(
                runtime_root / "manage-engine.ps1",
                "Stop",
                runtime_root,
                state_root,
                port,
                env,
            )
            native_response = invoke_native_launcher(
                runtime_root / "companion" / "native_host_launcher.exe",
                env,
            )
            require(native_response.get("ok") is True, "compiled Native Host could not manage Engine")
            _, native_state = wait_for_exact_health(port, runtime_root, state_path)

            before_repair = native_state["instanceId"]
            print("Windows smoke: repair install", flush=True)
            run_installer()
            _, repaired_state = wait_for_exact_health(port, runtime_root, state_path)
            require(
                repaired_state["instanceId"] != before_repair,
                "repair reused a stale Engine instance",
            )

            print("Windows smoke: rollback after injected failure", flush=True)
            run_installer(
                {"LOCAL_DUB_INSTALL_FAIL_AFTER_MOVE": "1"},
                expect_success=False,
            )
            _, rollback_state = wait_for_exact_health(port, runtime_root, state_path)
            require(
                rollback_state["instanceId"] != repaired_state["instanceId"],
                "post-activation rollback did not restore and restart the prior runtime",
            )
            require(task_fixture_exists(env), "rollback did not restore the Scheduled Task")
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_subkey):
                pass

            source_lock = installers[0].parent / ".venv" / "runtime-lock.json"
            source_lock_bytes = source_lock.read_bytes()
            source_lock.unlink()
            try:
                print("Windows smoke: fail-closed preflight", flush=True)
                unchanged_instance = read_engine_state(state_path)["instanceId"]
                run_installer(expect_success=False)
                require(
                    read_engine_state(state_path)["instanceId"] == unchanged_instance,
                    "fail-closed preflight disturbed the running Engine",
                )
            finally:
                source_lock.write_bytes(source_lock_bytes)

            print("Windows smoke: uninstall", flush=True)
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
            require(not runtime_root.exists(), "real uninstall left the runtime installed")
            require(not state_root.exists(), "real uninstall left lifecycle state")
            require(not native_manifest_path.exists(), "real uninstall left the Native Host manifest")
            require(not task_fixture_exists(env), "real uninstall left the Scheduled Task")
            try:
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_subkey)
            except FileNotFoundError:
                pass
            else:
                raise VerificationError("real uninstall left the HKCU Native Host registration")
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            except OSError:
                pass
            else:
                raise VerificationError("real uninstall left the Engine listener running")
        finally:
            print("Windows smoke: cleanup", flush=True)
            cleanup()
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
