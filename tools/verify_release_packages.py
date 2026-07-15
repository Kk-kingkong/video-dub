#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


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


def verify_extension(path: Path, extension_id: str, expected_version: str) -> dict[str, object]:
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
        expected_engine_name = f"LocalTube-Dub-Engine-v{expected_version}-macOS.zip"
        if release_info.get("engineBundleName") != expected_engine_name:
            fail("extension ZIP release-info has the wrong Engine bundle name")
        for key in ("engineDownloadUrl", "supportUrl"):
            value = str(release_info.get(key) or "")
            if value and not value.startswith("https://"):
                fail(f"extension ZIP {key} must use HTTPS")
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


def verify_engine(path: Path, extension_id: str, expected_version: str) -> dict[str, object]:
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
        if any("/.venv/" in f"/{name}" or name.endswith((".pyc", ".DS_Store")) for name in names):
            fail("Engine ZIP contains a machine-specific virtual environment or cache")

        release = json.loads(archive.read(f"{root}/release.json"))
        if release.get("version") != expected_version or release.get("chromeExtensionId") != extension_id:
            fail("Engine release metadata does not match version and extension ID")
        if int(release.get("protocolVersion") or 0) < 2:
            fail("Engine release metadata is missing the required protocol version")
        if release.get("signed") is not False or release.get("notarized") is not False:
            fail("private beta metadata must accurately report unsigned/unnotarized state")
        installer = archive.read(f"{root}/Install LocalTube Dub Engine.command").decode("utf-8")
        if extension_id not in installer or "__EXTENSION_ID__" in installer or "__VERSION__" in installer:
            fail("Engine installer was not bound to the requested extension ID and version")
        native_installer = archive.read(f"{root}/companion/install_native_host_macos.sh").decode("utf-8")
        if "^[a-p]{32}$" not in native_installer or "allowed_origins" not in native_installer:
            fail("Native Host installer lacks extension-ID validation or allowed_origins wiring")
        return {"files": len(names), "root": root, "version": release["version"]}


def main() -> None:
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
    result = {
        "ok": True,
        "extension": verify_extension(extension_zip, extension_id, version),
        "engine": verify_engine(engine_zip, extension_id, version),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
