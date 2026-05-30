#!/usr/bin/env bash
set -euo pipefail

# Builds the native-arch release binary. The original plan called for a
# `--arch arm64 --arch x86_64` universal build, which requires xcbuild
# (full Xcode). Under Xcode Command Line Tools only, that flag fails with
# "xcbuild executable does not exist". The user's dev machine is M2; the
# Tauri release recipe (Phase 5+) can re-do this with full Xcode for
# multi-arch when signing the production app.

cd "$(dirname "$0")"

mkdir -p bin
swift build -c release
ARCH_DIR=$(swift build -c release --show-bin-path)
cp "$ARCH_DIR/RemindersHelper" bin/irma-reminders-helper
chmod +x bin/irma-reminders-helper
file bin/irma-reminders-helper
