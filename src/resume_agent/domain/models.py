from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ExtractionStatus(StrEnum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    OCR = "ocr"
    INVENTORY_ONLY = "inventory_only"
    EMPTY = "empty"
    ENCRYPTED = "encrypted"
    FAILED = "failed"


class CandidateState(StrEnum):
    DISCOVERED = "discovered"
    EXTRACTING = "extracting"
    NORMALIZING = "normalizing"
    READY_FOR_ANALYSIS = "ready_for_analysis"
    ANALYZING = "analyzing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class CriterionKind(StrEnum):
    REQUIRED = "required"
    SCORED = "scored"
    BONUS = "bonus"


class Conclusion(StrEnum):
    MATCH = "match"
    NO_MATCH = "no_match"
    UNCERTAIN = "uncertain"


class MaterialFile(BaseModel):
    file_id: str
    candidate_id: str
    absolute_path: Path
    relative_path: str
    media_type: str
    material_role: str = "unknown"
    content_hash: str
    size: int
    mtime_ns: int
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    active: bool = True


class CandidatePackage(BaseModel):
    candidate_id: str
    display_name: str
    root_path: Path
    relative_dir: str
    package_hash: str
    files: list[MaterialFile] = Field(default_factory=list)


class ScanResult(BaseModel):
    root_path: Path
    candidates: list[CandidatePackage]
    unassigned_files: list[Path] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def file_count(self) -> int:
        return sum(len(candidate.files) for candidate in self.candidates)


class ExtractedUnit(BaseModel):
    locator_kind: Literal["page", "paragraph", "table", "image", "file"]
    locator_value: str
    text: str
    method: str
    status: str = "success"


class ExtractionResult(BaseModel):
    file_id: str
    status: ExtractionStatus
    units: list[ExtractedUnit] = Field(default_factory=list)
    expected_units: int = 0
    covered_units: int = 0
    error: str | None = None
    extractor_version: str = "1"

    @property
    def text(self) -> str:
        return "\n".join(unit.text for unit in self.units if unit.text.strip())


class Criterion(BaseModel):
    criterion_id: str
    name: str
    definition: str
    kind: CriterionKind = CriterionKind.SCORED
    weight: float = Field(default=10, ge=0, le=100)
    enabled: bool = True
    requires_external_fact: bool = False
    version: int = 1


class Evidence(BaseModel):
    file_id: str
    relative_path: str
    locator_kind: str
    locator_value: str
    quote: str = Field(max_length=500)


class Judgment(BaseModel):
    criterion_id: str
    conclusion: Conclusion
    confidence: float = Field(default=0.5, ge=0, le=1)
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    needs_external_fact: bool = False


class CandidateFacts(BaseModel):
    name: str | None = None
    highest_degree: str | None = None
    undergraduate_school: str | None = None
    current_or_last_company: str | None = None
    work_years: float | None = None
    skills: list[str] = Field(default_factory=list)
    summary: str = ""


class AnalysisResult(BaseModel):
    candidate_id: str
    facts: CandidateFacts = Field(default_factory=CandidateFacts)
    judgments: list[Judgment]
    recommendation: Literal["recommended", "possible", "not_recommended", "review"] = "review"
    overall_reason: str = ""
    score: float = 0
    model: str = ""
    prompt_version: str = "1"

    @field_validator("judgments")
    @classmethod
    def unique_criteria(cls, value: list[Judgment]) -> list[Judgment]:
        ids = [item.criterion_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("judgments contains duplicate criterion_id")
        return value


class RunConfig(BaseModel):
    worker_count: int = Field(default=8, ge=1, le=32)
    extraction_concurrency: int = Field(default=8, ge=1, le=32)
    analysis_concurrency: int = Field(default=8, ge=1, le=32)
    max_retries_per_resume: int = Field(default=2, ge=0, le=5)
    max_loop_steps: int = Field(default=20, ge=5, le=100)
    excel_flush_every: int = Field(default=20, ge=1, le=200)
    model: str = "deepseek-v4-flash"
    audit_model: str = "deepseek-v4-pro"
    api_base: str = "https://api.deepseek.com"
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    redact_pii: bool = True


class ProgressEvent(BaseModel):
    event: str
    candidate_id: str | None = None
    message: str = ""
    completed: int = 0
    total: int = 0
    worker: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
