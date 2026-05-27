#!/usr/bin/env bash
# Build "Irma.app" and "Stop Irma.app" bundles from this directory.
#
# Both .app bundles are written into apps/launcher/ and are git-ignored
# (binary; rebuild whenever launch.sh / icon.png change). After build,
# drag them into /Applications (or ~/Applications) and add to the Dock
# or pin via Spotlight.

set -euo pipefail

cd "$(dirname "$0")"

SRC_ICON="icon.png"
ICNS="crown.icns"

if [[ ! -f "$SRC_ICON" ]]; then
  echo "missing $SRC_ICON" >&2
  exit 1
fi

# ---- Build crown.icns from icon.png -------------------------------------

build_icns() {
  local iconset="crown.iconset"
  rm -rf "$iconset" "$ICNS"
  mkdir -p "$iconset"
  for spec in \
    "16:icon_16x16.png" \
    "32:icon_16x16@2x.png" \
    "32:icon_32x32.png" \
    "64:icon_32x32@2x.png" \
    "128:icon_128x128.png" \
    "256:icon_128x128@2x.png" \
    "256:icon_256x256.png" \
    "512:icon_256x256@2x.png" \
    "512:icon_512x512.png" \
    "1024:icon_512x512@2x.png"; do
    size=${spec%%:*}
    name=${spec#*:}
    sips -z "$size" "$size" "$SRC_ICON" --out "$iconset/$name" >/dev/null
  done
  iconutil -c icns "$iconset" -o "$ICNS"
  rm -rf "$iconset"
}

build_icns

# ---- App bundle factory --------------------------------------------------

build_app() {
  local app_name="$1"   # e.g. "Irma" or "Stop Irma"
  local exec_name="$2"  # e.g. "Irma" or "StopIrma" (no spaces)
  local script="$3"     # e.g. "launch.sh" or "stop.sh"

  local bundle="${app_name}.app"
  rm -rf "$bundle"
  mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"

  # Info.plist with the executable name templated in.
  sed "s/__EXEC__/${exec_name}/g; s/<string>Irma<\\/string>/<string>${app_name}<\\/string>/" Info.plist \
    > "$bundle/Contents/Info.plist"

  # The "binary" is just our shell script.
  cp "$script" "$bundle/Contents/MacOS/$exec_name"
  chmod +x "$bundle/Contents/MacOS/$exec_name"

  # Icon.
  cp "$ICNS" "$bundle/Contents/Resources/crown.icns"

  echo "  built $bundle"
}

echo "building app bundles…"
build_app "Irma"        "Irma"     "launch.sh"
build_app "Stop Irma"   "StopIrma" "stop.sh"

echo ""
echo "Done. Bundles:"
echo "  $(pwd)/Irma.app"
echo "  $(pwd)/Stop Irma.app"
echo ""
echo "Try it: open 'Irma.app'"
echo "Install: mv {Irma,'Stop Irma'}.app /Applications/  (or ~/Applications)"
