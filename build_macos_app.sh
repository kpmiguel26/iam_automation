#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="IAM Automation.app"
APP_ROOT="$PROJECT_ROOT/dist/$APP_NAME"
CONTENTS="$APP_ROOT/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
ICONSET="$(mktemp -d)/iam_automation.iconset"

cleanup() {
  rm -rf "$(dirname "$ICONSET")"
}
trap cleanup EXIT

PYTHON_BIN="${IAM_PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "[IAM] Missing virtual-environment Python: $PYTHON_BIN" >&2
  echo "[IAM] Run ./run.sh once, or set IAM_PYTHON_BIN." >&2
  exit 1
fi

mkdir -p "$MACOS" "$RESOURCES" "$ICONSET"

# Render the shared Qt SVG into the PNG sizes required by the macOS icon tool.
IAM_PROJECT_ROOT="$PROJECT_ROOT" IAM_ICONSET="$ICONSET" "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(os.environ["IAM_PROJECT_ROOT"])
iconset = Path(os.environ["IAM_ICONSET"])
renderer = QSvgRenderer(str(root / "iam_automation/static/preflight_icon.svg"))
for size in (16, 32, 128, 256, 512):
    for scale, suffix in ((1, ""), (2, "@2x")):
        pixels = size * scale
        image = QImage(QSize(pixels, pixels), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        image.save(str(iconset / f"icon_{size}x{size}{suffix}.png"))
PY

if command -v iconutil >/dev/null 2>&1 && iconutil -c icns "$ICONSET" -o "$RESOURCES/IAMAutomation.icns" 2>/dev/null; then
  ICON_ENTRY='<key>CFBundleIconFile</key><string>IAMAutomation</string>'
else
  echo "[IAM] iconutil could not build an ICNS file; using PNG fallback."
  cp "$ICONSET/icon_512x512.png" "$RESOURCES/IAMAutomation.png"
  ICON_ENTRY='<key>CFBundleIconFile</key><string>IAMAutomation.png</string>'
fi

cp "$PROJECT_ROOT/iam_automation/static/preflight_icon.svg" "$RESOURCES/preflight_icon.svg"

python3 - "$CONTENTS/Info.plist" "$ICON_ENTRY" <<'PY'
import plistlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
icon_entry = sys.argv[2]
icon_name = "IAMAutomation"
if "IAMAutomation.png" in icon_entry:
    icon_name = "IAMAutomation.png"
plist = {
    "CFBundleDisplayName": "IAM Automation",
    "CFBundleExecutable": "iam-automation",
    "CFBundleIdentifier": "com.kaiserpermanente.iamautomation",
    "CFBundleName": "IAM Automation",
    "CFBundlePackageType": "APPL",
    "CFBundleShortVersionString": "0.1.0",
    "CFBundleVersion": "0.1.0",
    "CFBundleIconFile": icon_name,
    "LSMinimumSystemVersion": "12.0",
    "NSHighResolutionCapable": True,
}
path.write_bytes(plistlib.dumps(plist, fmt=plistlib.FMT_XML))
PY

cat > "$MACOS/iam-automation" <<EOF
#!/bin/sh
set -e
PROJECT_ROOT="$(cd "$(dirname "\$0")/../../.." && pwd)"
exec "${PYTHON_BIN}" "\$PROJECT_ROOT/run_app.py" "\$@"
EOF
chmod +x "$MACOS/iam-automation"

echo "[IAM] Built: $APP_ROOT"
echo "[IAM] Open it with: open \"$APP_ROOT\""
