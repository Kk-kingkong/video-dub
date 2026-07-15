#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSION_ID="${1:-}"
OUTPUT_DIR="${2:-$ROOT_DIR/dist}"
ENGINE_DOWNLOAD_URL="${LOCAL_DUB_ENGINE_DOWNLOAD_URL:-}"
SUPPORT_URL="${LOCAL_DUB_SUPPORT_URL:-}"

if [[ ! "$EXTENSION_ID" =~ ^[a-p]{32}$ ]]; then
  echo "Usage: ./scripts/build_release_macos.sh <32-character-chrome-extension-id> [output-directory]"
  echo "Chrome extension IDs contain only letters a through p."
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
OUTPUT_DIR="$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/localtube-release.XXXXXX")"
trap 'rm -rf "$BUILD_ROOT"' EXIT

EXTENSION_ZIP="$OUTPUT_DIR/LocalTube-Dub-extension-v$VERSION.zip"
ENGINE_NAME="LocalTube-Dub-Engine-v$VERSION-macOS"
ENGINE_ZIP="$OUTPUT_DIR/$ENGINE_NAME.zip"
CHECKSUM_FILE="$OUTPUT_DIR/LocalTube-Dub-v$VERSION-SHA256SUMS.txt"
rm -f "$EXTENSION_ZIP" "$ENGINE_ZIP" "$CHECKSUM_FILE"

EXTENSION_STAGE="$BUILD_ROOT/extension"
mkdir -p "$EXTENSION_STAGE"
ditto --norsrc "$ROOT_DIR/extension" "$EXTENSION_STAGE"
find "$EXTENSION_STAGE" -name '.DS_Store' -delete
install -m 0644 "$ROOT_DIR/LICENSE" "$EXTENSION_STAGE/LICENSE"
install -m 0644 "$ROOT_DIR/THIRD_PARTY_NOTICES.md" "$EXTENSION_STAGE/THIRD_PARTY_NOTICES.md"
python3 - "$EXTENSION_STAGE/release-info.json" "$VERSION" "$EXTENSION_ID" "$ENGINE_NAME.zip" "$ENGINE_DOWNLOAD_URL" "$SUPPORT_URL" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

target = Path(sys.argv[1])
version, extension_id, engine_name, download_url, support_url = sys.argv[2:]
for label, value in (("Engine download URL", download_url), ("support URL", support_url)):
    if value and urlsplit(value).scheme.lower() != "https":
        raise SystemExit(f"{label} must use HTTPS: {value}")
payload = {
    "channel": "private-beta",
    "version": version,
    "extensionId": extension_id,
    "engineBundleName": engine_name,
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
for script in \
  start_engine_macos.sh \
  install_engine_deps_macos.sh \
  install_engine_autostart_macos.sh \
  uninstall_engine_autostart_macos.sh \
  install_local_whisper_macos.sh; do
  install -m 0755 "$ROOT_DIR/scripts/$script" "$ENGINE_STAGE/scripts/$script"
done
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

python3 - "$ENGINE_STAGE/release.json" "$VERSION" "$EXTENSION_ID" <<'PY'
import json
import sys
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "product": "LocalTube Dub Engine",
    "version": sys.argv[2],
    "protocolVersion": 2,
    "chromeExtensionId": sys.argv[3],
    "channel": "private-beta",
    "signed": False,
    "notarized": False,
}
target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

(
  cd "$BUILD_ROOT"
  zip -X -q -r "$ENGINE_ZIP" "$ENGINE_NAME"
)

python3 "$ROOT_DIR/tools/verify_release_packages.py" "$EXTENSION_ZIP" "$ENGINE_ZIP" "$EXTENSION_ID" "$VERSION"
if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  "$ROOT_DIR/tools/smoke_release_macos.sh" "$ENGINE_ZIP" "$EXTENSION_ID" "$VERSION"
else
  echo "Skipping isolated installer smoke test because project .venv is unavailable."
fi
(
  cd "$OUTPUT_DIR"
  shasum -a 256 "$(basename "$EXTENSION_ZIP")" "$(basename "$ENGINE_ZIP")" > "$CHECKSUM_FILE"
)

echo "LocalTube Dub release packages are ready:"
echo "  Extension: $EXTENSION_ZIP"
echo "  macOS Engine: $ENGINE_ZIP"
echo "  Checksums: $CHECKSUM_FILE"
echo "This private-beta Engine bundle is not signed or notarized."
