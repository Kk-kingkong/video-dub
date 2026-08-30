#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import importlib.util
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


def fail(message: str) -> None:
    raise SystemExit(message)


def normalized_files(archive: zipfile.ZipFile) -> set[str]:
    return {name for name in archive.namelist() if name and not name.endswith("/")}


def assert_safe_names(names: set[str], label: str) -> None:
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            fail(f"{label} contains an unsafe path: {name}")
        if any(part in (".DS_Store", "__MACOSX", "__pycache__") for part in path.parts):
            fail(f"{label} contains metadata or cache files: {name}")


def runtime_tree_sha256_from_zip(archive: zipfile.ZipFile, root: str) -> str:
    prefix = f"{root}/.venv/"
    entries: list[tuple[str, zipfile.ZipInfo]] = []
    for info in archive.infolist():
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        relative = info.filename[len(prefix) :]
        path = PurePosixPath(relative)
        if relative == "runtime-lock.json" or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        entries.append((relative, info))
    digest = hashlib.sha256()
    for relative, info in sorted(entries, key=lambda item: item[0]):
        payload = archive.read(info)
        mode = (info.external_attr >> 16) & 0xFFFF
        encoded_path = relative.encode("utf-8")
        if stat.S_ISLNK(mode):
            digest.update(b"L\0" + encoded_path + b"\0" + payload + b"\0")
        else:
            digest.update(b"F\0" + encoded_path + b"\0" + str(len(payload)).encode("ascii") + b"\0")
            digest.update(payload)
            digest.update(b"\0")
    return digest.hexdigest()


def selected_artifacts(manifest: dict[str, object], architecture: str) -> list[dict[str, object]]:
    platforms = manifest["platforms"]
    assert isinstance(platforms, dict)
    macos = platforms["macos"]
    assert isinstance(macos, dict)
    architectures = macos["architectures"]
    assert isinstance(architectures, dict)
    target = architectures[architecture]
    assert isinstance(target, dict)
    packages = manifest["packages"]
    assert isinstance(packages, list)
    artifacts = [target["python"]]
    for package in packages:
        assert isinstance(package, dict)
        artifact = package.get("artifact")
        if artifact is None:
            package_artifacts = package["artifacts"]
            assert isinstance(package_artifacts, dict)
            artifact = package_artifacts[architecture]
        artifacts.append(artifact)
    target_executables = target["executables"]
    assert isinstance(target_executables, list)
    artifacts.extend(target_executables)
    return [
        {
            "name": item["name"],
            "url": item["url"],
            "bytes": item["bytes"],
            "sha256": item["sha256"],
        }
        for item in artifacts
        if isinstance(item, dict)
    ]


def kokoro_model_identity(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "KOKORO_MODEL_MANIFEST" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call) or not node.value.args:
            break
        payload = ast.literal_eval(node.value.args[0])
        return {
            "id": str(payload["id"]),
            "version": str(payload["version"]),
            "archiveSha256": str(payload["sha256"]),
        }
    fail("packaged Kokoro source does not contain a readable model manifest")
    raise AssertionError("unreachable")


