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
SUPPORTED_PLATFORMS = {"macos"}
SUPPORTED_ARCHITECTURES = {"arm64", "x64"}
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
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict) or set(platforms) != SUPPORTED_PLATFORMS:
        raise RuntimeAssemblyError("runtime manifest must support exactly the macos platform")
    macos = platforms.get("macos")
    if not isinstance(macos, dict) or not isinstance(macos.get("architectures"), dict):
        raise RuntimeAssemblyError("runtime manifest is missing macOS architecture data")
    if set(macos["architectures"]) != SUPPORTED_ARCHITECTURES:
        raise RuntimeAssemblyError("runtime manifest must contain arm64 and x64 architectures")
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
        if artifact is not None and artifacts is not None:
            raise RuntimeAssemblyError(f"runtime package {package_id} cannot use both artifact forms")
        if artifact is not None:
            if not isinstance(artifact, dict):
                raise RuntimeAssemblyError(f"runtime package {package_id} artifact is invalid")
            _require_https_artifact(artifact, f"runtime package {package_id}")
        elif isinstance(artifacts, dict) and set(artifacts) == SUPPORTED_ARCHITECTURES:
            for architecture, item in artifacts.items():
                if not isinstance(item, dict):
                    raise RuntimeAssemblyError(f"runtime package {package_id}/{architecture} artifact is invalid")
                _require_https_artifact(item, f"runtime package {package_id}/{architecture}")
        else:
            raise RuntimeAssemblyError(f"runtime package {package_id} is missing architecture artifacts")
    for architecture, target in macos["architectures"].items():
        if not isinstance(target, dict):
            raise RuntimeAssemblyError(f"runtime manifest target macos/{architecture} is invalid")
        python_artifact = target.get("python")
        if not isinstance(python_artifact, dict):
            raise RuntimeAssemblyError(f"runtime manifest is missing Python for macos/{architecture}")
        _require_https_artifact(python_artifact, f"Python macos/{architecture}")
        executables = target.get("executables")
        if not isinstance(executables, list) or not executables:
            raise RuntimeAssemblyError(f"runtime manifest is missing executables for macos/{architecture}")
        for executable in executables:
            if not isinstance(executable, dict) or not str(executable.get("installAs") or ""):
                raise RuntimeAssemblyError(f"runtime executable for macos/{architecture} is invalid")
            _require_https_artifact(executable, f"runtime executable macos/{architecture}")
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


def _artifact_for_architecture(package: Mapping[str, Any], architecture: str) -> Mapping[str, Any]:
    if isinstance(package.get("artifact"), dict):
        return package["artifact"]
    artifacts = package.get("artifacts")
    if not isinstance(artifacts, dict) or not isinstance(artifacts.get(architecture), dict):
        raise RuntimeAssemblyError(f"runtime package {package.get('id')} lacks {architecture} artifact")
    return artifacts[architecture]


def _runtime_python(runtime_dir: Path) -> Path:
    candidate = runtime_dir / "bin" / "python"
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise RuntimeAssemblyError("private runtime is missing bin/python")
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


def _write_sitecustomize(runtime_dir: Path) -> None:
    python_bin = _runtime_python(runtime_dir)
    version = subprocess.run(
        [str(python_bin), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        capture_output=True,
        text=True,
        check=False,
    )
    if version.returncode != 0:
        raise RuntimeAssemblyError("private Python cannot report its version")
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


def _write_runtime_lock(runtime_dir: Path, manifest: Mapping[str, Any], platform: str, architecture: str, artifacts: list[Mapping[str, Any]]) -> None:
    lock = {
        "schemaVersion": 1,
        "bundledRuntime": True,
        "platform": platform,
        "architecture": architecture,
        "pythonExecutable": "bin/python",
        "pythonVersion": manifest["platforms"][platform]["architectures"][architecture]["pythonVersion"],
        "artifacts": [
            {
                "name": item["name"],
                "url": item["url"],
                "bytes": item["bytes"],
                "sha256": item["sha256"],
            }
            for item in artifacts
        ],
        "packages": [
            {"id": item["id"], "version": item["version"]}
            for item in manifest["packages"]
        ],
    }
    (runtime_dir / "runtime-lock.json").write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
    if architecture not in SUPPORTED_ARCHITECTURES:
        raise RuntimeAssemblyError(f"unsupported architecture: {architecture}")
    target = manifest["platforms"][platform]["architectures"][architecture]
    artifact_records: list[Mapping[str, Any]] = [target["python"]]
    artifact_records.extend(_artifact_for_architecture(package, architecture) for package in manifest["packages"])
    artifact_records.extend(target["executables"])
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
        _install_wheels(_runtime_python(runtime_dir), wheel_paths, testing=testing)
        for artifact, executable_path in zip(target["executables"], executable_paths):
            target_path = runtime_dir / "bin" / str(artifact["installAs"])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(executable_path, target_path)
            target_path.chmod(target_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        if not testing:
            _write_sitecustomize(runtime_dir)
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
        python_binary = python_tree / "bin" / "python"
        python_binary.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        python_binary.chmod(0o755)
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
            "platforms": {
                "macos": {
                    "architectures": {
                        architecture: {"pythonVersion": "3.11.test", "python": python_artifact, "executables": [{**binary_artifact, "installAs": "ffmpeg"}]}
                        for architecture in sorted(SUPPORTED_ARCHITECTURES)
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
        if lock.get("architecture") != "arm64" or lock.get("pythonExecutable") != "bin/python":
            raise RuntimeAssemblyError("self-test runtime lock is invalid")
        if not (result / "bin" / "python").is_file() or not (result / "bin" / "ffmpeg").is_file():
            raise RuntimeAssemblyError("self-test runtime is incomplete")
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
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "localtube-dub" / "runtime")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if args.platform is not None or args.arch is not None:
            parser.error("--self-test does not accept --platform or --arch")
    elif args.platform is None or args.arch is None:
        parser.error("--platform and --arch are required")
    return args


def main() -> None:
    args = parse_args()
    try:
        if args.self_test:
            run_self_test(args.output)
            print(json.dumps({"ok": True, "selfTest": "runtime-assembly"}))
            return
        manifest = load_runtime_manifest()
        output = assemble_runtime(manifest, args.platform, args.arch, args.output, args.cache)
        print(json.dumps({"ok": True, "platform": args.platform, "architecture": normalize_architecture(args.arch), "output": str(output)}))
    except RuntimeAssemblyError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
