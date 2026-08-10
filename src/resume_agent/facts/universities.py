from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from resume_agent.domain.models import AnalysisResult, Conclusion, Criterion
from resume_agent.llm.deepseek import calculate_score

CATALOG_RELATIVE_PATH = Path("resources/universities/university_catalog.json")
UNSUPPORTED_FACT_PATTERN = re.compile(
    r"排名|前\s*\d+|top\s*\d+|综合性|软科|qs|times|the\s", re.IGNORECASE
)


class UniversityRecord(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    categories: list[Literal["985", "211", "double_first_class"]]
    double_first_class_disciplines: list[str] = Field(default_factory=list)
    discipline_note: str = ""


class UniversityCatalogPayload(BaseModel):
    schema_version: int
    catalog_version: str
    counts: dict[str, int]
    sources: dict[str, dict[str, str]]
    institutions: list[UniversityRecord]


class UniversityMatch(BaseModel):
    status: Literal["matched", "not_found", "ambiguous"]
    query: str
    standard_name: str = ""
    categories: list[str] = Field(default_factory=list)
    catalog_version: str = ""


def normalize_university_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    normalized = re.sub(
        r"^(?:本科毕业于|毕业于|就读于|本科院校|毕业院校|学校|院校)[:：]?",
        "",
        normalized,
    )
    normalized = re.sub(r"[\s·•,，。;；:：'\"“”‘’()\[\]【】_\-]", "", normalized)
    return re.sub(r"校区$", "", normalized)


def _catalog_candidates() -> list[Path]:
    candidates: list[Path] = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / CATALOG_RELATIVE_PATH)
    candidates.extend(
        [
            Path(sys.executable).resolve().parent / CATALOG_RELATIVE_PATH,
            Path(__file__).resolve().parents[3] / CATALOG_RELATIVE_PATH,
        ]
    )
    return candidates


class UniversityCatalog:
    def __init__(self, payload: UniversityCatalogPayload):
        self.payload = payload
        self._index: dict[str, list[UniversityRecord]] = {}
        for record in payload.institutions:
            for value in (record.name, *record.aliases):
                key = normalize_university_name(value)
                if key:
                    self._index.setdefault(key, []).append(record)

    @classmethod
    def load(cls, path: Path) -> UniversityCatalog:
        payload = UniversityCatalogPayload.model_validate_json(path.read_text(encoding="utf-8"))
        return cls(payload)

    @classmethod
    def load_default(cls) -> UniversityCatalog:
        for path in _catalog_candidates():
            if path.is_file():
                return cls.load(path)
        raise FileNotFoundError(f"找不到内置院校目录：{CATALOG_RELATIVE_PATH}")

    def resolve(self, query: str) -> UniversityMatch:
        key = normalize_university_name(query)
        records = self._index.get(key, [])
        unique = {record.name: record for record in records}
        if not unique:
            return UniversityMatch(status="not_found", query=query)
        if len(unique) > 1:
            category_sets = {tuple(record.categories) for record in unique.values()}
            if len(category_sets) == 1:
                return UniversityMatch(
                    status="matched",
                    query=query,
                    standard_name=query,
                    categories=list(next(iter(unique.values())).categories),
                    catalog_version=self.payload.catalog_version,
                )
            return UniversityMatch(status="ambiguous", query=query)
        record = next(iter(unique.values()))
        return UniversityMatch(
            status="matched",
            query=query,
            standard_name=record.name,
            categories=list(record.categories),
            catalog_version=self.payload.catalog_version,
        )

    def evidence_supports(self, standard_name: str, quotes: list[str]) -> bool:
        record = next(
            (item for item in self.payload.institutions if item.name == standard_name), None
        )
        if record is None:
            return False
        forms = {
            normalize_university_name(value)
            for value in (record.name, *record.aliases)
            if normalize_university_name(value)
        }
        return any(
            form in normalize_university_name(quote)
            for quote in quotes
            for form in forms
        )

    @staticmethod
    def query_evidence_supports(query: str, quotes: list[str]) -> bool:
        key = normalize_university_name(query)
        return bool(key) and any(key in normalize_university_name(quote) for quote in quotes)


