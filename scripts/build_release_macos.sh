#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSION_ID="${1:-}"
OUTPUT_DIR="${2:-$ROOT_DIR/dist}"
ENGINE_DOWNLOAD_URL="${LOCAL_DUB_ENGINE_DOWNLOAD_URL:-}"
SUPPORT_URL="${LOCAL_DUB_SUPPORT_URL:-}"
RELEASE_CHANNEL="${LOCAL_DUB_RELEASE_CHANNEL:-store}"

if [[ ! "$EXTENSION_ID" =~ ^[a-p]{32}$ ]]; then
  echo "Usage: ./scripts/build_release_macos.sh <32-character-chrome-extension-id> [output-directory]"
  echo "Chrome extension IDs contain only letters a through p."
  exit 1
fi
if [[ "$RELEASE_CHANNEL" != "store" && "$RELEASE_CHANNEL" != "private-beta" ]]; then
  echo "LOCAL_DUB_RELEASE_CHANNEL must be store or private-beta."
  exit 1
fi
if [[ "$RELEASE_CHANNEL" == "store" && -z "$ENGINE_DOWNLOAD_URL" ]]; then
  echo "Store releases require LOCAL_DUB_ENGINE_DOWNLOAD_URL."
  exit 1
fi
for command in python3 zip unzip ditto shasum; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Missing release build command: $command"
    exit 1
  fi
done

VERSION="$(python3 - "$ROOT_DIR/extension/manifest.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(manifest["version"])
PY
)"
HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
  arm64|aarch64) PACKAGE_ARCH="arm64" ;;
  x86_64|amd64) PACKAGE_ARCH="x64" ;;
  *) echo "Unsupported macOS build architecture: $HOST_ARCH"; exit 1 ;;
esac
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/localtube-release.XXXXXX")"
trap 'rm -rf "$BUILD_ROOT"' EXIT

EXTENSION_ZIP="$OUTPUT_DIR/LocalTube-Dub-extension-v$VERSION.zip"
ENGINE_NAME="LocalTube-Dub-Engine-v$VERSION-macOS-$PACKAGE_ARCH"
ENGINE_ZIP="$OUTPUT_DIR/$ENGINE_NAME.zip"
CHECKSUM_FILE="$OUTPUT_DIR/LocalTube-Dub-v$VERSION-SHA256SUMS.txt"
rm -f "$EXTENSION_ZIP" "$ENGINE_ZIP" "$CHECKSUM_FILE"

EXTENSION_STAGE="$BUILD_ROOT/extension"
mkdir -p "$EXTENSION_STAGE"
ditto --norsrc "$ROOT_DIR/extension" "$EXTENSION_STAGE"
find "$EXTENSION_STAGE" -name '.DS_Store' -delete
install -m 0644 "$ROOT_DIR/LICENSE" "$EXTENSION_STAGE/LICENSE"
install -m 0644 "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$EXTENSION_STAGE/THIRD_PARTY_NOTICES.md"
python3 - "$EXTENSION_STAGE/release-info.json" "$VERSION" "$EXTENSION_ID" "$RELEASE_CHANNEL" "$ENGINE_DOWNLOAD_URL" "$SUPPORT_URL" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

target = Path(sys.argv[1])
version, extension_id, channel, download_url, support_url = sys.argv[2:]
for label, value in (("Engine download URL", download_url), ("support URL", support_url)):
    if value and urlsplit(value).scheme.lower() != "https":
        raise SystemExit(f"{label} must use HTTPS: {value}")
if download_url and urlsplit(download_url).path.lower().endswith(".zip"):
    raise SystemExit("Engine download URL must be a platform-neutral index, not an architecture-specific ZIP.")
