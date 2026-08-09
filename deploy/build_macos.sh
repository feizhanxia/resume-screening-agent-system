#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  python3 -m venv "$PROJECT_DIR/.venv"
fi
"$PYTHON_BIN" -m pip install -e '.[dev]' pyinstaller
"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --onedir \
  --name='简历筛选工作台' \
  --osx-bundle-identifier='com.resumeagent.desktop' \
  --paths=src \
  --collect-data='rapidocr' \
  --add-data='resources:resources' \
  src/resume_agent/app/__main__.py
hdiutil create \
  -volname '简历筛选工作台' \
  -srcfolder "$PROJECT_DIR/dist/简历筛选工作台.app" \
  -ov \
  -format UDZO \
  "$PROJECT_DIR/dist/简历筛选工作台-macOS-arm64.dmg"
echo "构建完成：$PROJECT_DIR/dist/简历筛选工作台-macOS-arm64.dmg"
