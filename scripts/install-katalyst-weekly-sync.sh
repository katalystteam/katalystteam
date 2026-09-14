#!/bin/bash
# Install Monday 12:00 AM local launchd job for dashboard + GHL call notes sync.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$ROOT/scripts/com.katalyst.weekly-sync.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.katalyst.weekly-sync.plist"
LABEL="com.katalyst.weekly-sync"
UID_NUM="$(id -u)"

mkdir -p "$ROOT/sync_logs"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"

launchctl bootout "gui/$UID_NUM" "$PLIST_DST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST_DST"
launchctl enable "gui/$UID_NUM/$LABEL"

echo "Installed $LABEL"
echo "Schedule: every Monday at 12:00 AM (local time)"
echo "Runs: $ROOT/run_katalyst_sync.sh"
echo "Logs: $ROOT/sync_logs/cron.log"
echo ""
launchctl print "gui/$UID_NUM/$LABEL" | rg -n "state =|path =|last exit|runs =|next run|schedule" || launchctl print "gui/$UID_NUM/$LABEL"
