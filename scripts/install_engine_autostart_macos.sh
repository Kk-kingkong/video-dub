#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="${LOCAL_DUB_RUNTIME_DIR:-$HOME/Library/Application Support/LocalTube Dub/engine-runtime}"
LABEL="com.localtube.dub.engine.http"
DOMAIN="gui/$(id -u)"
PLIST_PATH="${LOCAL_DUB_LAUNCH_AGENT_PATH:-$HOME/Library/LaunchAgents/$LABEL.plist}"
LOG_DIR="${LOCAL_DUB_LOG_DIR:-$HOME/Library/Logs/LocalTube Dub}"
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
  echo "LocalTube Dub Engine auto-start needs Python 3.10+. Run ./scripts/install_engine_deps_macos.sh first."
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

SERVICE_ROOT="$RUNTIME_DIR"
SERVICE_PYTHON="$SERVICE_ROOT/.venv/bin/python"
mkdir -p "$(dirname "$PLIST_PATH")" "$LOG_DIR"
"$PYTHON_BIN" - "$PLIST_PATH" "$SERVICE_ROOT" "$SERVICE_PYTHON" "$LOG_DIR" <<'PY'
import plistlib
import sys
from pathlib import Path

plist_path = Path(sys.argv[1])
root_dir = Path(sys.argv[2]).expanduser().resolve()
python_bin = str(Path(sys.argv[3]).expanduser())
log_dir = Path(sys.argv[4]).expanduser().resolve()
payload = {
    "Label": "com.localtube.dub.engine.http",
    "ProgramArguments": [python_bin, str(root_dir / "server" / "local_dub_server.py")],
    "WorkingDirectory": str(root_dir),
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ThrottleInterval": 5,
    "ProcessType": "Background",
    "EnvironmentVariables": {
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
    },
    "StandardOutPath": str(log_dir / "engine.log"),
    "StandardErrorPath": str(log_dir / "engine-error.log"),
}
with plist_path.open("wb") as output:
    plistlib.dump(payload, output, sort_keys=False)
PY

if [[ "$DRY_RUN" == "1" ]]; then
  echo "Generated LocalTube Dub LaunchAgent: $PLIST_PATH"
  exit 0
fi

chmod +x "$SERVICE_ROOT/companion/native_host_launcher_macos.sh" "$SERVICE_ROOT/companion/native_host.py"
printf '%s\n' "$SERVICE_PYTHON" > "$SERVICE_ROOT/companion/.localtube_python_path"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
fi

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -tiTCP:8787 -sTCP:LISTEN 2>/dev/null || true)"
  for PID in $PIDS; do
    COMMAND_LINE="$(ps -p "$PID" -o command= 2>/dev/null || true)"
    if [[ "$COMMAND_LINE" != *"local_dub_server.py"* ]]; then
      echo "Port 8787 is occupied by another program (PID $PID): $COMMAND_LINE"
      exit 1
    fi
    kill "$PID" 2>/dev/null || true
  done
fi

for _ in {1..20}; do
  if ! lsof -tiTCP:8787 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if command -v lsof >/dev/null 2>&1 && lsof -tiTCP:8787 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "The previous LocalTube Dub Engine did not release port 8787 in time."
  exit 1
fi

launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
launchctl kickstart -k "$DOMAIN/$LABEL"

for _ in {1..40}; do
  if curl -fsS --max-time 1 http://127.0.0.1:8787/api/health 2>/dev/null | "$SERVICE_PYTHON" -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if int(p.get("protocolVersion") or 0) >= 2 else 1)' >/dev/null 2>&1; then
    echo "LocalTube Dub Engine auto-start is installed and healthy."
    echo "Runtime: $SERVICE_ROOT"
    echo "LaunchAgent: $PLIST_PATH"
    echo "Logs: $LOG_DIR"
    exit 0
  fi
  sleep 0.25
done

echo "LaunchAgent was installed, but Engine health did not recover in time."
echo "Check: $LOG_DIR/engine-error.log"
exit 1
