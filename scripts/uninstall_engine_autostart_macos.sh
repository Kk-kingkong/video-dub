#!/usr/bin/env bash
set -euo pipefail

LABEL="com.localtube.dub.engine.http"
DOMAIN="gui/$(id -u)"
PLIST_PATH="${LOCAL_DUB_LAUNCH_AGENT_PATH:-$HOME/Library/LaunchAgents/$LABEL.plist}"

if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
elif [[ -f "$PLIST_PATH" ]]; then
  launchctl bootout "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
fi

rm -f "$PLIST_PATH"
echo "Removed LocalTube Dub Engine auto-start: $PLIST_PATH"
