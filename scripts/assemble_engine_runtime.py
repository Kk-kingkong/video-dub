#!/usr/bin/env python3
"""Build an integrity-checked private LocalTube Dub Python runtime.

This is a release-builder tool. Customer installers receive the completed runtime
and never execute this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping


ROOT_DIR = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT_DIR / "packaging" / "runtime-manifest.json"
SUPPORTED_PLATFORMS = {"macos", "windows"}
SUPPORTED_ARCHITECTURES = {"arm64", "x64"}
SUPPORTED_ARCHITECTURES_BY_PLATFORM = {
    "macos": {"arm64", "x64"},
    "windows": {"x64"},
}
RUNTIME_LOCK_SCHEMA_VERSION = 2
TREE_DIGEST_FORMAT_VERSION = 1
TREE_DIGEST_EXCLUSIONS = [
    "runtime-lock.json",
    "**/__pycache__/**",
    "**/*.pyc",
]
ArtifactFetcher = Callable[[Mapping[str, Any]], bytes]


class RuntimeAssemblyError(RuntimeError):
    pass


def normalize_architecture(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "arm64": "arm64",
        "aarch64": "arm64",
        "x86_64": "x64",
        "amd64": "x64",
        "x64": "x64",
    }
    if normalized not in aliases:
        raise RuntimeAssemblyError(f"unsupported architecture: {value}")
    return aliases[normalized]


def _require_https_artifact(artifact: Mapping[str, Any], label: str) -> None:
    url = str(artifact.get("url") or "")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise RuntimeAssemblyError(f"{label} must use an HTTPS URL")
    if not str(artifact.get("name") or ""):
        raise RuntimeAssemblyError(f"{label} is missing a filename")
    try:
        size = int(artifact.get("bytes"))
    except (TypeError, ValueError) as error:
        raise RuntimeAssemblyError(f"{label} is missing an exact byte size") from error
    if size <= 0:
        raise RuntimeAssemblyError(f"{label} has an invalid byte size")
    digest = str(artifact.get("sha256") or "").lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise RuntimeAssemblyError(f"{label} is missing a SHA-256 digest")


def load_runtime_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeAssemblyError(f"cannot read runtime manifest: {path}") from error
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise RuntimeAssemblyError("runtime manifest schemaVersion must be 1")
    if set(manifest) != {"schemaVersion", "runtimeName", "modelManifest", "platforms", "packages"}:
        raise RuntimeAssemblyError("runtime manifest has unsupported or missing top-level keys")
    model_manifest = manifest.get("modelManifest")
    if not isinstance(model_manifest, dict) or set(model_manifest) != {"id", "version", "archiveSha256"}:
        raise RuntimeAssemblyError("runtime manifest must identify the reviewed Kokoro model manifest")
    if not str(model_manifest.get("id") or "") or not str(model_manifest.get("version") or ""):
        raise RuntimeAssemblyError("runtime model manifest identity is incomplete")
    model_digest = str(model_manifest.get("archiveSha256") or "").lower()
    if len(model_digest) != 64 or any(character not in "0123456789abcdef" for character in model_digest):
        raise RuntimeAssemblyError("runtime model manifest identity has an invalid SHA-256")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != SUPPORTED_PLATFORMS:
        raise RuntimeAssemblyError("runtime manifest must support exactly macos and windows")
    for platform_name, expected_architectures in SUPPORTED_ARCHITECTURES_BY_PLATFORM.items():
        target_platform = platforms.get(platform_name)
        if not isinstance(target_platform, dict) or not isinstance(target_platform.get("architectures"), dict):
            raise RuntimeAssemblyError(f"runtime manifest is missing {platform_name} architecture data")
        if set(target_platform["architectures"]) != expected_architectures:
            expected = ", ".join(sorted(expected_architectures))
            raise RuntimeAssemblyError(
                f"runtime manifest {platform_name} architectures must be exactly: {expected}"
            )
    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise RuntimeAssemblyError("runtime manifest is missing pinned Python packages")
    seen_packages: set[str] = set()
    for package in packages:
        if not isinstance(package, dict):
            raise RuntimeAssemblyError("runtime package entry must be an object")
        package_id = str(package.get("id") or "")
        if not package_id or package_id in seen_packages or not str(package.get("version") or ""):
            raise RuntimeAssemblyError("runtime package entries require unique id and version")
        seen_packages.add(package_id)
        artifact = package.get("artifact")
        artifacts = package.get("artifacts")
        platform_artifacts = package.get("platformArtifacts")
        if artifact is not None and (artifacts is not None or platform_artifacts is not None):
            raise RuntimeAssemblyError(f"runtime package {package_id} cannot use both artifact forms")
        if artifact is not None:
            if not isinstance(artifact, dict):
                raise RuntimeAssemblyError(f"runtime package {package_id} artifact is invalid")
            _require_https_artifact(artifact, f"runtime package {package_id}")
        elif (
            isinstance(artifacts, dict)
            and set(artifacts) == SUPPORTED_ARCHITECTURES_BY_PLATFORM["macos"]
            and isinstance(platform_artifacts, dict)
            and set(platform_artifacts) == {"windows"}
            and isinstance(platform_artifacts.get("windows"), dict)
            and set(platform_artifacts["windows"]) == SUPPORTED_ARCHITECTURES_BY_PLATFORM["windows"]
        ):
            for architecture, item in artifacts.items():
                if not isinstance(item, dict):
                    raise RuntimeAssemblyError(f"runtime package {package_id}/macos/{architecture} artifact is invalid")
                _require_https_artifact(item, f"runtime package {package_id}/macos/{architecture}")
            for architecture, item in platform_artifacts["windows"].items():
                if not isinstance(item, dict):
                    raise RuntimeAssemblyError(f"runtime package {package_id}/windows/{architecture} artifact is invalid")
                _require_https_artifact(item, f"runtime package {package_id}/windows/{architecture}")
        else:
            raise RuntimeAssemblyError(
                f"runtime package {package_id} is missing complete macos and windows artifacts"
            )
    for platform_name, platform_payload in platforms.items():
        for architecture, target in platform_payload["architectures"].items():
            if not isinstance(target, dict):
                raise RuntimeAssemblyError(f"runtime manifest target {platform_name}/{architecture} is invalid")
            python_artifact = target.get("python")
            if not isinstance(python_artifact, dict):
                raise RuntimeAssemblyError(
                    f"runtime manifest is missing Python for {platform_name}/{architecture}"
                )
            _require_https_artifact(python_artifact, f"Python {platform_name}/{architecture}")
            executables = target.get("executables")
            if not isinstance(executables, list) or not executables:
                raise RuntimeAssemblyError(
                    f"runtime manifest is missing executables for {platform_name}/{architecture}"
                )
            for executable in executables:
                if not isinstance(executable, dict) or not str(executable.get("installAs") or ""):
                    raise RuntimeAssemblyError(
                        f"runtime executable for {platform_name}/{architecture} is invalid"
                    )
                _require_https_artifact(
                    executable, f"runtime executable {platform_name}/{architecture}"
                )
    return manifest


def _artifact_path(cache_dir: Path, artifact: Mapping[str, Any]) -> Path:
    artifact_name = Path(str(artifact["name"])).name
    if artifact_name != artifact["name"]:
        raise RuntimeAssemblyError("artifact filename must not contain a path")
    return cache_dir / artifact_name


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, message: str, headers: Any, newurl: str) -> Any:
        if urllib.parse.urlsplit(newurl).scheme.lower() != "https":
            raise RuntimeAssemblyError("artifact redirect left HTTPS")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def _verify_bytes(payload: bytes, artifact: Mapping[str, Any]) -> None:
    expected_size = int(artifact["bytes"])
    if len(payload) != expected_size:
        raise RuntimeAssemblyError(f"artifact byte size mismatch for {artifact['name']}: expected {expected_size}, got {len(payload)}")
    actual_digest = hashlib.sha256(payload).hexdigest()
    if actual_digest != str(artifact["sha256"]).lower():
        raise RuntimeAssemblyError(f"artifact SHA-256 mismatch for {artifact['name']}")


def fetch_artifact(artifact: Mapping[str, Any], cache_dir: Path, fetcher: ArtifactFetcher | None = None, *, testing: bool = False) -> Path:
    if fetcher is not None and not testing:
        raise RuntimeAssemblyError("custom artifact fetchers are allowed only in self-tests")
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = _artifact_path(cache_dir, artifact)
    if target.is_file():
        payload = target.read_bytes()
        try:
            _verify_bytes(payload, artifact)
            return target
        except RuntimeAssemblyError:
            target.unlink()
    if fetcher is not None:
        payload = fetcher(artifact)
    else:
        opener = urllib.request.build_opener(_HttpsOnlyRedirect())
        request = urllib.request.Request(str(artifact["url"]), headers={"User-Agent": "LocalTube-Dub-release-builder/1"})
        try:
            with opener.open(request, timeout=90) as response:
                if urllib.parse.urlsplit(response.geturl()).scheme.lower() != "https":
                    raise RuntimeAssemblyError("artifact redirect left HTTPS")
                payload = response.read()
        except OSError as error:
            raise RuntimeAssemblyError(f"unable to download {artifact['name']}: {error}") from error
    _verify_bytes(payload, artifact)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
    temporary.write_bytes(payload)
    os.replace(temporary, target)
    return target


def _safe_member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts:
        raise RuntimeAssemblyError(f"unsafe archive path: {name}")
    return path


def _safe_link_target(member_path: PurePosixPath, value: str) -> None:
    target = PurePosixPath(value)
    if not value or target.is_absolute():
        raise RuntimeAssemblyError(f"unsafe archive link target: {value}")
    parts: list[str] = list(member_path.parts[:-1])
    for part in target.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise RuntimeAssemblyError(f"unsafe archive link target: {value}")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise RuntimeAssemblyError(f"unsafe archive link target: {value}")


def extract_python_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            members = archive.getmembers()
            for member in members:
                path = _safe_member_path(member.name)
                if member.isdev() or member.islnk():
                    raise RuntimeAssemblyError(f"unsafe archive member type: {path}")
                if member.issym():
                    _safe_link_target(path, member.linkname)
                if not (member.isdir() or member.isfile() or member.issym()):
                    raise RuntimeAssemblyError(f"unsupported archive member type: {path}")
            for member in members:
                path = _safe_member_path(member.name)
                output = destination.joinpath(*path.parts)
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                if member.issym():
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.unlink(missing_ok=True)
                    output.symlink_to(member.linkname)
                    continue
                output.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise RuntimeAssemblyError(f"could not extract archive member: {path}")
                with source, output.open("wb") as target:
                    shutil.copyfileobj(source, target)
                output.chmod(member.mode & 0o777)
    except (tarfile.TarError, OSError) as error:
        if isinstance(error, RuntimeAssemblyError):
            raise
        raise RuntimeAssemblyError(f"cannot extract Python archive: {error}") from error


def _artifact_for_architecture(
    package: Mapping[str, Any],
    platform: str,
    architecture: str,
) -> Mapping[str, Any]:
    if isinstance(package.get("artifact"), dict):
        return package["artifact"]
    platform_artifacts = package.get("platformArtifacts")
    if (
        isinstance(platform_artifacts, dict)
        and isinstance(platform_artifacts.get(platform), dict)
        and isinstance(platform_artifacts[platform].get(architecture), dict)
    ):
        return platform_artifacts[platform][architecture]
    artifacts = package.get("artifacts")
    if (
        platform != "macos"
        or not isinstance(artifacts, dict)
        or not isinstance(artifacts.get(architecture), dict)
    ):
        raise RuntimeAssemblyError(
            f"runtime package {package.get('id')} lacks {platform}/{architecture} artifact"
        )
    return artifacts[architecture]


def _runtime_python(runtime_dir: Path, platform: str) -> Path:
    candidate = (
        runtime_dir / "python.exe"
        if platform == "windows"
        else runtime_dir / "bin" / "python"
    )
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeAssemblyError(f"private runtime is missing {candidate.relative_to(runtime_dir)}")
    return candidate


def _install_wheels(python_bin: Path, wheels: list[Path], *, testing: bool) -> None:
    if testing:
        return
    command = [
        str(python_bin),
        "-m",
        "pip",
        "install",
        "--no-index",
        "--no-deps",
        "--disable-pip-version-check",
        "--no-warn-script-location",
        *[str(wheel) for wheel in wheels],
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "pip failed").strip()
        raise RuntimeAssemblyError(f"offline wheel installation failed: {detail}")


def _make_unix_python_entrypoints_relocatable(runtime_dir: Path, platform: str) -> None:
    if platform == "windows":
        return
    runtime_bin = runtime_dir / "bin"
    for command in sorted(runtime_bin.iterdir()):
        if command.is_symlink() or not command.is_file():
            continue
        payload = command.read_bytes()
        first_line, separator, body = payload.partition(b"\n")
        if not separator or not first_line.startswith(b"#!"):
            continue
        interpreter = first_line[2:].decode("utf-8", errors="replace").strip().split(maxsplit=1)[0]
        if not interpreter.startswith("/") or not Path(interpreter).name.lower().startswith("python"):
            continue

        entrypoint = runtime_bin / f".{command.name}.entrypoint.py"
        if entrypoint.exists():
            raise RuntimeAssemblyError(f"private runtime entrypoint collision: {entrypoint.name}")
        original_mode = command.stat().st_mode
        os.replace(command, entrypoint)
        entrypoint.write_bytes(b"#!/usr/bin/env python3\n" + body)
        entrypoint.chmod(original_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
        command.write_text(
            "#!/bin/sh\n"
            'SCRIPT_DIR=$(CDPATH= cd -P "$(dirname "$0")" >/dev/null 2>&1 && pwd)\n'
            f'exec "$SCRIPT_DIR/python" "$SCRIPT_DIR/{entrypoint.name}" "$@"\n',
            encoding="utf-8",
        )
        command.chmod(original_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _write_sitecustomize(runtime_dir: Path, platform: str) -> None:
    python_bin = _runtime_python(runtime_dir, platform)
    version = subprocess.run(
        [str(python_bin), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
        text=True,
        check=False,
    )
    if version.returncode != 0:
        raise RuntimeAssemblyError("private Python cannot report its version")
    if platform == "windows":
        site_packages = runtime_dir / "Lib" / "site-packages"
    else:
        site_packages = runtime_dir / "lib" / f"python{version.stdout.strip()}" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    (site_packages / "sitecustomize.py").write_text(
        "# Keep the bundled media tools discoverable when launchd starts Python.\n"
        "import os\n"
        "import sys\n"
        "_runtime_bin = os.path.dirname(os.path.realpath(sys.executable))\n"
        "_path = os.environ.get('PATH', '')\n"
        "if _runtime_bin not in _path.split(os.pathsep):\n"
        "    os.environ['PATH'] = _runtime_bin + (os.pathsep + _path if _path else '')\n",
        encoding="utf-8",
    )


def _remove_runtime_caches(runtime_dir: Path) -> None:
    for cache_directory in runtime_dir.rglob("__pycache__"):
        shutil.rmtree(cache_directory, ignore_errors=True)
    for bytecode in runtime_dir.rglob("*.pyc"):
        bytecode.unlink(missing_ok=True)


def _tree_entry_is_excluded(relative_path: PurePosixPath) -> bool:
    if relative_path == PurePosixPath("runtime-lock.json"):
        return True
    if "__pycache__" in relative_path.parts:
        return True
    return relative_path.suffix == ".pyc"


def runtime_tree_sha256(runtime_dir: Path) -> str:
    runtime_dir = runtime_dir.expanduser().resolve()
    if not runtime_dir.is_dir():
        raise RuntimeAssemblyError(f"private runtime directory is missing: {runtime_dir}")
    digest = hashlib.sha256()
    entries = sorted(runtime_dir.rglob("*"), key=lambda item: item.relative_to(runtime_dir).as_posix())
    for entry in entries:
        relative = PurePosixPath(entry.relative_to(runtime_dir).as_posix())
        if _tree_entry_is_excluded(relative):
            continue
        encoded_path = relative.as_posix().encode("utf-8")
        if entry.is_symlink():
            target = os.readlink(entry).encode("utf-8")
            digest.update(b"L\0" + encoded_path + b"\0" + target + b"\0")
            continue
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise RuntimeAssemblyError(f"unsupported runtime tree entry: {relative}")
        size = entry.stat().st_size
        digest.update(b"F\0" + encoded_path + b"\0" + str(size).encode("ascii") + b"\0")
        with entry.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _selected_artifacts(
    manifest: Mapping[str, Any],
    platform: str,
    architecture: str,
) -> list[Mapping[str, Any]]:
    target = manifest["platforms"][platform]["architectures"][architecture]
    artifacts: list[Mapping[str, Any]] = [target["python"]]
    artifacts.extend(
        _artifact_for_architecture(package, platform, architecture)
        for package in manifest["packages"]
    )
    artifacts.extend(target["executables"])
    return artifacts


def _artifact_contract(artifacts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "name": item["name"],
            "url": item["url"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in artifacts
    ]


def _package_contract(manifest: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"id": str(item["id"]), "version": str(item["version"])}
        for item in manifest["packages"]
    ]


def _write_runtime_lock(runtime_dir: Path, manifest: Mapping[str, Any], platform: str, architecture: str, artifacts: list[Mapping[str, Any]]) -> None:
    lock = {
        "schemaVersion": RUNTIME_LOCK_SCHEMA_VERSION,
        "bundledRuntime": True,
        "platform": platform,
        "architecture": architecture,
        "pythonExecutable": "python.exe" if platform == "windows" else "bin/python",
        "pythonVersion": manifest["platforms"][platform]["architectures"][architecture]["pythonVersion"],
        "artifacts": _artifact_contract(artifacts),
        "packages": _package_contract(manifest),
        "modelManifest": dict(manifest["modelManifest"]),
        "installedTree": {
            "algorithm": "sha256",
            "formatVersion": TREE_DIGEST_FORMAT_VERSION,
            "digest": runtime_tree_sha256(runtime_dir),
            "excluded": TREE_DIGEST_EXCLUSIONS,
        },
    }
    (runtime_dir / "runtime-lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeAssemblyError(f"{label} is missing or invalid: {path}") from error
    if not isinstance(payload, dict):
        raise RuntimeAssemblyError(f"{label} must be a JSON object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as error:
        raise RuntimeAssemblyError(f"cannot read integrity file: {path}") from error
    return digest.hexdigest()


def _validate_contract_list(value: Any, required_keys: set[str], label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise RuntimeAssemblyError(f"{label} must be a non-empty list")
    records: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != required_keys:
            raise RuntimeAssemblyError(f"{label} contains an invalid record")
        records.append(item)
    return records


def verify_runtime_contract(
    runtime_dir: Path,
    release_metadata: Mapping[str, Any],
    expected_platform: str,
    expected_architecture: str,
) -> dict[str, Any]:
    expected_architecture = normalize_architecture(expected_architecture)
    if expected_platform not in SUPPORTED_PLATFORMS:
        raise RuntimeAssemblyError(f"unsupported platform: {expected_platform}")
    if (
        release_metadata.get("bundledRuntime") is not True
        or release_metadata.get("platform") != expected_platform
        or release_metadata.get("architecture") != expected_architecture
        or release_metadata.get("runtimeLock") != ".venv/runtime-lock.json"
    ):
        raise RuntimeAssemblyError("release metadata does not match this bundled runtime")
    contract = release_metadata.get("runtimeContract")
    required_contract_keys = {
        "schemaVersion",
        "lockSha256",
        "treeSha256",
        "pythonVersion",
        "packages",
        "artifacts",
        "modelManifest",
    }
    if not isinstance(contract, dict) or set(contract) != required_contract_keys or contract.get("schemaVersion") != 1:
        raise RuntimeAssemblyError("release metadata has an invalid runtime contract")

    runtime_dir = runtime_dir.expanduser().resolve()
    lock_path = runtime_dir / "runtime-lock.json"
    if _sha256_file(lock_path) != str(contract.get("lockSha256") or ""):
        raise RuntimeAssemblyError("runtime lock integrity verification failed")
    lock = _load_json_object(lock_path, "runtime lock")
    required_lock_keys = {
        "schemaVersion",
        "bundledRuntime",
        "platform",
        "architecture",
        "pythonExecutable",
        "pythonVersion",
        "artifacts",
        "packages",
        "modelManifest",
        "installedTree",
    }
    if set(lock) != required_lock_keys or lock.get("schemaVersion") != RUNTIME_LOCK_SCHEMA_VERSION:
        raise RuntimeAssemblyError("runtime lock schema is invalid")
    if (
        lock.get("bundledRuntime") is not True
        or lock.get("platform") != expected_platform
        or lock.get("architecture") != expected_architecture
        or lock.get("pythonExecutable")
        != ("python.exe" if expected_platform == "windows" else "bin/python")
        or lock.get("pythonVersion") != contract.get("pythonVersion")
    ):
        raise RuntimeAssemblyError("runtime lock platform, architecture, or Python version is invalid")

    packages = _validate_contract_list(lock.get("packages"), {"id", "version"}, "runtime packages")
    artifacts = _validate_contract_list(lock.get("artifacts"), {"name", "url", "bytes", "sha256"}, "runtime artifacts")
    if packages != contract.get("packages") or artifacts != contract.get("artifacts"):
        raise RuntimeAssemblyError("runtime lock does not match the pinned package and artifact contract")
    package_ids = [str(item["id"]) for item in packages]
    if len(package_ids) != len(set(package_ids)):
        raise RuntimeAssemblyError("runtime package contract contains duplicate package identifiers")
    if lock.get("modelManifest") != contract.get("modelManifest"):
        raise RuntimeAssemblyError("runtime lock does not match the reviewed model manifest identity")

    installed_tree = lock.get("installedTree")
    if (
        not isinstance(installed_tree, dict)
        or set(installed_tree) != {"algorithm", "formatVersion", "digest", "excluded"}
        or installed_tree.get("algorithm") != "sha256"
        or installed_tree.get("formatVersion") != TREE_DIGEST_FORMAT_VERSION
        or installed_tree.get("excluded") != TREE_DIGEST_EXCLUSIONS
        or installed_tree.get("digest") != contract.get("treeSha256")
    ):
        raise RuntimeAssemblyError("runtime lock has an invalid installed-tree contract")
    actual_tree_digest = runtime_tree_sha256(runtime_dir)
    if actual_tree_digest != installed_tree["digest"]:
        raise RuntimeAssemblyError("installed runtime tree integrity verification failed")

    python_bin = _runtime_python(runtime_dir, expected_platform)
    ffmpeg_bin = (
        runtime_dir / "ffmpeg.exe"
        if expected_platform == "windows"
        else runtime_dir / "bin" / "ffmpeg"
    )
    if not ffmpeg_bin.is_file() or not os.access(ffmpeg_bin, os.X_OK):
        raise RuntimeAssemblyError(
            f"private runtime is missing {ffmpeg_bin.relative_to(runtime_dir)}"
        )
    probe = subprocess.run(
        [
            str(python_bin),
            "-I",
            "-c",
            (
                "import importlib.metadata,json,platform,sys;"
                "expected=json.loads(sys.argv[1]);"
                "arch={'aarch64':'arm64','arm64':'arm64','amd64':'x64','x86_64':'x64'}.get(platform.machine().lower());"
                "actual={item['id']:importlib.metadata.version(item['id']) for item in expected['packages']};"
                "raise SystemExit(0 if platform.python_version()==expected['pythonVersion'] "
                "and arch==expected['architecture'] "
                "and actual=={item['id']:item['version'] for item in expected['packages']} else 1)"
            ),
            json.dumps(
                {
                    "pythonVersion": lock["pythonVersion"],
                    "architecture": expected_architecture,
                    "packages": packages,
                },
                separators=(",", ":"),
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout or "version mismatch").strip()
        raise RuntimeAssemblyError(f"installed Python package verification failed: {detail}")
    return lock


def assemble_runtime(
    manifest: Mapping[str, Any],
    platform: str,
    architecture: str,
    output: Path,
    cache_dir: Path,
    *,
    fetcher: ArtifactFetcher | None = None,
    testing: bool = False,
) -> Path:
    if platform not in SUPPORTED_PLATFORMS:
        raise RuntimeAssemblyError(f"unsupported platform: {platform}")
    architecture = normalize_architecture(architecture)
    if architecture not in SUPPORTED_ARCHITECTURES_BY_PLATFORM[platform]:
        raise RuntimeAssemblyError(f"unsupported architecture for {platform}: {architecture}")
    target = manifest["platforms"][platform]["architectures"][architecture]
    artifact_records = _selected_artifacts(manifest, platform, architecture)
    fetched = [fetch_artifact(artifact, cache_dir, fetcher, testing=testing) for artifact in artifact_records]
    python_archive = fetched[0]
    wheel_paths = fetched[1 : 1 + len(manifest["packages"])]
    executable_paths = fetched[1 + len(manifest["packages"]) :]

    output = output.expanduser().resolve()
    staging = output.with_name(f".{output.name}.staging-{uuid.uuid4().hex}")
    backup = output.with_name(f".{output.name}.backup-{uuid.uuid4().hex}")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        extracted = staging / "extracted"
        extract_python_archive(python_archive, extracted)
        python_root = extracted / "python"
        if not python_root.is_dir():
            raise RuntimeAssemblyError("Python archive must contain a top-level python directory")
        runtime_dir = staging / "runtime"
        shutil.move(str(python_root), runtime_dir)
        _install_wheels(_runtime_python(runtime_dir, platform), wheel_paths, testing=testing)
        _make_unix_python_entrypoints_relocatable(runtime_dir, platform)
        for artifact, executable_path in zip(target["executables"], executable_paths):
            target_path = (
                runtime_dir / str(artifact["installAs"])
                if platform == "windows"
                else runtime_dir / "bin" / str(artifact["installAs"])
            )
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(executable_path, target_path)
            target_path.chmod(target_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if not testing:
            _write_sitecustomize(runtime_dir, platform)
        _remove_runtime_caches(runtime_dir)
        _write_runtime_lock(runtime_dir, manifest, platform, architecture, artifact_records)
        if output.exists():
            os.replace(output, backup)
        os.replace(runtime_dir, output)
        shutil.rmtree(backup, ignore_errors=True)
        return output
    except Exception:
        if not output.exists() and backup.exists():
            os.replace(backup, output)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


def _synthetic_artifact(name: str, content: bytes) -> dict[str, Any]:
    return {
        "name": name,
        "url": f"https://fixtures.local/{name}",
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def run_self_test(output: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="localtube-runtime-fixtures.") as temporary:
        root = Path(temporary)
        python_tree = root / "python"
        (python_tree / "bin").mkdir(parents=True)
        (python_tree / "lib").mkdir()
        (python_tree / "lib" / "marker.txt").write_text("runtime-library\n", encoding="utf-8")
        (python_tree / "other-lib").mkdir()
        (python_tree / "other-lib" / "marker.txt").write_text("other-library\n", encoding="utf-8")
        (python_tree / "current-lib").symlink_to("lib", target_is_directory=True)
        python_binary = python_tree / "bin" / "python"
        python_binary.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        python_binary.chmod(0o755)
        fixture_command = python_tree / "bin" / "fixture-cli"
        fixture_command.write_text(
            "#!/deleted/build/runtime/bin/python\n"
            "print('fixture command')\n",
            encoding="utf-8",
        )
        fixture_command.chmod(0o755)
        archive = root / "python.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(python_tree, arcname="python")
        archive_payload = archive.read_bytes()
        wheel_payload = b"PK\\x03\\x04synthetic-wheel"
        ffmpeg_payload = b"#!/usr/bin/env sh\nexit 0\n"
        python_artifact = _synthetic_artifact("python.tar.gz", archive_payload)
        wheel_artifact = _synthetic_artifact("example-1.0-py3-none-any.whl", wheel_payload)
        binary_artifact = _synthetic_artifact("ffmpeg", ffmpeg_payload)
        fixture_bytes = {item["name"]: data for item, data in ((python_artifact, archive_payload), (wheel_artifact, wheel_payload), (binary_artifact, ffmpeg_payload))}
        manifest = {
            "schemaVersion": 1,
            "runtimeName": "Synthetic private runtime",
            "modelManifest": {
                "id": "synthetic-kokoro",
                "version": "test",
                "archiveSha256": "1" * 64,
            },
            "platforms": {
                "macos": {
                    "architectures": {
                        architecture: {"pythonVersion": "3.11.test", "python": python_artifact, "executables": [{**binary_artifact, "installAs": "ffmpeg"}]}
                        for architecture in sorted(SUPPORTED_ARCHITECTURES_BY_PLATFORM["macos"])
                    }
                },
                "windows": {
                    "architectures": {
                        "x64": {
                            "pythonVersion": "3.11.test",
                            "python": python_artifact,
                            "executables": [{**binary_artifact, "installAs": "ffmpeg.exe"}],
                        }
                    }
                }
            },
            "packages": [{"id": "example", "version": "1.0", "artifact": wheel_artifact}],
        }
        invalid = json.loads(json.dumps(manifest))
        invalid["platforms"]["macos"]["architectures"]["arm64"]["python"]["url"] = "http://invalid.local/python.tar.gz"
        try:
            load_runtime_manifest_from_payload(invalid)
        except RuntimeAssemblyError:
            pass
        else:
            raise RuntimeAssemblyError("self-test did not reject non-HTTPS artifacts")
        result = assemble_runtime(
            load_runtime_manifest_from_payload(manifest),
            "macos",
            "aarch64",
            output,
            root / "cache",
            fetcher=lambda artifact: fixture_bytes[str(artifact["name"])],
            testing=True,
        )
        lock = json.loads((result / "runtime-lock.json").read_text(encoding="utf-8"))
        if lock.get("schemaVersion") != 2:
            raise RuntimeAssemblyError("self-test runtime lock schema is not integrity-enforcing")
        if lock.get("architecture") != "arm64" or lock.get("pythonExecutable") != "bin/python":
            raise RuntimeAssemblyError("self-test runtime lock is invalid")
        if lock.get("packages") != [{"id": "example", "version": "1.0"}]:
            raise RuntimeAssemblyError("self-test runtime lock does not contain the complete package contract")
        if lock.get("modelManifest") != manifest["modelManifest"]:
            raise RuntimeAssemblyError("self-test runtime lock does not identify the Kokoro model manifest")
        installed_tree = lock.get("installedTree")
        if (
            not isinstance(installed_tree, dict)
            or installed_tree.get("algorithm") != "sha256"
            or len(str(installed_tree.get("digest") or "")) != 64
        ):
            raise RuntimeAssemblyError("self-test runtime lock is missing the installed-tree digest")
        if runtime_tree_sha256(result) != installed_tree["digest"]:
            raise RuntimeAssemblyError("self-test installed-tree digest does not reproduce")
        current_library = result / "current-lib"
        current_library.unlink()
        current_library.symlink_to("other-lib", target_is_directory=True)
        if runtime_tree_sha256(result) == installed_tree["digest"]:
            raise RuntimeAssemblyError("self-test installed-tree digest ignored a directory symlink")
        current_library.unlink()
        current_library.symlink_to("lib", target_is_directory=True)
        (result / "bin" / "ffmpeg").write_bytes(ffmpeg_payload + b"tampered")
        if runtime_tree_sha256(result) == installed_tree["digest"]:
            raise RuntimeAssemblyError("self-test installed-tree digest did not detect tampering")
        if not (result / "bin" / "python").is_file() or not (result / "bin" / "ffmpeg").is_file():
            raise RuntimeAssemblyError("self-test runtime is incomplete")
        relocated_command = result / "bin" / "fixture-cli"
        relocated_payload = relocated_command.read_text(encoding="utf-8")
        relocated_entrypoint = result / "bin" / ".fixture-cli.entrypoint.py"
        if "$SCRIPT_DIR/python" not in relocated_payload or not relocated_entrypoint.is_file():
            raise RuntimeAssemblyError("self-test Python entrypoint is not relocatable")
        if b"/deleted/build" in relocated_entrypoint.read_bytes():
            raise RuntimeAssemblyError("self-test Python entrypoint retained its build-time interpreter")
        relocated_probe = subprocess.run(
            [str(relocated_command), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if relocated_probe.returncode != 0:
            raise RuntimeAssemblyError("self-test relocated Python entrypoint is not executable")
        unsafe_archive = root / "unsafe.tar.gz"
        with tarfile.open(unsafe_archive, "w:gz") as tar:
            bad = root / "bad"
            bad.write_text("bad", encoding="utf-8")
            tar.add(bad, arcname="../bad")
        try:
            extract_python_archive(unsafe_archive, root / "unsafe-output")
        except RuntimeAssemblyError:
            pass
        else:
            raise RuntimeAssemblyError("self-test did not reject unsafe archive paths")


def load_runtime_manifest_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="localtube-runtime-manifest.") as temporary:
        manifest_path = Path(temporary) / "runtime-manifest.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        return load_runtime_manifest(manifest_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assemble a pinned LocalTube Dub private runtime")
    parser.add_argument("--platform", choices=sorted(SUPPORTED_PLATFORMS))
    parser.add_argument("--arch")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-runtime", type=Path)
    parser.add_argument("--release-metadata", type=Path)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "localtube-dub" / "runtime")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.output is None:
            parser.error("--self-test requires --output")
        if args.platform is not None or args.arch is not None or args.verify_runtime is not None or args.release_metadata is not None:
            parser.error("--self-test accepts only --output")
    elif args.verify_runtime is not None:
        if args.output is not None or args.platform is None or args.arch is None or args.release_metadata is None:
            parser.error("--verify-runtime requires --platform, --arch, and --release-metadata")
    elif args.output is None or args.platform is None or args.arch is None or args.release_metadata is not None:
        parser.error("assembly requires --output, --platform, and --arch")
    return args


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            run_self_test(args.output)
            print(json.dumps({"ok": True, "selfTest": "runtime-assembly"}))
            return
        if args.verify_runtime is not None:
            release = _load_json_object(args.release_metadata, "release metadata")
            lock = verify_runtime_contract(args.verify_runtime, release, args.platform, args.arch)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "platform": lock["platform"],
                        "architecture": lock["architecture"],
                        "pythonVersion": lock["pythonVersion"],
                        "packages": len(lock["packages"]),
                    }
                )
            )
            return
        manifest = load_runtime_manifest()
        output = assemble_runtime(manifest, args.platform, args.arch, args.output, args.cache)
        print(json.dumps({"ok": True, "platform": args.platform, "architecture": normalize_architecture(args.arch), "output": str(output)}))
    except RuntimeAssemblyError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
