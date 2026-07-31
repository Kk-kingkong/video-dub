#!/usr/bin/env python3
"""Build the pinned Windows x64 LocalTube Dub Engine package."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "scripts"))

from assemble_engine_runtime import assemble_runtime, load_runtime_manifest  # noqa: E402


EXTENSION_ID = "ikoenamldegccnhmjjnlkffocdkbbbmo"
PACKAGE_VERSION = "0.2.1"
PACKAGE_NAME = "LocalTube-Dub-Engine-v0.2.1-Windows-x64.zip"
CHECKSUM_NAME = "LocalTube-Dub-v0.2.1-Windows-x64-SHA256SUMS.txt"
ENGINE_FOLDER = "LocalTube-Dub-Engine-v0.2.1-Windows-x64"


class WindowsBuildError(RuntimeError):
    pass


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def render_template(source: Path, destination: Path) -> None:
    text = source.read_text(encoding="utf-8")
    text = text.replace("__EXTENSION_ID__", EXTENSION_ID).replace("__VERSION__", PACKAGE_VERSION)
    if "__EXTENSION_ID__" in text or "__VERSION__" in text:
        raise WindowsBuildError(f"unrendered placeholder in {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="\r\n") as output:
        output.write(text)


def find_csharp_compiler() -> Path:
    candidate = shutil.which("csc.exe")
    if candidate:
        return Path(candidate)
    windows_root = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for framework in ("Framework64", "Framework"):
        path = windows_root / "Microsoft.NET" / framework / "v4.0.30319" / "csc.exe"
        if path.is_file():
            return path
    raise WindowsBuildError("csc.exe is required to build the Native Messaging launcher")


def compile_native_launcher(stage: Path) -> None:
    source = ROOT_DIR / "packaging" / "windows" / "native-host-launcher.cs"
    output = stage / "companion" / "native_host_launcher.exe"
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            str(find_csharp_compiler()),
            "/nologo",
            "/target:exe",
            f"/out:{output}",
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "csc.exe failed").strip()
        raise WindowsBuildError(f"Native Messaging launcher compilation failed: {detail}")


def runtime_contract(runtime: Path) -> dict[str, Any]:
    lock_path = runtime / "runtime-lock.json"
    lock_bytes = lock_path.read_bytes()
    lock = json.loads(lock_bytes)
    return {
        "schemaVersion": 1,
        "lockSha256": hashlib.sha256(lock_bytes).hexdigest(),
        "treeSha256": lock["installedTree"]["digest"],
        "pythonVersion": lock["pythonVersion"],
        "packages": lock["packages"],
        "artifacts": lock["artifacts"],
        "modelManifest": lock["modelManifest"],
    }


def write_release_metadata(stage: Path) -> None:
    payload = {
        "product": "LocalTube Dub Engine",
        "version": PACKAGE_VERSION,
        "protocolVersion": 2,
        "chromeExtensionId": EXTENSION_ID,
        "platform": "windows",
        "architecture": "x64",
        "bundledRuntime": True,
        "runtimeLock": ".venv/runtime-lock.json",
        "runtimeContract": runtime_contract(stage / ".venv"),
        "channel": "private-beta",
        "signed": False,
        "notarized": False,
    }
    (stage / "release.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def assert_model_not_bundled(stage: Path) -> None:
    prohibited = {"model.int8.onnx", "voices.bin", "kokoro-int8-multi-lang-v1_1.tar.bz2"}
    for path in stage.rglob("*"):
        if path.name in prohibited or "models/kokoro" in path.as_posix():
            raise WindowsBuildError(f"Windows package must not bundle a Kokoro model: {path}")


def write_zip(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            relative = Path(ENGINE_FOLDER) / path.relative_to(source)
            archive.write(path, relative.as_posix())


def write_checksum(package: Path) -> Path:
    digest = hashlib.sha256()
    with package.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = package.with_name(CHECKSUM_NAME)
    checksum.write_text(
        f"{digest.hexdigest()}  {package.name}\n",
        encoding="ascii",
    )
    return checksum


def build(output_dir: Path, cache_dir: Path) -> Path:
    if os.name != "nt":
        raise WindowsBuildError("the Windows runtime package must be built on Windows x64")
    manifest = load_runtime_manifest()
    with tempfile.TemporaryDirectory(prefix="LocalTube Dub Windows build ") as temporary:
        stage = Path(temporary) / ENGINE_FOLDER
        stage.mkdir(parents=True)
        for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            copy_file(ROOT_DIR / name, stage / name)
        for name in ("local_dub_server.py", "kokoro_tts.py"):
            copy_file(ROOT_DIR / "server" / name, stage / "server" / name)
        copy_file(ROOT_DIR / "companion" / "native_host.py", stage / "companion" / "native_host.py")
        copy_file(
            ROOT_DIR / "scripts" / "assemble_engine_runtime.py",
            stage / "scripts" / "assemble_engine_runtime.py",
        )
        assemble_runtime(manifest, "windows", "x64", stage / ".venv", cache_dir)
        compile_native_launcher(stage)
        render_template(
            ROOT_DIR / "packaging" / "windows" / "Install LocalTube Dub Engine.cmd.in",
            stage / "Install LocalTube Dub Engine.cmd",
        )
        render_template(
            ROOT_DIR / "packaging" / "windows" / "install-engine.ps1.in",
            stage / "install-engine.ps1",
        )
        render_template(
            ROOT_DIR / "packaging" / "windows" / "manage-engine.ps1.in",
            stage / "manage-engine.ps1",
        )
        render_template(
            ROOT_DIR / "packaging" / "windows" / "uninstall-engine.ps1.in",
            stage / "uninstall-engine.ps1",
        )
        write_release_metadata(stage)
        assert_model_not_bundled(stage)
        package = output_dir / PACKAGE_NAME
        write_zip(stage, package)
        write_checksum(package)
        return package


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT_DIR / "dist")
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path.home() / ".cache" / "localtube-dub" / "runtime",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        package = build(args.output.resolve(), args.cache.resolve())
        print(f"Windows Engine: {package}")
        print(f"SHA-256: {package.with_name(CHECKSUM_NAME)}")
        return 0
    except (OSError, WindowsBuildError) as error:
        print(f"Windows release build failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
