#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "arm64" ]]; then
  echo "This release script requires an Apple Silicon Mac." >&2
  exit 1
fi

PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
DIST_DIR="$PROJECT_DIR/dist"
APP_NAME="简历筛选工作台"
APP_DIR="$DIST_DIR/$APP_NAME.app"
APP_EXECUTABLE="$APP_DIR/Contents/MacOS/$APP_NAME"
DMG_PATH="$DIST_DIR/ResumeScreeningAgent-macOS-arm64.dmg"
ZIP_PATH="$DIST_DIR/ResumeScreeningAgent-macOS-arm64.zip"
HASH_PATH="$DIST_DIR/macos-SHA256.txt"
DEPENDENCY_PATH="$DIST_DIR/macos-dependencies.txt"
STAGING_DIR="$PROJECT_DIR/build/macos-dmg"
ZIP_STAGING_DIR="$PROJECT_DIR/build/macos-zip"

if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi

"$PYTHON_BIN" -m pip install --upgrade pip wheel
"$PYTHON_BIN" -m pip install -e '.[dev]'
APP_VERSION="$("$PYTHON_BIN" -c 'from resume_agent import __version__; print(__version__)')"
"$PYTHON_BIN" -m ruff check src tests deploy/windows/collect_licenses.py deploy/windows/create_portable.py
"$PYTHON_BIN" -m pytest

rm -rf "$APP_DIR" "$STAGING_DIR" "$ZIP_STAGING_DIR"
rm -f "$DMG_PATH" "$ZIP_PATH" "$HASH_PATH" "$DEPENDENCY_PATH"

export MACOSX_DEPLOYMENT_TARGET="11.0"
"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name="$APP_NAME" \
  --osx-bundle-identifier='com.resumeagent.desktop' \
  --target-architecture=arm64 \
  --paths=src \
  --collect-all=rapidocr \
  --collect-all=keyring \
  --hidden-import=keyring.backends.macOS \
  --add-data='resources:resources' \
  src/resume_agent/app/__main__.py

if [[ ! -x "$APP_EXECUTABLE" ]]; then
  echo "PyInstaller did not create the expected application executable." >&2
  exit 1
fi

RESOURCE_DIR="$APP_DIR/Contents/Resources"
LICENSE_DIR="$RESOURCE_DIR/licenses"
INFO_PLIST="$APP_DIR/Contents/Info.plist"
mkdir -p "$LICENSE_DIR"
cp LICENSE "$RESOURCE_DIR/LICENSE.txt"
cp THIRD_PARTY_NOTICES.md "$RESOURCE_DIR/THIRD_PARTY_NOTICES.md"
cp resources/tesseract/tessdata/LICENSE "$LICENSE_DIR/TESSERACT-TESSDATA-APACHE-2.0.txt"
SITE_PACKAGES="$("$PYTHON_BIN" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
"$PYTHON_BIN" deploy/windows/collect_licenses.py "$SITE_PACKAGES" "$LICENSE_DIR"
plutil -replace CFBundleShortVersionString -string "$APP_VERSION" "$INFO_PLIST"
plutil -replace CFBundleVersion -string "$APP_VERSION" "$INFO_PLIST"
plutil -replace LSMinimumSystemVersion -string "11.0" "$INFO_PLIST"

# Re-sign after adding license resources. Public Beta builds are ad-hoc signed and not notarized.
codesign --force --deep --sign - "$APP_DIR"
codesign --verify --deep --strict --verbose=2 "$APP_DIR"

QT_QPA_PLATFORM=offscreen RESUME_AGENT_SMOKE_TEST=1 "$APP_EXECUTABLE"

mkdir -p "$STAGING_DIR"
ditto "$APP_DIR" "$STAGING_DIR/$APP_NAME.app"
ln -s /Applications "$STAGING_DIR/Applications"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"
hdiutil verify "$DMG_PATH"

mkdir -p "$ZIP_STAGING_DIR"
ditto "$APP_DIR" "$ZIP_STAGING_DIR/ResumeScreeningAgent.app"
ditto -c -k --keepParent "$ZIP_STAGING_DIR/ResumeScreeningAgent.app" "$ZIP_PATH"
"$PYTHON_BIN" -m pip list --format=freeze > "$DEPENDENCY_PATH"

(
  cd "$DIST_DIR"
  shasum -a 256 "$(basename "$DMG_PATH")" "$(basename "$ZIP_PATH")" > "$(basename "$HASH_PATH")"
  shasum -a 256 -c "$(basename "$HASH_PATH")"
)

echo "macOS Apple Silicon build completed:"
echo "  DMG: $DMG_PATH"
echo "  ZIP: $ZIP_PATH"
echo "  Checksums: $HASH_PATH"
