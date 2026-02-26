#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="PromptTool.app"
DEST_ARG="${1:-}"
if [[ -z "${DEST_ARG}" ]]; then
  APP_DIR="${ROOT_DIR}/${APP_NAME}"
elif [[ "${DEST_ARG}" == *.app ]]; then
  APP_DIR="${DEST_ARG}"
else
  APP_DIR="${DEST_ARG}/${APP_NAME}"
fi
ARCH="$(uname -m)"
RUNTIME_ID="osx-x64"
if [[ "${ARCH}" == "arm64" ]]; then
  RUNTIME_ID="osx-arm64"
fi
PUBLISH_DIR="${ROOT_DIR}/.publish/${RUNTIME_ID}"

rm -rf "${PUBLISH_DIR}"
mkdir -p "${PUBLISH_DIR}"

dotnet publish "${ROOT_DIR}/PromptTool" -c Release -r "${RUNTIME_ID}" --self-contained true -p:PublishSingleFile=true -o "${PUBLISH_DIR}"

rm -rf "${APP_DIR}"
mkdir -p "${APP_DIR}/Contents/MacOS"
mkdir -p "${APP_DIR}/Contents/Resources"

cp -R "${PUBLISH_DIR}/"* "${APP_DIR}/Contents/MacOS/"

cat > "${APP_DIR}/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>PromptTool</string>
  <key>CFBundleDisplayName</key><string>PromptTool</string>
  <key>CFBundleIdentifier</key><string>com.prompttool.app</string>
  <key>CFBundleVersion</key><string>1.0.0</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleExecutable</key><string>PromptTool</string>
  <key>CFBundleIconFile</key><string>PromptTool.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
</dict>
</plist>
PLIST

ICONSET_DIR="${ROOT_DIR}/PromptTool/Assets/Icon.iconset"
ICON_PNG="${ROOT_DIR}/PromptTool/Assets/Icon.png"
ICON_DEST="${APP_DIR}/Contents/Resources/PromptTool.icns"
if [[ -d "${ICONSET_DIR}" ]]; then
  iconutil -c icns "${ICONSET_DIR}" -o "${ICON_DEST}" || true
elif [[ -f "${ICON_PNG}" ]]; then
  cp "${ICON_PNG}" "${APP_DIR}/Contents/Resources/PromptTool.png"
fi

echo "Created ${APP_DIR}"
