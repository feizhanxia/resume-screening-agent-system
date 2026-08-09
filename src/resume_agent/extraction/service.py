from __future__ import annotations

import asyncio

from resume_agent.domain.models import ExtractionResult, ExtractionStatus, MaterialFile
from resume_agent.extraction.docx import EXTRACTOR_VERSION as DOCX_VERSION
from resume_agent.extraction.docx import extract_docx
from resume_agent.extraction.image import EXTRACTOR_VERSION as IMAGE_VERSION
from resume_agent.extraction.image import extract_image
from resume_agent.extraction.pdf import EXTRACTOR_VERSION as PDF_VERSION
from resume_agent.extraction.pdf import extract_pdf
from resume_agent.storage.database import Database

MAX_EXTRACTABLE_BYTES = 100 * 1024 * 1024


class ExtractionService:
    def __init__(
        self, database: Database, concurrency: int = 8, ocr_languages: str = "chi_sim+eng"
    ):
        self.database = database
        self.semaphore = asyncio.Semaphore(concurrency)
        self.ocr_languages = ocr_languages

    @staticmethod
    def version_for(file: MaterialFile) -> str:
        suffix = file.absolute_path.suffix.lower()
        if suffix == ".pdf":
            return PDF_VERSION
        if suffix == ".docx":
            return DOCX_VERSION
        if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
            return IMAGE_VERSION
        return "inventory-1"

    async def extract(self, file: MaterialFile) -> ExtractionResult:
        version = self.version_for(file)
        cached = self.database.cached_extraction(file.file_id, version)
        if cached:
            return cached
        async with self.semaphore:
            suffix = file.absolute_path.suffix.lower()
            if suffix in {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"} and (
                file.size > MAX_EXTRACTABLE_BYTES
            ):
                result = ExtractionResult(
                    file_id=file.file_id,
                    status=ExtractionStatus.FAILED,
                    expected_units=1,
                    covered_units=0,
                    error="文件超过 100 MB 的自动提取安全上限，需要人工复核",
                    extractor_version=version,
                )
            elif suffix == ".pdf":
                result = await asyncio.to_thread(
                    extract_pdf, file.absolute_path, file.file_id, self.ocr_languages
                )
            elif suffix == ".docx":
                result = await asyncio.to_thread(extract_docx, file.absolute_path, file.file_id)
            elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
                result = await asyncio.to_thread(
                    extract_image, file.absolute_path, file.file_id, self.ocr_languages
                )
            else:
                result = ExtractionResult(
                    file_id=file.file_id,
                    status=ExtractionStatus.INVENTORY_ONLY,
                    expected_units=1,
                    covered_units=1,
                    extractor_version=version,
                )
            self.database.save_extraction(result)
            return result
