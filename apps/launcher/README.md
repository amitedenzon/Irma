# Irma launcher

A double-clickable macOS app that starts the FastAPI backend (`:8765`) and the
Tauri desktop shell (`tauri:dev`) in the background, plus a companion app to
stop them again.

## Build

```bash
cd apps/launcher
./build.sh
```

This produces two app bundles in `apps/launcher/`:

- `Irma.app`       — starts the backend + desktop. Re-launching while it's
                     already running is a no-op (you'll see a notification).
- `Stop Irma.app`  — kills the processes and frees port 8765.

Both bundles are git-ignored — rebuild whenever `launch.sh` or `icon.png`
changes.

## Install

```bash
mv Irma.app 'Stop Irma.app' /Applications/
```

Now they show up in Spotlight, Launchpad, and the Dock.

## Where things land

- API stdout/stderr → `~/Library/Logs/Irma/api.log`
- Desktop stdout/stderr → `~/Library/Logs/Irma/desktop.log`
- Running PIDs → `~/Library/Application Support/Irma/pids`

## Troubleshooting

**Nothing happens when I click Irma.app** — open `Console.app` and search for
`Irma` to see the launcher's error, or peek at the logs above.

**"uv not found" notification** — the launcher inherits a minimal `PATH` when
spawned from Finder. Edit `launch.sh` to add wherever `uv` lives, or export
`IRMA_LAUNCHER_PATH` in your shell rc.

**Already-running message but nothing is alive** — delete the stale pidfile:
```bash
rm ~/Library/Application\ Support/Irma/pids
```

**Port 8765 in use** — `Stop Irma.app` kills anything left on it.
