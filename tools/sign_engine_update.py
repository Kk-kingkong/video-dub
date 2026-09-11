#!/usr/bin/env python3
"""Sign locally or verify the complete Engine automatic-update release catalog."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath


CERTIFICATE_PATH = Path(__file__).resolve().parents[1] / "server" / "update-signing-cert.cer"
DOWNLOAD_ROOT = "https://github.com/Kk-kingkong/video-dub/releases/download"
MANIFEST_NAME = "LocalTube-Dub-update.json"
SIGNATURE_NAME = "LocalTube-Dub-update.sig"
TARGETS = (("macos", "arm64", "macOS-arm64"), ("macos", "x64", "macOS-x64"), ("windows", "x64", "Windows-x64"))


class PublicationError(RuntimeError):
    pass


def openssl(*arguments: str) -> bytes:
    result = subprocess.run(["openssl", *arguments], capture_output=True, check=False)
    if result.returncode:
        raise PublicationError("OpenSSL signing or pinned-certificate verification failed")
    return result.stdout


def publish(version: str, assets_dir: Path, private_key: Path | None, output_dir: Path, *, verify: bool = False) -> None:
    if (verify and private_key is not None) or (not verify and private_key is None):
        raise PublicationError("A private key is required only for signing, never verification")
    if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)", version):
        raise PublicationError("Version must be a stable three-component version")
    try:
        certificate = CERTIFICATE_PATH.read_bytes()
        packages = []
        for platform, architecture, suffix in TARGETS:
            name = f"LocalTube-Dub-Engine-v{version}-{suffix}.zip"
            package = assets_dir / name
            with zipfile.ZipFile(package) as archive:
                names = archive.namelist()
                if len(names) != len(set(names)):
                    raise PublicationError(f"Duplicate archive entry in {name}")
                for entry in names:
                    path = PurePosixPath(entry)
                    if path.is_absolute() or ".." in path.parts or "\\" in entry or path.parts[0] != package.stem:
                        raise PublicationError(f"Unsafe archive path in {name}")
                if archive.testzip() is not None:
                    raise PublicationError(f"Corrupt archive: {name}")
                release = json.loads(archive.read(f"{package.stem}/release.json"))
                if not isinstance(release, dict) or release.get("autoUpdate") is not True or any(release.get(field) != expected for field, expected in {
                    "version": version, "platform": platform, "architecture": architecture,
                    "protocolVersion": 2,
                }.items()):
                    raise PublicationError(f"Release metadata mismatch in {name}")
                if archive.read(f"{package.stem}/server/update-signing-cert.cer") != certificate:
                    raise PublicationError(f"Pinned update certificate mismatch in {name}")
            digest = hashlib.sha256()
            with package.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
            packages.append({
                "platform": platform, "architecture": architecture,
                "url": f"{DOWNLOAD_ROOT}/v{version}/{name}",
                "size": package.stat().st_size, "sha256": digest.hexdigest(),
            })
        manifest = (json.dumps({
            "schemaVersion": 1, "channel": "stable", "version": version,
            "protocolVersion": 2, "packages": packages,
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if verify and (output_dir / MANIFEST_NAME).read_bytes() != manifest:
            raise PublicationError("Published manifest does not match the complete release archives")
        with tempfile.TemporaryDirectory(prefix="localtube-update-signing-") as temporary:
            temporary_path = Path(temporary)
            manifest_path = temporary_path / MANIFEST_NAME
            signature_path = temporary_path / SIGNATURE_NAME
            public_key_path = temporary_path / "public.pem"
            manifest_path.write_bytes(manifest)
            public_key_path.write_bytes(openssl("x509", "-inform", "DER", "-in", str(CERTIFICATE_PATH), "-pubkey", "-noout"))
            signature = ((output_dir / SIGNATURE_NAME).read_bytes() if verify else
                         openssl("dgst", "-sha256", "-sign", str(private_key), str(manifest_path)))
            signature_path.write_bytes(signature)
            openssl("dgst", "-sha256", "-verify", str(public_key_path), "-signature", str(signature_path), str(manifest_path))
        if verify:
            return
        # A published version is immutable; rerunning the signer must be harmless.
        for name, content in ((MANIFEST_NAME, manifest), (SIGNATURE_NAME, signature)):
            existing = output_dir / name
            if existing.exists() and existing.read_bytes() != content:
                raise PublicationError(f"Refusing to replace different publication data: {name}")
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / MANIFEST_NAME).write_bytes(manifest)
        (output_dir / SIGNATURE_NAME).write_bytes(signature)
    except (OSError, KeyError, IndexError, ValueError, zipfile.BadZipFile, zlib.error, EOFError, RuntimeError) as error:
        if isinstance(error, PublicationError):
            raise
        raise PublicationError(f"Engine update publication failed: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--assets-dir", required=True, type=Path)
    parser.add_argument("--private-key", type=Path, help="Local signing key; omit for --verify")
    parser.add_argument("--output-dir", required=True, type=Path, help="Publication directory (read-only input with --verify)")
    parser.add_argument("--verify", action="store_true", help="Verify existing manifest and signature without a private key or writes")
    args = parser.parse_args()
    try:
        publish(args.version, args.assets_dir, args.private_key, args.output_dir, verify=args.verify)
    except PublicationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(f"{'Verified' if args.verify else 'Verified and signed'} all three Engine packages for v{args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
