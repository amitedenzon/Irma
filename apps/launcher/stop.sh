#!/usr/bin/env bash
# Stop the Irma backend + desktop processes started by launch.sh.
# Reads PIDs from ~/Library/Application Support/Irma/pids and kills the
# whole process group of each (so child processes — uvicorn workers,
# Vite, Cargo's tauri dev runner — also die).

set -uo pipefail

STATE_DIR="$HOME/Library/Application Support/Irma"
PIDFILE="$STATE_DIR/pids"

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"Irma\""
}

if [[ ! -f "$PIDFILE" ]]; then
  notify "Irma is not running (no pidfile)."
  exit 0
fi

killed=0
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  if kill -0 "$pid" 2>/dev/null; then
    # Kill the whole process group; ignore failures so we keep trying.
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    killed=$((killed + 1))
  fi
done < "$PIDFILE"

# Give them a moment, then force-kill anything still alive.
sleep 1
while IFS= read -r pid; do
  [[ -z "$pid" ]] && continue
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
done < "$PIDFILE"

# Best-effort: anything left on :8765 must die (uvicorn reload spawns
# children that don't always inherit the launcher's process group).
lsof -ti:8765 2>/dev/null | xargs -r kill -9 2>/dev/null || true

rm -f "$PIDFILE"
notify "Stopped Irma ($killed processes)."
