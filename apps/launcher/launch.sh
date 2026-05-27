#!/usr/bin/env bash
# Irma launcher — boots the FastAPI backend and the Tauri desktop shell
# in the background. Invoked by Irma.app when the user double-clicks it
# from Finder, the Dock, or Spotlight.
#
# Re-running while Irma is already alive is a no-op (shows a notification).

set -euo pipefail

REPO="/Users/amit/Documents/Code/Irma"
LOG_DIR="$HOME/Library/Logs/Irma"
STATE_DIR="$HOME/Library/Application Support/Irma"
PIDFILE="$STATE_DIR/pids"

mkdir -p "$LOG_DIR" "$STATE_DIR"

# GUI launches inherit a minimal PATH — add the usual Homebrew + system bins
# so `uv` and `npm` resolve. Adjust IRMA_LAUNCHER_PATH in ~/.zshrc to override.
export PATH="${IRMA_LAUNCHER_PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

notify() {
  /usr/bin/osascript -e "display notification \"$1\" with title \"Irma\""
}

# ---- Idempotence guard ----------------------------------------------------

is_alive() {
  local pid=$1
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

if [[ -f "$PIDFILE" ]]; then
  any_alive=false
  while IFS= read -r pid; do
    if is_alive "$pid"; then any_alive=true; break; fi
  done < "$PIDFILE"
  if $any_alive; then
    notify "Irma is already running"
    exit 0
  fi
  rm -f "$PIDFILE"
fi

# ---- Tool checks ----------------------------------------------------------

for tool in uv npm; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    notify "$tool not found on PATH — edit launch.sh / Info.plist."
    exit 1
  fi
done

# ---- Launch API (FastAPI on :8765) ---------------------------------------

API_LOG="$LOG_DIR/api.log"
cd "$REPO/services/api"
{
  echo
  echo "==== api start $(date '+%Y-%m-%d %H:%M:%S') ===="
} >> "$API_LOG"
nohup uv run uvicorn irma_api.app:create_app \
    --factory --reload --port 8765 \
    >> "$API_LOG" 2>&1 < /dev/null &
API_PID=$!

# ---- Launch desktop (Tauri dev shell) ------------------------------------

DESKTOP_LOG="$LOG_DIR/desktop.log"
cd "$REPO/apps/desktop"
{
  echo
  echo "==== desktop start $(date '+%Y-%m-%d %H:%M:%S') ===="
} >> "$DESKTOP_LOG"
nohup npm run tauri:dev \
    >> "$DESKTOP_LOG" 2>&1 < /dev/null &
DESKTOP_PID=$!

# ---- Persist PIDs --------------------------------------------------------

printf '%s\n%s\n' "$API_PID" "$DESKTOP_PID" > "$PIDFILE"

notify "API on :8765 · desktop building (first launch takes ~30s)…"
