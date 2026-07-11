#!/usr/bin/env bash
# Start (or cleanly restart) the SINGLE live-coach feed process.
#
# Guarantees, in order:
#   1. No other `hstracker live` process survives (kills zombies from any
#      previous session — detached children outlive their shell wrappers).
#   2. The feed writes to a FRESH per-run log file in append mode, so no
#      truncation races with a tail -F reader are possible.
#   3. The feed is verified alive after startup; a dead-on-arrival feed
#      fails loudly with its output instead of silently doing nothing.
#
# Usage: ./coach_feed.sh [log-file]
# Prints FEED_PID=<pid> and LOG=<path> on success. Exit 1 on any failure.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Kill every existing feed and verify zero remain (zombie hygiene).
pkill -f "hstracker live" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do
    pgrep -f "hstracker live" >/dev/null || break
    sleep 0.3
    pkill -9 -f "hstracker live" 2>/dev/null || true
done
if pgrep -f "hstracker live" >/dev/null; then
    echo "ERROR: could not kill existing hstracker live process(es):" >&2
    pgrep -fa "hstracker live" >&2
    exit 1
fi

# 2. Fresh log file, append-only writer.
LOG="${1:-/tmp/hst_coach_$(date +%Y%m%d_%H%M%S).log}"
: > "$LOG"
PYTHONUNBUFFERED=1 nohup ./hst live >> "$LOG" 2>&1 &
FEED_PID=$!

# 3. Verify it survived startup and found the Hearthstone log directory.
sleep 2
if ! kill -0 "$FEED_PID" 2>/dev/null; then
    echo "ERROR: feed died at startup. Output:" >&2
    cat "$LOG" >&2
    exit 1
fi
if ! grep -q "^watching " "$LOG"; then
    echo "WARNING: feed running but no 'watching <dir>' line yet — is Hearthstone running?" >&2
fi

echo "FEED_PID=$FEED_PID"
echo "LOG=$LOG"
