from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

_rapidocr_engine = None
_rapidocr_lock = threading.Lock()


def find_tesseract() -> str | None:
    configured = os.getenv("RESUME_AGENT_TESSERACT")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    executable_dir = Path(sys.executable).resolve().parent
    bundle_root = Path(getattr(sys, "_MEIPASS", executable_dir))
    candidates.extend(
        [
            executable_dir / "resources" / "tesseract" / "bin" / "tesseract",
            executable_dir / "resources" / "tesseract" / "tesseract.exe",
            bundle_root / "resources" / "tesseract" / "bin" / "tesseract",
            bundle_root / "resources" / "tesseract" / "tesseract.exe",
            Path(__file__).resolve().parents[3] / "resources" / "tesseract" / "bin" / "tesseract",
        ]
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)
    return shutil.which("tesseract")


def find_tessdata() -> Path | None:
    configured = os.getenv("TESSDATA_PREFIX")
    candidates = []
    if configured:
        candidates.append(Path(configured))
    executable_dir = Path(sys.executable).resolve().parent
    bundle_root = Path(getattr(sys, "_MEIPASS", executable_dir))
    candidates.extend(
        [
            executable_dir / "resources" / "tesseract" / "tessdata",
            bundle_root / "resources" / "tesseract" / "tessdata",
            Path(__file__).resolve().parents[3] / "resources" / "tesseract" / "tessdata",
        ]
    )
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*.traineddata")):
            return candidate
    return None


def command_with_tessdata(command: list[str]) -> list[str]:
    tessdata = find_tessdata()
    if tessdata:
        return [*command, "--tessdata-dir", str(tessdata)]
    return command


def supported_languages(executable: str) -> set[str]:
    try:
        result = subprocess.run(
            command_with_tessdata([executable, "--list-langs"]),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return {
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip() and "available languages" not in line.lower()
        }
    except Exception:
        return set()


def resolve_languages(executable: str, requested: str) -> str | None:
    available = supported_languages(executable)
    requested_parts = [part for part in requested.split("+") if part]
    selected = [part for part in requested_parts if part in available]
    if selected:
        return "+".join(selected)
    if "eng" in available:
        return "eng"
    return next(iter(sorted(available)), None)


def rapid_ocr_image(path: Path) -> tuple[str, str | None]:
    global _rapidocr_engine
    try:
        with _rapidocr_lock:
            if _rapidocr_engine is None:
                from rapidocr import RapidOCR

                _rapidocr_engine = RapidOCR()
            result = _rapidocr_engine(str(path.resolve()))
        texts = getattr(result, "txts", None) or ()
        return "\n".join(text.strip() for text in texts if text and text.strip()), None
    except Exception as exc:
        return "", f"离线 ONNX OCR 失败：{exc}"
