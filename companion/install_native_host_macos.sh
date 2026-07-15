#!/usr/bin/env bash
set -euo pipefail

HOST_NAME="com.localtube.dub.engine"
EXTENSION_ID="${1:-}"

if [[ -z "$EXTENSION_ID" ]]; then
  echo "Usage: ./install_native_host_macos.sh <chrome-extension-id>"
  echo "Open the LocalTube Dub install page or chrome://extensions to get the extension ID."
  exit 1
fi
if [[ ! "$EXTENSION_ID" =~ ^[a-p]{32}$ ]]; then
  echo "Invalid Chrome extension ID: $EXTENSION_ID"
  echo "Chrome extension IDs contain exactly 32 letters from a to p."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOSTART_SCRIPT="$SCRIPT_DIR/../scripts/install_engine_autostart_macos.sh"
RUNTIME_ROOT="${LOCAL_DUB_RUNTIME_DIR:-$HOME/Library/Application Support/LocalTube Dub/engine-runtime}"
HOST_PATH="$RUNTIME_ROOT/companion/native_host_launcher_macos.sh"
PYTHON_HOST_PATH="$RUNTIME_ROOT/companion/native_host.py"
PYTHON_PATH_FILE="$RUNTIME_ROOT/companion/.localtube_python_path"
TARGET_FILE="${LOCAL_DUB_NATIVE_MANIFEST_PATH:-$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts/$HOST_NAME.json}"
TARGET_DIR="$(dirname "$TARGET_FILE")"
DRY_RUN="${LOCAL_DUB_NATIVE_INSTALL_DRY_RUN:-0}"

chmod +x "$AUTOSTART_SCRIPT"
if [[ "$DRY_RUN" == "1" ]]; then
  LOCAL_DUB_AUTOSTART_DRY_RUN=1 "$AUTOSTART_SCRIPT"
  HOST_PATH="$SCRIPT_DIR/native_host_launcher_macos.sh"
  PYTHON_HOST_PATH="$SCRIPT_DIR/native_host.py"
elif ! "$AUTOSTART_SCRIPT"; then
  echo "Engine login auto-start health verification failed. Native Host was not registered."
  exit 1
fi
if [[ "$DRY_RUN" != "1" ]]; then
  echo "Engine login auto-start is ready."
fi
if [[ ! -x "$HOST_PATH" || ! -f "$PYTHON_HOST_PATH" || ! -x "$RUNTIME_ROOT/.venv/bin/python" ]]; then
  if [[ "$DRY_RUN" != "1" ]]; then
    echo "LocalTube Dub runtime installation is incomplete: $RUNTIME_ROOT"
    echo "Run ./scripts/install_engine_deps_macos.sh, then retry this installer."
    exit 1
  fi
fi
chmod +x "$HOST_PATH" "$PYTHON_HOST_PATH"
if [[ "$DRY_RUN" != "1" ]]; then
  printf '%s\n' "$RUNTIME_ROOT/.venv/bin/python" > "$PYTHON_PATH_FILE"
fi
mkdir -p "$TARGET_DIR"

python3 - "$TARGET_FILE" "$HOST_PATH" "$EXTENSION_ID" <<'PY'
import json
import sys
from pathlib import Path

target_file = Path(sys.argv[1])
host_path = Path(sys.argv[2]).resolve()
extension_id = sys.argv[3].strip()

manifest = {
    "name": "com.localtube.dub.engine",
    "description": "LocalTube Dub local AI engine",
    "path": str(host_path),
    "type": "stdio",
    "allowed_origins": [f"chrome-extension://{extension_id}/"],
}

target_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target_file)
PY

echo "Installed LocalTube Dub Native Messaging host for extension: $EXTENSION_ID"
echo "Native host launcher: $HOST_PATH"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run only: no Engine or Chrome profile was changed."
  exit 0
fi
echo "Restart Chrome if the extension was already open."