def verify_extension(path: Path, extension_id: str, expected_version: str, expected_engine_name: str) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = normalized_files(archive)
        assert_safe_names(names, "extension ZIP")
        if "manifest.json" not in names:
            fail("extension ZIP must contain manifest.json at its root")
        if "release-info.json" not in names:
            fail("extension ZIP must contain release-info.json")
        if not {"LICENSE", "THIRD_PARTY_NOTICES.md"}.issubset(names):
            fail("extension ZIP must include its license and third-party notices")
        install_files = {"install.html", "install.css", "install_helpers.js", "install.js"}
        if not install_files.issubset(names):
            fail(f"extension ZIP is missing customer install files: {sorted(install_files - names)}")
        if any(name.endswith((".py", ".pyc", ".sh", ".command", ".env")) for name in names):
            fail("extension ZIP contains a server, installer, or environment file")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("manifest_version") != 3:
            fail("extension ZIP is not Manifest V3")
        if manifest.get("version") != expected_version:
            fail("extension ZIP version does not match the release version")
        if "key" in manifest:
            fail("release manifest must not embed a development extension key")
        release_info = json.loads(archive.read("release-info.json"))
        if release_info.get("channel") not in ("private-beta", "store"):
            fail("extension ZIP release-info has an invalid customer channel")
        if release_info.get("version") != expected_version or release_info.get("extensionId") != extension_id:
            fail("extension ZIP release-info does not match version and extension ID")
        packages = release_info.get("enginePackages")
        expected_packages = {
            ("macos", "arm64"): (
                "macOS Apple Silicon",
                f"LocalTube-Dub-Engine-v{expected_version}-macOS-arm64.zip",
            ),
            ("macos", "x64"): (
                "macOS Intel",
                f"LocalTube-Dub-Engine-v{expected_version}-macOS-x64.zip",
            ),
            ("windows", "x64"): (
                "Windows 10/11 x64",
                f"LocalTube-Dub-Engine-v{expected_version}-Windows-x64.zip",
            ),
        }
        if not isinstance(packages, list):
            fail("extension ZIP release-info must list every supported Engine package")
        actual_packages: dict[tuple[str, str], tuple[str, str]] = {}
        for package in packages:
            if not isinstance(package, dict):
                fail("extension ZIP release-info has an invalid Engine package entry")
            target = (
                str(package.get("platform") or ""),
                str(package.get("architecture") or ""),
            )
            if target in actual_packages:
                fail("extension ZIP release-info has a duplicate Engine target")
            actual_packages[target] = (
                str(package.get("label") or ""),
                str(package.get("bundleName") or ""),
            )
            value = str(package.get("downloadUrl") or "")
            if value and not value.startswith("https://"):
                fail("extension ZIP Engine package URL must use HTTPS")
        if actual_packages != expected_packages:
            fail("extension ZIP release-info must list every supported Engine package")
        if expected_engine_name not in {
            bundle_name for _, bundle_name in expected_packages.values()
        }:
            fail("extension ZIP release-info does not include the verified Engine bundle")
        for key in ("engineDownloadUrl", "supportUrl"):
            value = str(release_info.get(key) or "")
            if value and not value.startswith("https://"):
                fail(f"extension ZIP {key} must use HTTPS")
        download_url = str(release_info.get("engineDownloadUrl") or "")
        if release_info.get("channel") == "store" and not download_url:
            fail("Store extension ZIP must include a platform-neutral Engine download URL")
        if download_url and urlsplit(download_url).path.lower().endswith(".zip"):
            fail("extension ZIP Engine download URL must not target one architecture-specific ZIP")
        if release_info.get("signed") is not False or release_info.get("notarized") is not False:
            fail("private beta extension metadata must match the unsigned Engine bundle")

        install_html = archive.read("install.html").decode("utf-8", errors="replace")
        install_css = archive.read("install.css").decode("utf-8", errors="replace")
        install_js = archive.read("install.js").decode("utf-8", errors="replace")
        if 'data-release-channel="loading"' not in install_html:
            fail("customer install page must start with release content hidden")
        if 'data-audience="customer"' not in install_html or 'data-audience="developer"' not in install_html:
            fail("customer install page must keep customer and developer content separated")
        if 'data-audience="developer"' not in install_css or 'releaseChannel' not in install_js:
            fail("customer install page does not enforce release-channel visibility")
        if "release-info.json" not in install_js or "normalizeReleaseInfo" not in install_js:
            fail("customer install page does not load normalized release metadata")

        required = {manifest.get("action", {}).get("default_popup"), manifest.get("background", {}).get("service_worker")}
        required.update((manifest.get("icons") or {}).values())
        required.update((manifest.get("action", {}).get("default_icon") or {}).values())
        for content_script in manifest.get("content_scripts") or []:
            required.update(content_script.get("js") or [])
            required.update(content_script.get("css") or [])
        for resource_group in manifest.get("web_accessible_resources") or []:
            required.update(resource_group.get("resources") or [])
        missing = sorted(item for item in required if item and item not in names)
        if missing:
            fail(f"extension ZIP is missing manifest-referenced files: {missing}")

        html_missing = []
        for name in names:
            if not name.endswith(".html"):
                continue
            html = archive.read(name).decode("utf-8", errors="replace")
            for reference in re.findall(r"(?:src|href)=[\"']([^\"']+)[\"']", html):
                if reference.startswith(("#", "http://", "https://", "data:")):
                    continue
                clean_reference = reference.split("?", 1)[0].split("#", 1)[0]
                resolved = str(PurePosixPath(name).parent / clean_reference)
                if clean_reference and resolved not in names:
                    html_missing.append(f"{name} -> {resolved}")
        if html_missing:
            fail(f"extension ZIP is missing HTML-referenced files: {sorted(html_missing)}")

        for name in names:
            if name.endswith((".js", ".html", ".css", ".json")):
                text = archive.read(name).decode("utf-8", errors="replace")
                if re.search(r"\bsk-[A-Za-z0-9_-]{16,}\b", text):
                    fail(f"extension ZIP may contain an API key: {name}")
        return {"files": len(names), "version": manifest["version"]}


