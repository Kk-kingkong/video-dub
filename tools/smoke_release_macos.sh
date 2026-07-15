#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_ZIP="${1:-}"
EXTENSION_ID="${2:-}"
VERSION="${3:-}"

if [[ ! -f "$ENGINE_ZIP" || ! "$EXTENSION_ID" =~ ^[a-p]{32}$ || -z "$VERSION" ]]; then
  echo "Usage: ./tools/smoke_release_macos.sh <engine.zip> <extension-id> <version>"
  exit 1
fi
if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  echo "Release smoke test needs the project .venv. Run install_engine_deps_macos.sh first."
  exit 1
fi

TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/localtube-release-smoke.XXXXXX")"
trap 'rm -rf "$TEMP_ROOT"' EXIT
unzip -q "$ENGINE_ZIP" -d "$TEMP_ROOT"
ENGINE_ROOT="$TEMP_ROOT/LocalTube-Dub-Engine-v$VERSION-macOS"
if [[ ! -d "$ENGINE_ROOT" ]]; then
  echo "Engine archive has an unexpected top-level folder."
  exit 1
fi
ln -s "$ROOT_DIR/.venv" "$ENGINE_ROOT/.venv"

for command_file in "$ENGINE_ROOT"/*.command; do
  if [[ ! -x "$command_file" ]]; then
    echo "Double-click command lost executable permissions: $command_file"
    exit 1
  fi
  bash -n "$command_file"
done

PLIST_PATH="$TEMP_ROOT/com.localtube.dub.engine.http.plist"
MANIFEST_PATH="$TEMP_ROOT/com.localtube.dub.engine.json"
RUNTIME_DIR="$TEMP_ROOT/runtime"
LOG_DIR="$TEMP_ROOT/logs"
LOCAL_DUB_NATIVE_INSTALL_DRY_RUN=1 \
LOCAL_DUB_LAUNCH_AGENT_PATH="$PLIST_PATH" \
LOCAL_DUB_NATIVE_MANIFEST_PATH="$MANIFEST_PATH" \
LOCAL_DUB_RUNTIME_DIR="$RUNTIME_DIR" \
LOCAL_DUB_LOG_DIR="$LOG_DIR" \
  "$ENGINE_ROOT/companion/install_native_host_macos.sh" "$EXTENSION_ID"

"$ROOT_DIR/.venv/bin/python" - "$MANIFEST_PATH" "$PLIST_PATH" "$ENGINE_ROOT" "$EXTENSION_ID" "$VERSION" <<'PY'
import json
import plistlib
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
plist_path = Path(sys.argv[2])
engine_root = Path(sys.argv[3]).resolve()
extension_id = sys.argv[4]
version = sys.argv[5]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("name") != "com.localtube.dub.engine":
    raise SystemExit("Native Host name mismatch")
if manifest.get("allowed_origins") != [f"chrome-extension://{extension_id}/"]:
    raise SystemExit("Native Host allowed_origins mismatch")
if Path(manifest.get("path", "")).resolve() != engine_root / "companion" / "native_host_launcher_macos.sh":
    raise SystemExit("Native Host launcher path mismatch")
with plist_path.open("rb") as source:
    plist = plistlib.load(source)
if plist.get("Label") != "com.localtube.dub.engine.http" or not plist.get("RunAtLoad"):
    raise SystemExit("LaunchAgent payload mismatch")
release = json.loads((engine_root / "release.json").read_text(encoding="utf-8"))
if release.get("version") != version or int(release.get("protocolVersion") or 0) < 2:
    raise SystemExit("Engine release protocol metadata mismatch")
PY

LOCAL_DUB_UNINSTALL_DRY_RUN=1 \
LOCAL_DUB_NATIVE_MANIFEST_PATH="$MANIFEST_PATH" \
LOCAL_DUB_RUNTIME_DIR="$RUNTIME_DIR" \
  "$ENGINE_ROOT/companion/uninstall_native_host_macos.sh"

echo "macOS release installer smoke test ok: $VERSION / $EXTENSION_ID"
