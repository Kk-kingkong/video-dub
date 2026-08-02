#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${LOCAL_DUB_PYTHON:-}"
RELEASE_METADATA="$ROOT_DIR/release.json"
CUSTOMER_RELEASE="${LOCAL_DUB_CUSTOMER_RELEASE:-0}"
SOURCE_DEVELOPMENT="${LOCAL_DUB_SOURCE_DEVELOPMENT:-0}"

if [[ "${1:-}" == "--source-development" ]]; then
  SOURCE_DEVELOPMENT=1
  shift
fi
if [[ $# -ne 0 ]]; then
  echo "Usage: ./scripts/install_engine_deps_macos.sh [--source-development]"
  exit 1
fi

if [[ "$CUSTOMER_RELEASE" == "1" || -e "$RELEASE_METADATA" || -e "$VENV_DIR/runtime-lock.json" ]]; then
  if [[ "$SOURCE_DEVELOPMENT" == "1" ]]; then
    echo "A bundled customer release cannot use source-development dependency installation."
    exit 1
  fi
  if [[ ! -f "$RELEASE_METADATA" || ! -f "$VENV_DIR/runtime-lock.json" ]]; then
    echo "The bundled LocalTube Dub runtime metadata is incomplete. Download and extract the matching Engine package again."
    exit 1
  fi
  if [[ ! -x "$VENV_DIR/bin/python" || ! -x "$VENV_DIR/bin/ffmpeg" || ! -f "$ROOT_DIR/scripts/assemble_engine_runtime.py" ]]; then
    echo "The bundled LocalTube Dub runtime is incomplete. Download the matching Engine package again."
    exit 1
  fi
  case "$(uname -m)" in
    arm64|aarch64) PACKAGE_ARCH="arm64" ;;
    x86_64|amd64) PACKAGE_ARCH="x64" ;;
    *) echo "This Engine package does not support the current Mac architecture."; exit 1 ;;
  esac
  "$VENV_DIR/bin/python" "$ROOT_DIR/scripts/assemble_engine_runtime.py" \
    --verify-runtime "$VENV_DIR" \
    --release-metadata "$RELEASE_METADATA" \
    --platform macos \
    --arch "$PACKAGE_ARCH"
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

if [[ "$SOURCE_DEVELOPMENT" != "1" ]]; then
  cat <<'MSG'
This directory is not a complete customer Engine release.
For a source checkout, explicitly run:
  ./scripts/install_engine_deps_macos.sh --source-development
Customer installers must use the bundled private runtime and never install
Homebrew or Python packages from the network.
MSG
  exit 1
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
This source-development setup may use Homebrew and pip. Customer release
packages do not use this path.
The Engine uses a private project virtual environment, so Chrome and Terminal
always run the same modern Python and yt-dlp after a computer restart.
The optional curl_cffi package lets yt-dlp use browser-like TLS impersonation,
which is more stable for YouTube subtitle requests on some macOS/Python setups.
The edge-tts package enables the optional no-key "Natural online" neural voices.
Caption text is sent to Microsoft only after that voice mode is selected.
Start the Engine with:
  ./scripts/start_engine_macos.sh

MSG
