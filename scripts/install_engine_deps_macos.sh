#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${LOCAL_DUB_PYTHON:-}"

python_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

if [[ -z "$PYTHON_BIN" ]]; then
  for CANDIDATE in /opt/homebrew/bin/python3 /usr/local/bin/python3 "$(command -v python3 || true)"; do
    if [[ -n "$CANDIDATE" && -x "$CANDIDATE" ]] && python_supported "$CANDIDATE"; then
      PYTHON_BIN="$CANDIDATE"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]] || ! python_supported "$PYTHON_BIN"; then
  if command -v brew >/dev/null 2>&1; then
    echo "LocalTube Dub needs Python 3.10 or newer. Installing current Python with Homebrew..."
    brew install python
    PYTHON_BIN="$(brew --prefix)/bin/python3"
  else
    echo "LocalTube Dub needs Python 3.10 or newer, but only an older system Python was found."
    echo "Install Python 3 from https://www.python.org/downloads/ or Homebrew, then run this script again."
    exit 1
  fi
fi

if ! python_supported "$PYTHON_BIN"; then
  echo "The selected Python is still older than 3.10: $PYTHON_BIN"
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -U pip yt-dlp curl_cffi edge-tts
"$VENV_DIR/bin/python" -m yt_dlp --version
"$VENV_DIR/bin/python" -m edge_tts --version
printf '%s\n' "$VENV_DIR/bin/python" > "$ROOT_DIR/companion/.localtube_python_path"

cat <<'MSG'

LocalTube Dub Engine dependencies are ready.
The Engine uses a private project virtual environment, so Chrome and Terminal
always run the same modern Python and yt-dlp after a computer restart.
The optional curl_cffi package lets yt-dlp use browser-like TLS impersonation,
which is more stable for YouTube subtitle requests on some macOS/Python setups.
The edge-tts package enables the optional no-key "Natural online" neural voices.
Caption text is sent to Microsoft only after that voice mode is selected.
Start the Engine with:
  ./scripts/start_engine_macos.sh

MSG
