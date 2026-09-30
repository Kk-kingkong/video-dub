#!/usr/bin/env python3
"""Exercise signed Engine publication using disposable real RSA keys."""
from __future__ import annotations

import json
import copy
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import sign_engine_update as publication
import promote_engine_release as promotion


def verify_promotion_gate(version: str, assets: Path, signed: Path) -> None:
    tag, commit = f"v{version}", "a" * 40
    files = {path.name: path for directory in (assets, signed) for path in directory.iterdir()}
    release = dict(id=7, tag_name=tag, draft=True, prerelease=False, assets=[
        dict(id=index, name=name, size=path.stat().st_size, state="uploaded", updated_at="unchanged")
        for index, (name, path) in enumerate(sorted(files.items()), 1)
    ])
    passed = dict(id=10, run_attempt=1, run_started_at="2026-09-30T01:00:00Z", head_sha=commit, status="completed", conclusion="success",
                  event="push", path=".github/workflows/cross-platform-engine.yml")
    for scenario in ("success", "no-ci", "failed-ci", "running-ci", "rerun-failed-ci", "late-failed-ci", "bad-signature",
                     "missing-asset", "asset-changed", "published-early", "tag-moved", "not-draft", "prerelease", "verify-only"):
        fixture = copy.deepcopy(release)
        if scenario in ("not-draft", "verify-only"):
            fixture["draft"] = False
        if scenario == "prerelease":
            fixture["prerelease"] = True
        if scenario == "missing-asset":
            fixture["assets"].pop()
        patches, downloads = [], []
        commit_reads = 0

        def api(_repository, endpoint, *, payload=None):
            nonlocal commit_reads
            if payload is not None:
                assert endpoint == "releases/7"
                assert len(downloads) == 5, "release was published before checking every signed asset"
                patches.append(payload)
                return {**fixture, "draft": False}
            if endpoint.startswith("releases?"):
                return [copy.deepcopy(fixture)]
            if endpoint == "releases/7":
                current = copy.deepcopy(fixture)
                if scenario == "asset-changed":
                    current["assets"][0]["id"] += 100
                if scenario == "published-early":
                    current["draft"] = False
                return current
            if endpoint.startswith("commits/"):
                commit_reads += 1
                return {"sha": "b" * 40 if scenario == "tag-moved" and commit_reads > 1 else commit}
            if endpoint.startswith("actions/workflows/"):
                if scenario == "no-ci":
                    return {"workflow_runs": []}
                if scenario in ("failed-ci", "running-ci", "rerun-failed-ci") or scenario == "late-failed-ci" and commit_reads > 1:
                    latest = {**passed, "id": 11, "run_started_at": "2026-09-30T02:00:00Z", "conclusion": "failure"}
                    if scenario == "running-ci":
                        latest.update(status="in_progress", conclusion=None)
                    if scenario == "rerun-failed-ci":
                        latest.update(id=9, run_attempt=2)
                    return {"workflow_runs": [passed, latest]}
                current = {**passed, "head_sha": "b" * 40} if scenario == "tag-moved" and commit_reads > 1 else passed
                return {"workflow_runs": [current]}
            raise AssertionError(endpoint)

        def download(_repository, asset, destination):
            downloads.append(asset["name"])
            shutil.copyfile(files[asset["name"]], destination)
            if scenario == "bad-signature" and asset["name"] == publication.SIGNATURE_NAME:
                destination.write_bytes(b"invalid signature")

        with patch.object(promotion, "api", api), patch.object(promotion, "download_asset", download):
            try:
                promotion.promote("Kk-kingkong/video-dub", tag, verify_only=scenario == "verify-only")
            except publication.PublicationError:
                assert scenario not in ("success", "verify-only"), scenario
            else:
                assert scenario in ("success", "verify-only"), f"unsafe promotion accepted: {scenario}"
        assert len(patches) == (1 if scenario == "success" else 0), scenario
        if patches:
            assert patches == [{"draft": False, "prerelease": False, "make_latest": "true"}]
    with patch.object(promotion, "api", side_effect=AssertionError("invalid tags must not reach GitHub")):
        for tag in ("v1.2.3-rc1", "main", "../v1.2.3", "v1.2.3\n", "v01.2.3"):
            try:
                promotion.promote("Kk-kingkong/video-dub", tag)
            except publication.PublicationError:
                pass
            else:
                raise AssertionError(f"invalid tag accepted: {tag!r}")
    print("Draft Engine promotion checks passed: CI, signatures, asset drift and publication ordering")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="localtube-update-publication-") as temporary:
        root = Path(temporary)
        key, certificate = root / "private.pem", root / "certificate.cer"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
             "-out", str(certificate), "-outform", "DER", "-subj", "/CN=Publication test", "-days", "1"],
            check=True, capture_output=True,
        )
        publication.CERTIFICATE_PATH = certificate
        assets = root / "assets"
        assets.mkdir()
        version = "1.2.3"
        for platform, architecture, suffix in publication.TARGETS:
            name = f"LocalTube-Dub-Engine-v{version}-{suffix}.zip"
            with zipfile.ZipFile(assets / name, "w") as archive:
                archive.writestr(f"{name[:-4]}/release.json", json.dumps({
                    "version": version, "protocolVersion": 2, "platform": platform,
                    "architecture": architecture, "autoUpdate": True,
                }))
                archive.writestr(f"{name[:-4]}/server/update-signing-cert.cer", certificate.read_bytes())
        output = root / "published"
        publication.publish(version, assets, key, output)
        manifest = (output / publication.MANIFEST_NAME).read_bytes()
        signature = (output / publication.SIGNATURE_NAME).read_bytes()
        payload = json.loads(manifest)
        assert set(payload) == {"schemaVersion", "channel", "version", "protocolVersion", "packages"}
        assert payload["channel"] == "stable" and payload["version"] == version
        assert len(payload["packages"]) == 3
        for package in payload["packages"]:
            assert set(package) == {"platform", "architecture", "url", "size", "sha256"}
            assert package["url"].startswith(publication.DOWNLOAD_ROOT + f"/v{version}/")
            assert package["size"] > 0 and len(package["sha256"]) == 64
        assert manifest == (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        public_key = subprocess.run(
            ["openssl", "x509", "-inform", "DER", "-in", str(certificate), "-pubkey", "-noout"],
            check=True, capture_output=True,
        ).stdout
        (root / "public.pem").write_bytes(public_key)
        subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", str(root / "public.pem"),
             "-signature", str(output / publication.SIGNATURE_NAME), str(output / publication.MANIFEST_NAME)],
            check=True, capture_output=True,
        )
        publication.publish(version, assets, key, output)
        assert (output / publication.MANIFEST_NAME).read_bytes() == manifest
        assert (output / publication.SIGNATURE_NAME).read_bytes() == signature
        publication.publish(version, assets, None, output, verify=True)
        verify_promotion_gate(version, assets, output)
        (output / publication.MANIFEST_NAME).write_bytes(manifest + b" ")
        try:
            publication.publish(version, assets, None, output, verify=True)
        except publication.PublicationError:
            pass
        else:
            raise AssertionError("tampered published manifest was accepted")
        (output / publication.MANIFEST_NAME).write_bytes(manifest)
        (output / publication.SIGNATURE_NAME).write_bytes(signature[:-1] + bytes([signature[-1] ^ 1]))
        try:
            publication.publish(version, assets, None, output, verify=True)
        except publication.PublicationError:
            pass
        else:
            raise AssertionError("tampered published signature was accepted")
        (output / publication.SIGNATURE_NAME).write_bytes(signature)

        def rejected(private_key: Path = key) -> None:
            try:
                publication.publish(version, assets, private_key, root / "rejected")
            except publication.PublicationError:
                assert not (root / "rejected" / publication.MANIFEST_NAME).exists()
            else:
                raise AssertionError("unsafe publication was accepted")

        missing = assets / f"LocalTube-Dub-Engine-v{version}-Windows-x64.zip"
        original = missing.read_bytes()
        missing.unlink()
        rejected()
        missing.write_bytes(b"broken ZIP")
        rejected()
        missing.write_bytes(original)
        wrong_key = root / "wrong.pem"
        subprocess.run(["openssl", "genrsa", "-out", str(wrong_key), "2048"], check=True, capture_output=True)
        rejected(wrong_key)
        with zipfile.ZipFile(missing, "w") as archive:
            archive.writestr(f"{missing.stem}/release.json", json.dumps({
                "version": version, "protocolVersion": 2, "platform": "windows",
                "architecture": "x64", "autoUpdate": True,
            }))
            archive.writestr(f"{missing.stem}/server/update-signing-cert.cer", b"wrong trust anchor")
        rejected()
    print("Signed Engine publication checks passed")


if __name__ == "__main__":
    main()
