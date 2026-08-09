from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from resume_agent.domain.models import ExtractedUnit, ExtractionResult, ExtractionStatus

EXTRACTOR_VERSION = "python-docx-ordered-1"


def iter_blocks(document: Document):
    body = document.element.body
    paragraph_index = 0
    table_index = 0
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph_index += 1
            yield "paragraph", paragraph_index, Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            table_index += 1
            yield "table", table_index, Table(child, document)


def extract_docx(path: Path, file_id: str) -> ExtractionResult:
    try:
        document = Document(str(path))
        units: list[ExtractedUnit] = []
        for kind, index, block in iter_blocks(document):
            if kind == "paragraph":
                text = block.text.strip()
            else:
                rows = []
                for row in block.rows:
                    values = [cell.text.strip().replace("\n", " / ") for cell in row.cells]
                    if any(values):
                        rows.append(" | ".join(values))
                text = "\n".join(rows)
            if text:
                units.append(
                    ExtractedUnit(
                        locator_kind=kind,
                        locator_value=str(index),
                        text=text,
                        method="native",
                    )
                )
        inline_shapes = len(document.inline_shapes)
        error = None
        if inline_shapes and not units:
            error = f"DOCX 含 {inline_shapes} 个图片/嵌入对象但无可提取文本，需要人工复核"
        status = ExtractionStatus.EXTRACTED if units else ExtractionStatus.EMPTY
        return ExtractionResult(
            file_id=file_id,
            status=status,
            units=units,
            expected_units=len(units),
            covered_units=len(units),
            error=error,
            extractor_version=EXTRACTOR_VERSION,
        )
    except Exception as exc:
        return ExtractionResult(
            file_id=file_id,
            status=ExtractionStatus.FAILED,
            error=str(exc),
            extractor_version=EXTRACTOR_VERSION,
        )
