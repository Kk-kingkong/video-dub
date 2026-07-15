#!/usr/bin/env python3
"""Verify public-repository and Chrome Web Store documentation invariants."""

from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_VERSION = "0.1.96"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def read(relative_path: str) -> str:
    path = ROOT / relative_path
    require(path.is_file(), f"missing required file: {relative_path}")
    return path.read_text(encoding="utf-8")


def verify_repository_files() -> None:
    required = (
        "LICENSE",
        "README.zh-CN.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "SUPPORT.md",
        "THIRD_PARTY_NOTICES.md",
        ".github/ISSUE_TEMPLATE/bug_report.yml",
        ".github/ISSUE_TEMPLATE/feature_request.yml",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "docs/privacy-policy.md",
        "docs/store-listing-draft.md",
        "docs/chrome-web-store-permissions.md",
        "docs/release-process.md",
    )
    for relative_path in required:
        read(relative_path)

    require(not (ROOT / "docs/privacy-policy-template.md").exists(), "obsolete privacy template still exists")
    license_text = read("LICENSE")
    require("Apache License" in license_text and "Version 2.0" in license_text, "Apache-2.0 license missing")
    ignore = read(".gitignore")
    for pattern in (".venv/", ".env", "dist/", "models/", "*.log", "*.pem"):
        require(pattern in ignore, f".gitignore does not exclude {pattern}")


def verify_release_metadata() -> None:
    manifest = json.loads(read("extension/manifest.json"))
    release_info = json.loads(read("extension/release-info.json"))
    require(manifest.get("version") == EXPECTED_VERSION, "manifest version mismatch")
    require(release_info.get("version") == EXPECTED_VERSION, "release-info version mismatch")
    require(len(str(manifest.get("description") or "")) <= 132, "manifest description exceeds 132 characters")
    require(EXPECTED_VERSION in read("extension/popup.html"), "popup fallback version mismatch")
    require(f"## {EXPECTED_VERSION} -" in read("CHANGELOG.md"), "changelog entry missing")


def verify_public_claims() -> None:
    privacy = read("docs/privacy-policy.md")
    for phrase in (
        "chrome.storage.sync",
        "chrome.storage.local",
        "YouTube cookies",
        "tabCapture",
        "Microsoft natural online",
        "does not sell user data",
        "no LocalTube Dub account system",
    ):
        require(phrase.casefold() in privacy.casefold(), f"privacy disclosure missing: {phrase}")

    listing = read("docs/store-listing-draft.md")
    require("single purpose" in listing.casefold(), "single-purpose listing text missing")
    require("managed service entry reserved" not in listing.casefold(), "undeveloped managed-service claim remains")
    require("1280 x 800" in listing and "440 x 280" in listing, "required listing assets missing")
    require("reviewer instructions" in listing.casefold(), "reviewer instructions missing")

    readme = read("README.md")
    for link in ("README.zh-CN.md", "docs/privacy-policy.md", "CONTRIBUTING.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md"):
        require(link in readme, f"README link missing: {link}")
    require("not affiliated" in readme.casefold(), "README non-affiliation disclosure missing")

    chinese_readme = read("README.zh-CN.md")
    for phrase in ("YouTube 中文翻译与配音", "隐私政策", "当前限制", EXPECTED_VERSION):
        require(phrase in chinese_readme, f"Chinese README content missing: {phrase}")


def verify_no_obvious_secrets() -> None:
    secret_patterns = (
        re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
        re.compile(r"AIza[0-9A-Za-z_-]{20,}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    )
    excluded_parts = {".git", ".venv", "dist", "__pycache__"}
    text_suffixes = {".css", ".html", ".js", ".json", ".md", ".py", ".sh", ".txt", ".yml", ".yaml"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded_parts for part in path.parts):
            continue
        if path.name != "LICENSE" and path.suffix.lower() not in text_suffixes:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in secret_patterns:
            require(not pattern.search(content), f"possible credential in {path.relative_to(ROOT)}")


def main() -> None:
    verify_repository_files()
    verify_release_metadata()
    verify_public_claims()
    verify_no_obvious_secrets()
    print("Open-source and Chrome Web Store compliance checks passed.")


if __name__ == "__main__":
    main()
