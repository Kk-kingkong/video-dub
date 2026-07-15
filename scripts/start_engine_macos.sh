#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

HOST="${LOCAL_DUB_HOST:-127.0.0.1}"
PORT="${LOCAL_DUB_PORT:-8787}"
HEALTH_HOST="$HOST"
if [[ "$HEALTH_HOST" == "0.0.0.0" ]]; then
  HEALTH_HOST="127.0.0.1"
fi
HEALTH_URL="http://${HEALTH_HOST}:${PORT}/api/health"
PYTHON_BIN="${LOCAL_DUB_PYTHON:-}"
if [[ -z "$PYTHON_BIN" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3 was not found. Run ./scripts/install_engine_deps_macos.sh first."
  exit 1
fi

EXPECTED_VERSION="$("$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for candidate in (root / "release.json", root / "extension" / "manifest.json"):
    try:
        version = str(json.loads(candidate.read_text(encoding="utf-8")).get("version") or "").strip()
    except (OSError, ValueError):
        continue
    if version:
        print(version)
        break
PY
)"

health_ok() {
  curl -fsS --max-time 2 "$HEALTH_URL" 2>/dev/null | "$PYTHON_BIN" -c 'import json,sys; p=json.load(sys.stdin); expected=sys.argv[1]; compatible=int(p.get("protocolVersion") or 0) >= 2; current=str(p.get("engineVersion") or ""); raise SystemExit(0 if compatible and (not expected or current == expected) else 1)' "$EXPECTED_VERSION" >/dev/null 2>&1
}

if health_ok; then
  echo "LocalTube Dub Engine is already running: $HEALTH_URL"
  echo "Keep this terminal open while using YouTube dubbing."
  exit 0
fi

if curl -fsS --max-time 2 "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Found a different LocalTube Dub Engine version on $HEALTH_URL. Restarting it with $EXPECTED_VERSION..."
fi

if command -v lsof >/dev/null 2>&1; then
  PIDS="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$PIDS" ]]; then
    BLOCKED=0
    for PID in $PIDS; do
      COMMAND_LINE="$(ps -p "$PID" -o command= 2>/dev/null || true)"
      if [[ "$COMMAND_LINE" == *"local_dub_server.py"* ]]; then
        echo "Found an old LocalTube Dub Engine on port $PORT (PID $PID). Restarting it..."
        kill "$PID" 2>/dev/null || true
      else
        BLOCKED=1
        echo "Port $PORT is occupied by PID $PID:"
        echo "  $COMMAND_LINE"
      fi
    done

    if [[ "$BLOCKED" -eq 1 ]]; then
      echo
      echo "Close the process above, or start LocalTube Dub Engine on another port:"
      echo "  LOCAL_DUB_PORT=8788 ./scripts/start_engine_macos.sh"
      exit 1
    fi

    for _ in {1..20}; do
      if ! lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
        break
      fi
      sleep 0.25
    done
  fi
fi

echo "Starting LocalTube Dub Engine on $HEALTH_URL"
echo "Keep this terminal open while using YouTube dubbing."
exec "$PYTHON_BIN" server/local_dub_server.py
