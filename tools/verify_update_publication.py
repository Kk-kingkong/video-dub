#!/usr/bin/env python3
"""Exercise signed Engine publication using disposable real RSA keys."""
from __future__ import annotations

import json
import subprocess
import tempfile
import zipfile
from pathlib import Path

import sign_engine_update as publication


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
