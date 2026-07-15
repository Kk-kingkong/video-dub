#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL_NAME="${LOCAL_DUB_WHISPER_CPP_MODEL_NAME:-base}"
MODEL_DIR="${LOCAL_DUB_WHISPER_CPP_MODEL_DIR:-$HOME/Library/Application Support/LocalTube Dub/models}"
MODEL_PATH="$MODEL_DIR/ggml-${MODEL_NAME}.bin"
MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${MODEL_NAME}.bin"
PARTIAL_PATH="$MODEL_PATH.download"

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required for one-click whisper.cpp installation on macOS."
  echo "Install Homebrew from https://brew.sh, then run this script again."
  exit 1
fi

echo "Installing whisper.cpp and ffmpeg..."
brew install whisper-cpp ffmpeg

mkdir -p "$MODEL_DIR"
if [[ ! -f "$MODEL_PATH" || "$(stat -f%z "$MODEL_PATH" 2>/dev/null || echo 0)" -lt 50000000 ]]; then
  echo "Downloading multilingual Whisper ${MODEL_NAME} model to:"
  echo "  $MODEL_PATH"
  curl -L --fail --retry 3 --continue-at - --output "$PARTIAL_PATH" "$MODEL_URL"
  mv "$PARTIAL_PATH" "$MODEL_PATH"
else
  echo "Whisper model is already installed: $MODEL_PATH"
fi

WHISPER_BIN="$(command -v whisper-cli || command -v whisper-cpp || true)"
FFMPEG_BIN="$(command -v ffmpeg || true)"
if [[ -z "$WHISPER_BIN" || -z "$FFMPEG_BIN" || ! -f "$MODEL_PATH" ]]; then
  echo "Local Whisper installation did not complete correctly."
  exit 1
fi

ENGINE_HEALTH_URL="http://127.0.0.1:8787/api/health"
ENGINE_RESTART_URL="http://127.0.0.1:8787/api/restart"
if curl -fsS --max-time 2 "$ENGINE_HEALTH_URL" >/dev/null 2>&1; then
  echo "Restarting LocalTube Dub Engine so it can load local Whisper support..."
  curl -fsS --max-time 3 -X POST -H "content-type: application/json" -d '{}' "$ENGINE_RESTART_URL" >/dev/null 2>&1 || true
else
  echo "Starting LocalTube Dub Engine with local Whisper support..."
  nohup "$ROOT_DIR/scripts/start_engine_macos.sh" >>"${TMPDIR:-/tmp}/localtube-dub-engine.log" 2>&1 &
fi

cat <<MSG

LocalTube Dub local transcription is ready.
  whisper.cpp: $WHISPER_BIN
  ffmpeg:      $FFMPEG_BIN
  model:       $MODEL_PATH

The base multilingual model is about 142 MB and is used only on this Mac.
Return to the extension and click "检查 Engine" or "开始翻译".

MSG
