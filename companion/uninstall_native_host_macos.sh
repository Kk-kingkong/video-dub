#!/usr/bin/env bash
set -euo pipefail

HOST_NAME="com.localtube.dub.engine"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOSTART_UNINSTALLER="$SCRIPT_DIR/../scripts/uninstall_engine_autostart_macos.sh"
RUNTIME_ROOT="${LOCAL_DUB_RUNTIME_DIR:-$HOME/Library/Application Support/LocalTube Dub/engine-runtime}"
TARGET_FILE="${LOCAL_DUB_NATIVE_MANIFEST_PATH:-$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts/$HOST_NAME.json}"
PURGE="${1:-}"
DRY_RUN="${LOCAL_DUB_UNINSTALL_DRY_RUN:-0}"
PYTHON_BIN="$RUNTIME_ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Would remove LocalTube Dub Engine auto-start, Native Host manifest, and runtime."
  echo "Manifest: $TARGET_FILE"
  echo "Runtime: $RUNTIME_ROOT"
  exit 0
fi

if [[ -x "$AUTOSTART_UNINSTALLER" ]]; then
  "$AUTOSTART_UNINSTALLER"
fi

if [[ -f "$TARGET_FILE" ]]; then
  if [[ -z "$PYTHON_BIN" ]]; then
    echo "Cannot validate the Native Messaging manifest because Python is unavailable."
    exit 1
  fi
  if "$PYTHON_BIN" - "$TARGET_FILE" "$HOST_NAME" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected_name = sys.argv[2]
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    raise SystemExit(1)
raise SystemExit(0 if payload.get("name") == expected_name else 1)
PY
  then
    rm -f "$TARGET_FILE"
    echo "Removed LocalTube Dub Native Messaging manifest: $TARGET_FILE"
  else
    echo "Refusing to remove an unrecognized Native Messaging manifest: $TARGET_FILE"
    exit 1
  fi
fi

if [[ -d "$RUNTIME_ROOT" ]]; then
  rm -rf "$RUNTIME_ROOT"
  echo "Removed LocalTube Dub Engine runtime: $RUNTIME_ROOT"
fi

if [[ "$PURGE" == "--purge" ]]; then
  rm -rf "$HOME/Library/Caches/LocalTube Dub" "$HOME/Library/Logs/LocalTube Dub"
  echo "Removed LocalTube Dub caches and logs."
  echo "Local Whisper models were kept so a later reinstall does not download them again."
fi

echo "LocalTube Dub Engine has been uninstalled. Restart Chrome to clear the old Native Host connection."