def _requested_categories(criterion: Criterion) -> tuple[list[str], bool] | None:
    text = unicodedata.normalize("NFKC", f"{criterion.name} {criterion.definition}").lower()
    categories = []
    if "985" in text:
        categories.append("985")
    if "211" in text:
        categories.append("211")
    if "双一流" in text:
        categories.append("double_first_class")
    if not categories:
        return None
    if UNSUPPORTED_FACT_PATTERN.search(text):
        return None
    if "double_first_class" in categories and ("一流学科" in text or "双一流学科" in text):
        return None
    graduate_stages = ("硕士院校", "研究生院校", "博士院校")
    if any(stage in text for stage in graduate_stages) and "本科" not in text:
        return None
    require_all = any(connector in text for connector in ("同时", "均为", "且为", "并且"))
    return categories, require_all


def _refresh_score_and_recommendation(
    result: AnalysisResult, criteria: list[Criterion]
) -> None:
    active = [item for item in criteria if item.enabled]
    result.score = calculate_score(result.judgments, active)
    kinds = {item.criterion_id: item.kind for item in active}
    required = [item for item in result.judgments if kinds.get(item.criterion_id) == "required"]
    if any(item.conclusion == Conclusion.NO_MATCH for item in required):
        result.recommendation = "not_recommended"
    elif any(item.conclusion == Conclusion.UNCERTAIN for item in required):
        result.recommendation = "review"
    elif result.score >= 70:
        result.recommendation = "recommended"
    elif result.score >= 50:
        result.recommendation = "possible"
    else:
        result.recommendation = "not_recommended"


def apply_university_resolutions(
    result: AnalysisResult,
    criteria: list[Criterion],
    catalog: UniversityCatalog,
) -> int:
    school = (result.facts.undergraduate_school or "").strip()
    criteria_by_id = {item.criterion_id: item for item in criteria if item.enabled}
    resolved = 0
    for judgment in result.judgments:
        criterion = criteria_by_id.get(judgment.criterion_id)
        requested = _requested_categories(criterion) if criterion else None
        if not criterion or not criterion.requires_external_fact or not requested:
            continue
        if not school:
            judgment.reason = "未从候选人材料中提取到可核验的本科院校"
            continue
        match = catalog.resolve(school)
        quotes = [evidence.quote for evidence in judgment.evidence]
        if match.status != "matched":
            formal_name = bool(re.search(r"(?:大学|学院)(?:[（(].*校区?[）)])?$", school))
            if (
                match.status == "not_found"
                and formal_name
                and catalog.query_evidence_supports(school, quotes)
            ):
                categories, require_all = requested
                labels = {"985": "985", "211": "211", "double_first_class": "双一流"}
                requirement = ("且" if require_all else "或").join(
                    labels[item] for item in categories
                )
                judgment.conclusion = Conclusion.NO_MATCH
                judgment.confidence = 0.99
                judgment.needs_external_fact = False
                judgment.reason = (
                    f"本科院校“{school}”未列入{requirement}官方名单；"
                    f"依据内置教育部目录 {catalog.payload.catalog_version}"
                )
                resolved += 1
                continue
            judgment.reason = f"本科院校“{school}”未能与内置官方目录精确匹配"
            continue
        evidence_supported = catalog.evidence_supports(
            match.standard_name, quotes
        ) or catalog.query_evidence_supports(school, quotes)
        if not evidence_supported:
            judgment.reason = "提取出的本科院校缺少可回溯的简历原文证据"
            continue
        categories, require_all = requested
        present = set(match.categories)
        satisfied = (
            all(category in present for category in categories)
            if require_all
            else any(category in present for category in categories)
        )
        labels = {"985": "985", "211": "211", "double_first_class": "双一流"}
        requirement = ("且" if require_all else "或").join(labels[item] for item in categories)
        judgment.conclusion = Conclusion.MATCH if satisfied else Conclusion.NO_MATCH
        judgment.confidence = 0.99
        judgment.needs_external_fact = False
        verb = "符合" if satisfied else "不符合"
        judgment.reason = (
            f"本科院校“{match.standard_name}”{verb}{requirement}条件；"
            f"依据内置教育部目录 {match.catalog_version}"
        )
        resolved += 1
    if resolved:
        _refresh_score_and_recommendation(result, criteria)
        result.overall_reason = "；".join(
            value
            for value in (
                result.overall_reason,
                f"已用内置官方院校目录核验 {resolved} 项条件",
            )
            if value
        )
    return resolved