payload = {
    "channel": channel,
    "version": version,
    "extensionId": extension_id,
    "enginePackages": [
        {
            "platform": "macos",
            "architecture": "arm64",
            "label": "macOS Apple Silicon",
            "bundleName": f"LocalTube-Dub-Engine-v{version}-macOS-arm64.zip",
            "downloadUrl": "",
        },
        {
            "platform": "macos",
            "architecture": "x64",
            "label": "macOS Intel",
            "bundleName": f"LocalTube-Dub-Engine-v{version}-macOS-x64.zip",
            "downloadUrl": "",
        },
        {
            "platform": "windows",
            "architecture": "x64",
            "label": "Windows 10/11 x64",
            "bundleName": f"LocalTube-Dub-Engine-v{version}-Windows-x64.zip",
            "downloadUrl": "",
        },
    ],
    "engineDownloadUrl": download_url,
    "supportUrl": support_url,
    "signed": False,
    "notarized": False,
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
(
  cd "$EXTENSION_STAGE"
  zip -X -q -r "$EXTENSION_ZIP" .
)

ENGINE_STAGE="$BUILD_ROOT/$ENGINE_NAME"
mkdir -p "$ENGINE_STAGE/server" "$ENGINE_STAGE/scripts" "$ENGINE_STAGE/companion"
install -m 0644 "$ROOT_DIR/LICENSE" "$ENGINE_STAGE/LICENSE"
install -m 0644 "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$ENGINE_STAGE/THIRD_PARTY_NOTICES.md"
install -m 0644 "$ROOT_DIR/server/local_dub_server.py" "$ENGINE_STAGE/server/local_dub_server.py"
install -m 0644 "$ROOT_DIR/server/kokoro_tts.py" "$ENGINE_STAGE/server/kokoro_tts.py"
install -m 0644 "$ROOT_DIR/server/engine_updates.py" "$ENGINE_STAGE/server/engine_updates.py"
install -m 0644 "$ROOT_DIR/server/update-signing-cert.cer" "$ENGINE_STAGE/server/update-signing-cert.cer"
for script in \
  assemble_engine_runtime.py \
  start_engine_macos.sh \
  install_engine_deps_macos.sh \
  install_engine_autostart_macos.sh \
  uninstall_engine_autostart_macos.sh \
  install_local_whisper_macos.sh; do
  install -m 0755 "$ROOT_DIR/scripts/$script" "$ENGINE_STAGE/scripts/$script"
done

python3 "$ROOT_DIR/scripts/assemble_engine_runtime.py" \
  --platform macos \
  --arch "$PACKAGE_ARCH" \
  --output "$ENGINE_STAGE/.venv"
for script in \
  native_host.py \
  native_host_launcher_macos.sh \
  install_native_host_macos.sh \
  uninstall_native_host_macos.sh; do
  install -m 0755 "$ROOT_DIR/companion/$script" "$ENGINE_STAGE/companion/$script"
done

render_template() {
  local source_file="$1"
  local target_file="$2"
  sed \
    -e "s/__EXTENSION_ID__/$EXTENSION_ID/g" \
    -e "s/__VERSION__/$VERSION/g" \
    "$source_file" > "$target_file"
}

render_template "$ROOT_DIR/packaging/macos/Install LocalTube Dub Engine.command.in" "$ENGINE_STAGE/Install LocalTube Dub Engine.command"
render_template "$ROOT_DIR/packaging/macos/Install No-Caption Whisper.command.in" "$ENGINE_STAGE/Install No-Caption Whisper.command"
render_template "$ROOT_DIR/packaging/macos/Uninstall LocalTube Dub Engine.command.in" "$ENGINE_STAGE/Uninstall LocalTube Dub Engine.command"
render_template "$ROOT_DIR/packaging/macos/README.md.in" "$ENGINE_STAGE/README.md"
chmod 0755 "$ENGINE_STAGE"/*.command

python3 - "$ENGINE_STAGE/release.json" "$ENGINE_STAGE/.venv/runtime-lock.json" "$VERSION" "$EXTENSION_ID" "$PACKAGE_ARCH" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
lock_bytes = lock_path.read_bytes()
lock = json.loads(lock_bytes)
runtime_contract = {
    "schemaVersion": 1,
    "lockSha256": hashlib.sha256(lock_bytes).hexdigest(),
    "treeSha256": lock["installedTree"]["digest"],
    "pythonVersion": lock["pythonVersion"],
    "packages": lock["packages"],
    "artifacts": lock["artifacts"],
    "modelManifest": lock["modelManifest"],
}
payload = {
    "product": "LocalTube Dub Engine",
    "version": sys.argv[3],
    "protocolVersion": 2,
    "chromeExtensionId": sys.argv[4],
    "platform": "macos",
    "architecture": sys.argv[5],
    "bundledRuntime": True,
    "autoUpdate": True,
    "runtimeLock": ".venv/runtime-lock.json",
    "runtimeContract": runtime_contract,
    "channel": "private-beta",
    "signed": False,
    "notarized": False,
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

(
  cd "$BUILD_ROOT"
  zip -X -y -q -r "$ENGINE_ZIP" "$ENGINE_NAME"
)

python3 "$ROOT_DIR/tools/verify_release_packages.py" "$EXTENSION_ZIP" "$ENGINE_ZIP" "$EXTENSION_ID" "$VERSION"
"$ROOT_DIR/tools/smoke_release_macos.sh" "$ENGINE_ZIP" "$EXTENSION_ID" "$VERSION"
(
  cd "$OUTPUT_DIR"
  shasum -a 256 "$(basename "$EXTENSION_ZIP")" "$(basename "$ENGINE_ZIP")" > "$CHECKSUM_FILE"
)

echo "LocalTube Dub release packages are ready:"
echo "  Extension: $EXTENSION_ZIP"
echo "  macOS Engine ($PACKAGE_ARCH): $ENGINE_ZIP"
echo "  Checksums: $CHECKSUM_FILE"
echo "This private-beta Engine bundle is not signed or notarized."
