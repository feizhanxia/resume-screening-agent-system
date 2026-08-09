from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pypdfium2 as pdfium

from resume_agent.domain.models import ExtractedUnit, ExtractionResult, ExtractionStatus
from resume_agent.extraction.ocr import (
    command_with_tessdata,
    find_tesseract,
    rapid_ocr_image,
    resolve_languages,
)

EXTRACTOR_VERSION = "pdfium-1"
MIN_TEXT_CHARS = 24


def _ocr_page(page: object, languages: str = "chi_sim+eng") -> tuple[str, str | None]:
    executable = find_tesseract()
    try:
        bitmap = page.render(scale=2.2)
        image = bitmap.to_pil()
        with tempfile.TemporaryDirectory(prefix="resume-agent-ocr-") as temp_dir:
            image_path = Path(temp_dir) / "page.png"
            image.save(image_path)
            if not executable:
                return rapid_ocr_image(image_path)
            selected_languages = resolve_languages(executable, languages)
            if not selected_languages:
                return rapid_ocr_image(image_path)
            command = command_with_tessdata(
                [
                    executable,
                    str(image_path.resolve()),
                    "stdout",
                    "-l",
                    selected_languages,
                    "--psm",
                    "6",
                ]
            )
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if result.returncode != 0:
                return rapid_ocr_image(image_path)
        return result.stdout.strip(), None
    except Exception as exc:  # native renderer/OCR errors vary by platform
        return "", str(exc)


def extract_pdf(path: Path, file_id: str, ocr_languages: str = "chi_sim+eng") -> ExtractionResult:
    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        message = str(exc)
        status = (
            ExtractionStatus.ENCRYPTED if "password" in message.lower() else ExtractionStatus.FAILED
        )
        return ExtractionResult(
            file_id=file_id,
            status=status,
            error=message,
            extractor_version=EXTRACTOR_VERSION,
        )

    units: list[ExtractedUnit] = []
    errors: list[str] = []
    ocr_used = False
    page_count = len(document)
    for index in range(page_count):
        page_no = index + 1
        try:
            page = document[index]
            text_page = page.get_textpage()
            text = text_page.get_text_range().strip()
            method = "native"
            status = "success"
            if len("".join(text.split())) < MIN_TEXT_CHARS:
                ocr_text, ocr_error = _ocr_page(page, ocr_languages)
                if ocr_text:
                    text = ocr_text
                    method = "ocr"
                    ocr_used = True
                elif not text:
                    status = "empty"
                    if ocr_error:
                        errors.append(f"第 {page_no} 页：{ocr_error}")
            units.append(
                ExtractedUnit(
                    locator_kind="page",
                    locator_value=str(page_no),
                    text=text,
                    method=method,
                    status=status,
                )
            )
        except Exception as exc:
            errors.append(f"第 {page_no} 页：{exc}")
            units.append(
                ExtractedUnit(
                    locator_kind="page",
                    locator_value=str(page_no),
                    text="",
                    method="failed",
                    status="failed",
                )
            )

    covered = sum(unit.status in {"success", "empty"} for unit in units)
    nonempty = any(unit.text.strip() for unit in units)
    if covered < page_count:
        final_status = ExtractionStatus.FAILED
    elif not nonempty:
        final_status = ExtractionStatus.EMPTY
    elif ocr_used:
        final_status = ExtractionStatus.OCR
    else:
        final_status = ExtractionStatus.EXTRACTED
    return ExtractionResult(
        file_id=file_id,
        status=final_status,
        units=units,
        expected_units=page_count,
        covered_units=covered,
        error="；".join(errors) or None,
        extractor_version=EXTRACTOR_VERSION,
    )
