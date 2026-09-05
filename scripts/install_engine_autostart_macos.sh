#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${LOCAL_DUB_RUNTIME_DIR:-$HOME/Library/Application Support/LocalTube Dub/engine-runtime}"
PYTHON_BIN="${LOCAL_DUB_PYTHON:-}"
DRY_RUN="${LOCAL_DUB_AUTOSTART_DRY_RUN:-0}"

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if [[ -z "$PYTHON_BIN" && -x "$SOURCE_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$SOURCE_ROOT/.venv/bin/python"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  for CANDIDATE in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
    if [[ -n "$CANDIDATE" && -x "$CANDIDATE" ]] && python_supported "$CANDIDATE"; then
      PYTHON_BIN="$CANDIDATE"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]] || ! python_supported "$PYTHON_BIN"; then
  echo "LocalTube Dub Engine on-demand startup needs Python 3.10+. Run ./scripts/install_engine_deps_macos.sh first."
  exit 1
fi

if [[ "$DRY_RUN" != "1" && "$SOURCE_ROOT" != "$RUNTIME_DIR" ]]; then
  if [[ ! -x "$SOURCE_ROOT/.venv/bin/python" ]]; then
    echo "Project virtual environment is missing. Run ./scripts/install_engine_deps_macos.sh first."
    exit 1
  fi
  STAGING_DIR="$RUNTIME_DIR.staging.$$"
  BACKUP_DIR="$RUNTIME_DIR.backup.$$"
  rm -rf "$STAGING_DIR" "$BACKUP_DIR"
  mkdir -p "$STAGING_DIR/server" "$STAGING_DIR/scripts" "$STAGING_DIR/companion"
  ditto "$SOURCE_ROOT/.venv" "$STAGING_DIR/.venv"
  install -m 0644 "$SOURCE_ROOT/server/local_dub_server.py" "$STAGING_DIR/server/local_dub_server.py"
  install -m 0644 "$SOURCE_ROOT/server/kokoro_tts.py" "$STAGING_DIR/server/kokoro_tts.py"
  install -m 0755 "$SOURCE_ROOT/scripts/start_engine_macos.sh" "$STAGING_DIR/scripts/start_engine_macos.sh"
  install -m 0755 "$SOURCE_ROOT/scripts/install_engine_autostart_macos.sh" "$STAGING_DIR/scripts/install_engine_autostart_macos.sh"
  install -m 0755 "$SOURCE_ROOT/scripts/uninstall_engine_autostart_macos.sh" "$STAGING_DIR/scripts/uninstall_engine_autostart_macos.sh"
  install -m 0755 "$SOURCE_ROOT/scripts/install_local_whisper_macos.sh" "$STAGING_DIR/scripts/install_local_whisper_macos.sh"
  install -m 0755 "$SOURCE_ROOT/companion/native_host.py" "$STAGING_DIR/companion/native_host.py"
  install -m 0755 "$SOURCE_ROOT/companion/native_host_launcher_macos.sh" "$STAGING_DIR/companion/native_host_launcher_macos.sh"
  install -m 0755 "$SOURCE_ROOT/companion/uninstall_native_host_macos.sh" "$STAGING_DIR/companion/uninstall_native_host_macos.sh"
  if [[ -f "$SOURCE_ROOT/release.json" ]]; then
    install -m 0644 "$SOURCE_ROOT/release.json" "$STAGING_DIR/release.json"
  elif [[ -f "$SOURCE_ROOT/extension/manifest.json" ]]; then
    "$PYTHON_BIN" - "$SOURCE_ROOT/extension/manifest.json" "$STAGING_DIR/release.json" <<'PY'
import json
import sys
from pathlib import Path

manifest = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
payload = {
    "product": "LocalTube Dub Engine",
    "version": str(manifest.get("version") or "development"),
    "protocolVersion": 2,
    "channel": "development",
}
Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  fi
  if [[ -d "$RUNTIME_DIR" ]]; then
    mv "$RUNTIME_DIR" "$BACKUP_DIR"
  fi
  mv "$STAGING_DIR" "$RUNTIME_DIR"
  rm -rf "$BACKUP_DIR"
fi

# Keep this command name for existing Native Host repair clients.
if [[ "$DRY_RUN" == "1" ]]; then
  echo "Dry run: Engine will start on demand; no LaunchAgent will be created."
  exit 0
fi

chmod +x "$RUNTIME_DIR/companion/native_host_launcher_macos.sh" "$RUNTIME_DIR/companion/native_host.py"
printf '%s\n' "$RUNTIME_DIR/.venv/bin/python" > "$RUNTIME_DIR/companion/.localtube_python_path"
PYTHONPATH="$RUNTIME_DIR/companion" "$RUNTIME_DIR/.venv/bin/python" -c 'import native_host'
"$SOURCE_ROOT/scripts/uninstall_engine_autostart_macos.sh"

echo "LocalTube Dub Engine on-demand startup is ready."
echo "Runtime: $RUNTIME_DIR"
echo "The extension starts Engine when needed; it exits after five idle minutes."
