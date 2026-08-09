from __future__ import annotations

import subprocess
from pathlib import Path

from resume_agent.domain.models import ExtractedUnit, ExtractionResult, ExtractionStatus
from resume_agent.extraction.ocr import (
    command_with_tessdata,
    find_tesseract,
    rapid_ocr_image,
    resolve_languages,
)

EXTRACTOR_VERSION = "tesseract-image-1"


def extract_image(path: Path, file_id: str, languages: str = "chi_sim+eng") -> ExtractionResult:
    executable = find_tesseract()
    if not executable:
        text, error = rapid_ocr_image(path)
        return _result(file_id, text, error, "rapidocr")
    languages = resolve_languages(executable, languages)
    if not languages:
        text, error = rapid_ocr_image(path)
        return _result(file_id, text, error, "rapidocr")
    try:
        command = command_with_tessdata(
            [executable, str(path.resolve()), "stdout", "-l", languages, "--psm", "6"]
        )
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        text = result.stdout.strip()
        if result.returncode != 0:
            text, error = rapid_ocr_image(path)
            return _result(file_id, text, error or result.stderr.strip(), "rapidocr")
        return _result(file_id, text, None, "tesseract")
    except Exception as exc:
        text, error = rapid_ocr_image(path)
        return _result(file_id, text, error or str(exc), "rapidocr")


def _result(file_id: str, text: str, error: str | None, method: str) -> ExtractionResult:
    if text:
        status = ExtractionStatus.OCR
    elif error:
        status = ExtractionStatus.FAILED
    else:
        status = ExtractionStatus.EMPTY
    return ExtractionResult(
        file_id=file_id,
        status=status,
        units=[
            ExtractedUnit(
                locator_kind="image",
                locator_value="1",
                text=text,
                method=method,
                status="success" if text else ("failed" if error else "empty"),
            )
        ],
        expected_units=1,
        covered_units=1 if not error else 0,
        error=error,
        extractor_version=EXTRACTOR_VERSION,
    )
