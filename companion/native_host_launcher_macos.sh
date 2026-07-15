#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_PYTHON="$SCRIPT_DIR/../.venv/bin/python"
RUNTIME_BIN="$SCRIPT_DIR/../.venv/bin"
export PATH="$RUNTIME_BIN:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

PYTHON_BIN="${LOCALTUBE_DUB_PYTHON:-}"
PYTHON_PATH_FILE="$SCRIPT_DIR/.localtube_python_path"
if [[ -z "$PYTHON_BIN" && -x "$RUNTIME_PYTHON" ]]; then
  PYTHON_BIN="$RUNTIME_PYTHON"
fi
if [[ -z "$PYTHON_BIN" && -s "$PYTHON_PATH_FILE" ]]; then
  IFS= read -r CONFIGURED_PYTHON < "$PYTHON_PATH_FILE" || true
  if [[ -n "${CONFIGURED_PYTHON:-}" && -x "$CONFIGURED_PYTHON" ]]; then
    PYTHON_BIN="$CONFIGURED_PYTHON"
  fi
fi

if [[ -z "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "LocalTube Dub Native Host: python3 not found" >&2
  exit 127
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/native_host.py"
