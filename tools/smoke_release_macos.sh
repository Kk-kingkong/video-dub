#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_ZIP="${1:-}"
EXTENSION_ID="${2:-}"
VERSION="${3:-}"

if [[ ! -f "$ENGINE_ZIP" || ! "$EXTENSION_ID" =~ ^[a-p]{32}$ || -z "$VERSION" ]]; then
  echo "Usage: ./tools/smoke_release_macos.sh <engine.zip> <extension-id> <version>"
  exit 1
fi
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/localtube-release-smoke.XXXXXX")"
trap 'rm -rf "$TEMP_ROOT"' EXIT
unzip -q "$ENGINE_ZIP" -d "$TEMP_ROOT"
HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
  arm64|aarch64) PACKAGE_ARCH="arm64" ;;
  x86_64|amd64) PACKAGE_ARCH="x64" ;;
  *) echo "Unsupported smoke-test architecture: $HOST_ARCH"; exit 1 ;;
esac
ENGINE_ROOT="$TEMP_ROOT/LocalTube-Dub-Engine-v$VERSION-macOS-$PACKAGE_ARCH"
if [[ ! -d "$ENGINE_ROOT" ]]; then
  echo "Engine archive has an unexpected top-level folder."
  exit 1
fi
if [[ ! -x "$ENGINE_ROOT/.venv/bin/python" || ! -f "$ENGINE_ROOT/.venv/runtime-lock.json" ]]; then
  echo "Release package is missing its private runtime."
  exit 1
fi
"$ENGINE_ROOT/.venv/bin/python" -c 'import curl_cffi, edge_tts, sherpa_onnx, yt_dlp; import shutil; raise SystemExit(0 if shutil.which("ffmpeg") else 1)'

for command_file in "$ENGINE_ROOT"/*.command; do
  if [[ ! -x "$command_file" ]]; then
    echo "Double-click command lost executable permissions: $command_file"
    exit 1
  fi
  bash -n "$command_file"
done

PLIST_PATH="$TEMP_ROOT/com.localtube.dub.engine.http.plist"
MANIFEST_PATH="$TEMP_ROOT/com.localtube.dub.engine.json"
RUNTIME_DIR="$TEMP_ROOT/runtime"
LOG_DIR="$TEMP_ROOT/logs"
LOCAL_DUB_INSTALL_DRY_RUN=1 \
LOCAL_DUB_LAUNCH_AGENT_PATH="$PLIST_PATH" \
LOCAL_DUB_NATIVE_MANIFEST_PATH="$MANIFEST_PATH" \
LOCAL_DUB_RUNTIME_DIR="$RUNTIME_DIR" \
LOCAL_DUB_LOG_DIR="$LOG_DIR" \
  "$ENGINE_ROOT/Install LocalTube Dub Engine.command"

"$RUNTIME_DIR/.venv/bin/python" - "$MANIFEST_PATH" "$PLIST_PATH" "$RUNTIME_DIR" "$EXTENSION_ID" "$VERSION" "$PACKAGE_ARCH" <<'PY'
import json
import plistlib
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
plist_path = Path(sys.argv[2])
engine_root = Path(sys.argv[3]).resolve()
extension_id = sys.argv[4]
version = sys.argv[5]
architecture = sys.argv[6]
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("name") != "com.localtube.dub.engine":
    raise SystemExit("Native Host name mismatch")
if manifest.get("allowed_origins") != [f"chrome-extension://{extension_id}/"]:
    raise SystemExit("Native Host allowed_origins mismatch")
if Path(manifest.get("path", "")).resolve() != engine_root / "companion" / "native_host_launcher_macos.sh":
    raise SystemExit("Native Host launcher path mismatch")
with plist_path.open("rb") as source:
    plist = plistlib.load(source)
if plist.get("Label") != "com.localtube.dub.engine.http" or not plist.get("RunAtLoad"):
    raise SystemExit("LaunchAgent payload mismatch")
release = json.loads((engine_root / "release.json").read_text(encoding="utf-8"))
if release.get("version") != version or int(release.get("protocolVersion") or 0) < 2:
    raise SystemExit("Engine release protocol metadata mismatch")
if release.get("platform") != "macos" or release.get("architecture") != architecture or release.get("bundledRuntime") is not True:
    raise SystemExit("Engine release runtime metadata mismatch")
lock = json.loads((engine_root / ".venv" / "runtime-lock.json").read_text(encoding="utf-8"))
if lock.get("architecture") != architecture or lock.get("pythonExecutable") != "bin/python":
    raise SystemExit("private runtime lock mismatch")
PY

"$RUNTIME_DIR/.venv/bin/python" -c 'import curl_cffi, edge_tts, sherpa_onnx, yt_dlp; import shutil; raise SystemExit(0 if shutil.which("ffmpeg") else 1)'
LOCAL_DUB_HOST=127.0.0.1 \
LOCAL_DUB_PORT=18787 \
  "$RUNTIME_DIR/.venv/bin/python" "$RUNTIME_DIR/server/local_dub_server.py" >"$TEMP_ROOT/engine.log" 2>&1 &
ENGINE_PID=$!
cleanup_engine() {
  kill "$ENGINE_PID" >/dev/null 2>&1 || true
  wait "$ENGINE_PID" >/dev/null 2>&1 || true
}
trap 'cleanup_engine; rm -rf "$TEMP_ROOT"' EXIT
for _ in {1..40}; do
  if curl -fsS --max-time 1 http://127.0.0.1:18787/api/health 2>/dev/null | "$RUNTIME_DIR/.venv/bin/python" -c 'import json,sys; p=json.load(sys.stdin); raise SystemExit(0 if int(p.get("protocolVersion") or 0) >= 2 and p.get("ytDlp") and p.get("edgeTts") else 1)' >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
if ! curl -fsS --max-time 1 http://127.0.0.1:18787/api/health >/dev/null 2>&1; then
  echo "Packaged Engine did not pass its isolated health check."
  cat "$TEMP_ROOT/engine.log" >&2 || true
  exit 1
fi
cleanup_engine
trap 'rm -rf "$TEMP_ROOT"' EXIT

LOCAL_DUB_UNINSTALL_DRY_RUN=1 \
LOCAL_DUB_NATIVE_MANIFEST_PATH="$MANIFEST_PATH" \
LOCAL_DUB_RUNTIME_DIR="$RUNTIME_DIR" \
  "$ENGINE_ROOT/companion/uninstall_native_host_macos.sh"

echo "macOS release installer smoke test ok: $VERSION / $EXTENSION_ID"
