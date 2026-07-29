#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${LOCAL_DUB_PYTHON:-}"

if [[ -f "$VENV_DIR/runtime-lock.json" ]]; then
  if [[ ! -x "$VENV_DIR/bin/python" || ! -x "$VENV_DIR/bin/ffmpeg" ]]; then
    echo "The bundled LocalTube Dub runtime is incomplete. Download the matching Engine package again."
    exit 1
  fi
  "$VENV_DIR/bin/python" - "$VENV_DIR/runtime-lock.json" <<'PY'
import importlib.util
import json
import sys
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
required = {"yt_dlp", "curl_cffi", "edge_tts", "sherpa_onnx"}
missing = sorted(name for name in required if importlib.util.find_spec(name) is None)
if lock.get("bundledRuntime") is not True or lock.get("pythonExecutable") != "bin/python" or missing:
    raise SystemExit("Bundled runtime verification failed: " + ", ".join(missing or ["invalid runtime lock"]))
PY
  printf '%s\n' "$VENV_DIR/bin/python" > "$ROOT_DIR/companion/.localtube_python_path"
  cat <<'MSG'

LocalTube Dub Engine bundled runtime is ready.
This customer package already contains its private Python, yt-dlp, Microsoft
natural-online voice dependencies, Kokoro runtime, and ffmpeg. No Homebrew,
pip, compiler, or extra command is needed for the main Engine installation.
The Kokoro voice model is intentionally not included; install it explicitly
from the extension after the Engine is connected.

MSG
  exit 0
fi

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