def verify_engine(
    path: Path,
    extension_id: str,
    expected_version: str,
    runtime_manifest: dict[str, object],
) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        names = normalized_files(archive)
        assert_safe_names(names, "Engine ZIP")
        roots = {PurePosixPath(name).parts[0] for name in names}
        if len(roots) != 1:
            fail("Engine ZIP must contain exactly one top-level folder")
        root = next(iter(roots))
        required = {
            f"{root}/Install LocalTube Dub Engine.command",
            f"{root}/Install No-Caption Whisper.command",
            f"{root}/Uninstall LocalTube Dub Engine.command",
            f"{root}/LICENSE",
            f"{root}/README.md",
            f"{root}/THIRD_PARTY_NOTICES.md",
            f"{root}/release.json",
            f"{root}/server/local_dub_server.py",
            f"{root}/server/kokoro_tts.py",
            f"{root}/.venv/bin/python",
            f"{root}/.venv/runtime-lock.json",
            f"{root}/scripts/assemble_engine_runtime.py",
            f"{root}/scripts/install_engine_deps_macos.sh",
            f"{root}/scripts/install_engine_autostart_macos.sh",
            f"{root}/companion/native_host.py",
            f"{root}/companion/native_host_launcher_macos.sh",
            f"{root}/companion/install_native_host_macos.sh",
            f"{root}/companion/uninstall_native_host_macos.sh",
        }
        missing = sorted(required - names)
        if missing:
            fail(f"Engine ZIP is missing required files: {missing}")
        if any(name.endswith((".pyc", ".DS_Store")) for name in names):
            fail("Engine ZIP contains a Python cache or Finder metadata")
        prohibited_model_names = ("model.int8.onnx", "voices.bin", "kokoro-int8-multi-lang-v1_1.tar.bz2")
        if any(name.endswith(prohibited_model_names) or "/models/kokoro/" in f"/{name}" for name in names):
            fail("Engine ZIP must not contain a Kokoro model archive or activated model files")

        release = json.loads(archive.read(f"{root}/release.json"))
        if release.get("version") != expected_version or release.get("chromeExtensionId") != extension_id:
            fail("Engine release metadata does not match version and extension ID")
        if int(release.get("protocolVersion") or 0) < 2:
            fail("Engine release metadata is missing the required protocol version")
        if release.get("signed") is not False or release.get("notarized") is not False:
            fail("private beta metadata must accurately report unsigned/unnotarized state")
        architecture = str(release.get("architecture") or "")
        if release.get("platform") != "macos" or architecture not in {"arm64", "x64"}:
            fail("Engine release metadata must identify a supported macOS architecture")
        if release.get("bundledRuntime") is not True or release.get("runtimeLock") != ".venv/runtime-lock.json":
            fail("Engine release metadata must identify its bundled private runtime")
        runtime_contract = release.get("runtimeContract")
        contract_keys = {
            "schemaVersion",
            "lockSha256",
            "treeSha256",
            "pythonVersion",
            "packages",
            "artifacts",
            "modelManifest",
        }
        if not isinstance(runtime_contract, dict) or set(runtime_contract) != contract_keys or runtime_contract.get("schemaVersion") != 1:
            fail("Engine release metadata has an invalid runtime integrity contract")
        lock_bytes = archive.read(f"{root}/.venv/runtime-lock.json")
        if hashlib.sha256(lock_bytes).hexdigest() != runtime_contract.get("lockSha256"):
            fail("Engine runtime lock digest does not match release metadata")
        runtime_lock = json.loads(lock_bytes)
        lock_keys = {
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
        if set(runtime_lock) != lock_keys or runtime_lock.get("schemaVersion") != 2:
            fail("Engine runtime lock schema is invalid")
        if (
            runtime_lock.get("bundledRuntime") is not True
            or runtime_lock.get("platform") != "macos"
            or runtime_lock.get("architecture") != architecture
            or runtime_lock.get("pythonExecutable") != "bin/python"
        ):
            fail("Engine runtime lock does not match release platform and architecture")
        manifest_platforms = runtime_manifest["platforms"]
        assert isinstance(manifest_platforms, dict)
        manifest_macos = manifest_platforms["macos"]
        assert isinstance(manifest_macos, dict)
        manifest_architectures = manifest_macos["architectures"]
        assert isinstance(manifest_architectures, dict)
        manifest_target = manifest_architectures[architecture]
        assert isinstance(manifest_target, dict)
        expected_python_version = manifest_target["pythonVersion"]
        manifest_packages = runtime_manifest["packages"]
        assert isinstance(manifest_packages, list)
        expected_packages = [
            {"id": item["id"], "version": item["version"]}
            for item in manifest_packages
            if isinstance(item, dict)
        ]
        expected_artifacts = selected_artifacts(runtime_manifest, architecture)
        expected_model_manifest = runtime_manifest["modelManifest"]
        if (
            runtime_lock.get("pythonVersion") != expected_python_version
            or runtime_lock.get("packages") != expected_packages
            or runtime_lock.get("artifacts") != expected_artifacts
            or runtime_lock.get("modelManifest") != expected_model_manifest
        ):
            fail("Engine runtime lock does not match the reviewed pinned runtime manifest")
        if (
            runtime_contract.get("pythonVersion") != expected_python_version
            or runtime_contract.get("packages") != expected_packages
            or runtime_contract.get("artifacts") != expected_artifacts
            or runtime_contract.get("modelManifest") != expected_model_manifest
        ):
            fail("Engine release runtime contract does not match the reviewed runtime manifest")
        packaged_model_identity = kokoro_model_identity(
            archive.read(f"{root}/server/kokoro_tts.py").decode("utf-8")
        )
        if packaged_model_identity != expected_model_manifest:
            fail("packaged Kokoro source does not match the reviewed model manifest identity")
        installed_tree = runtime_lock.get("installedTree")
        if (
            not isinstance(installed_tree, dict)
            or set(installed_tree) != {"algorithm", "formatVersion", "digest", "excluded"}
            or installed_tree.get("algorithm") != "sha256"
            or installed_tree.get("formatVersion") != 1
            or installed_tree.get("excluded") != [
                "runtime-lock.json",
                "**/__pycache__/**",
                "**/*.pyc",
            ]
            or installed_tree.get("digest") != runtime_contract.get("treeSha256")
        ):
            fail("Engine runtime lock has an invalid installed-tree digest contract")
        if runtime_tree_sha256_from_zip(archive, root) != installed_tree["digest"]:
            fail("Engine ZIP private runtime tree does not match its integrity digest")
        installer = archive.read(f"{root}/Install LocalTube Dub Engine.command").decode("utf-8")
        if extension_id not in installer or "__EXTENSION_ID__" in installer or "__VERSION__" in installer:
            fail("Engine installer was not bound to the requested extension ID and version")
        if "ditto \"$ROOT_DIR\" \"$STAGING_ROOT\"" not in installer or "LOCAL_DUB_RUNTIME_DIR=\"$RUNTIME_ROOT\"" not in installer:
            fail("Engine installer does not atomically copy its bundled runtime")
        if 'if [[ -t 0 ]]' not in installer or 'read -r -p "按回车键关闭窗口..." _ || true' not in installer:
            fail("Engine installer must not report failure when a non-interactive install reaches EOF")
        quarantine_clear = installer.find('/usr/bin/xattr -drs com.apple.quarantine "$ROOT_DIR"')
        runtime_verify = installer.find('LOCAL_DUB_CUSTOMER_RELEASE=1 "$ROOT_DIR/scripts/install_engine_deps_macos.sh"')
        if quarantine_clear < 0 or runtime_verify < 0 or quarantine_clear > runtime_verify:
            fail("Engine installer must clear its downloaded runtime quarantine before integrity verification")
        if re.search(r"\b(?:pip|brew|curl|wget)\b", installer):
            fail("customer Engine installer must not invoke package managers or network tools")
        dependency_installer = archive.read(f"{root}/scripts/install_engine_deps_macos.sh").decode("utf-8")
        bundled_gate = dependency_installer.find('if [[ "$CUSTOMER_RELEASE" == "1"')
        source_gate = dependency_installer.find('if [[ "$SOURCE_DEVELOPMENT" != "1" ]]')
        first_pip_or_brew = min(
            position
            for position in (dependency_installer.find("-m pip"), dependency_installer.find("brew install"))
            if position >= 0
        )
        if bundled_gate < 0 or source_gate < bundled_gate or source_gate > first_pip_or_brew:
            fail("release dependency script must fail closed before any source package-manager path")
        if "--verify-runtime" not in dependency_installer or "LOCAL_DUB_CUSTOMER_RELEASE=1" not in installer:
            fail("customer installer does not enforce the bundled runtime integrity contract")
        native_installer = archive.read(f"{root}/companion/install_native_host_macos.sh").decode("utf-8")
        if "^[a-p]{32}$" not in native_installer or "allowed_origins" not in native_installer:
            fail("Native Host installer lacks extension-ID validation or allowed_origins wiring")
        return {"files": len(names), "root": root, "version": release["version"], "architecture": architecture}


def main() -> None:
    if len(sys.argv) == 2 and sys.argv[1] == "--self-test":
        root = Path(__file__).resolve().parents[1]
        manifest_path = root / "packaging" / "runtime-manifest.json"
        assembler_path = root / "scripts" / "assemble_engine_runtime.py"
        if not manifest_path.is_file():
            fail("runtime manifest is missing")
        if not assembler_path.is_file():
            fail("runtime assembler is missing")
        assembler_spec = importlib.util.spec_from_file_location("localtube_runtime_assembler", assembler_path)
        if assembler_spec is None or assembler_spec.loader is None:
            fail("runtime assembler is not importable")
        assembler = importlib.util.module_from_spec(assembler_spec)
        assembler_spec.loader.exec_module(assembler)
        manifest = assembler.load_runtime_manifest(manifest_path)
        expected_model_manifest = {
            "id": "kokoro-int8-multi-lang-v1_1",
            "version": "1.1-int8",
            "archiveSha256": "a1e94694776049035c4f2c6529f003aaece993c76aae9a78995831c3c4dcafc6",
        }
        if manifest.get("modelManifest") != expected_model_manifest:
            fail("runtime manifest does not identify the reviewed Kokoro model")
        expected_packages = {
            "aiohappyeyeballs": "2.7.1",
            "aiohttp": "3.14.1",
            "aiosignal": "1.4.0",
            "attrs": "26.1.0",
            "certifi": "2026.6.17",
            "cffi": "2.1.0",
            "curl-cffi": "0.13.0",
            "edge-tts": "7.2.8",
            "frozenlist": "1.8.0",
            "idna": "3.18",
            "multidict": "6.7.1",
            "propcache": "0.5.2",
            "pycparser": "3.0",
            "sherpa-onnx": "1.13.4",
            "sherpa-onnx-core": "1.13.4",
            "tabulate": "0.10.0",
            "typing-extensions": "4.16.0",
            "yarl": "1.24.2",
            "yt-dlp": "2026.7.4",
        }
        actual_packages = {item["id"]: item["version"] for item in manifest["packages"]}
        if actual_packages != expected_packages:
            fail("runtime manifest does not contain the reviewed complete package set")
        for architecture in ("arm64", "x64"):
            target = manifest["platforms"]["macos"]["architectures"][architecture]
            if target["python"]["url"].startswith("https://") is False:
                fail("runtime Python URL must use HTTPS")
            if not target["python"].get("bytes") or not target["python"].get("sha256"):
                fail("runtime Python artifact must have size and SHA-256")
            if any("kokoro-int8" in str(artifact.get("name")) for artifact in target["executables"]):
                fail("runtime manifest must not distribute the Kokoro model")
        with tempfile.TemporaryDirectory(prefix="localtube-release-self-test.") as temporary:
            output = Path(temporary) / "runtime"
            result = subprocess.run(
                [sys.executable, str(assembler_path), "--self-test", "--output", str(output)],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                fail(result.stderr.strip() or result.stdout.strip() or "runtime assembler self-test failed")
        print(json.dumps({"ok": True, "selfTest": "runtime-package"}))
        return
    if len(sys.argv) != 5:
        fail("Usage: verify_release_packages.py <extension.zip> <engine.zip> <extension-id> <version>")
    extension_zip = Path(sys.argv[1])
    engine_zip = Path(sys.argv[2])
    extension_id = sys.argv[3]
    version = sys.argv[4]
    if not re.fullmatch(r"[a-p]{32}", extension_id):
        fail("invalid Chrome extension ID")
    if not extension_zip.is_file() or not engine_zip.is_file():
        fail("release ZIP is missing")
    root = Path(__file__).resolve().parents[1]
    runtime_manifest = json.loads((root / "packaging" / "runtime-manifest.json").read_text(encoding="utf-8"))
    engine = verify_engine(engine_zip, extension_id, version, runtime_manifest)
    expected_engine_name = f"LocalTube-Dub-Engine-v{version}-macOS-{engine['architecture']}.zip"
    result = {
        "ok": True,
        "extension": verify_extension(extension_zip, extension_id, version, expected_engine_name),
        "engine": engine,
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
