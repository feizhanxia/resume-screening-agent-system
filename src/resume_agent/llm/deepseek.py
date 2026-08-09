from __future__ import annotations

import asyncio
import json
import random
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from resume_agent.domain.models import (
    AnalysisResult,
    CandidateFacts,
    CandidatePackage,
    Conclusion,
    Criterion,
    ExtractionResult,
    Judgment,
    RunConfig,
)
from resume_agent.llm.privacy import redact_pii


class CriteriaPayload(BaseModel):
    criteria: list[Criterion]


class ModelAnalysisPayload(BaseModel):
    facts: CandidateFacts = Field(default_factory=CandidateFacts)
    judgments: list[Judgment]
    recommendation: str = "review"
    overall_reason: str = ""


SYSTEM_CRITERIA = """你是招聘条件结构化助手。只拆解用户给定的JD，不添加JD没有的条件。
输出一个JSON对象，唯一顶层字段为criteria。每个条件包含criterion_id、name、definition、kind、
weight、enabled、requires_external_fact、version。kind只能是required、scored、bonus。
硬性门槛与评分偏好必须分开；涉及学校排名、985/211/双一流、论文级别等需外部名单核验的条件，
requires_external_fact=true。criterion_id使用稳定的英文点分标识。最多30项。"""


SYSTEM_ANALYZE = """你是谨慎的简历证据分析助手。只可使用给出的候选人材料，不使用常识补全事实，
也不依据性别、年龄、民族、婚育、照片或健康状况评分。对每个启用条件必须返回且只返回一个判断。
conclusion只能是match、no_match、uncertain。证据必须引用输入中的file_id、relative_path、locator_kind、
locator_value并给出短原文；没有直接证据时必须uncertain且evidence为空。涉及外部名单或排名且本地未提供
可信事实时，needs_external_fact=true且结论为uncertain。输出JSON对象，不要Markdown。"""


class DeepSeekClient:
    def __init__(self, api_key: str, config: RunConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.api_base,
            timeout=config.timeout_seconds,
            max_retries=0,
        )
        self.semaphore = asyncio.Semaphore(config.analysis_concurrency)

    async def _json_chat(self, *, model: str, system: str, user: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.config.max_retries_per_resume + 1):
            try:
                async with self.semaphore:
                    response = await self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        response_format={"type": "json_object"},
                        temperature=0,
                        max_tokens=8000,
                    )
                content = response.choices[0].message.content or ""
                return json.loads(content)
            except Exception as exc:
                last_error = exc
                if attempt >= self.config.max_retries_per_resume:
                    break
                await asyncio.sleep(min(8, 1.2 * (2**attempt)) + random.random())
        raise RuntimeError(f"模型调用失败：{type(last_error).__name__}") from last_error

    async def compile_criteria(self, jd: str, requirements: str) -> list[Criterion]:
        payload = await self._json_chat(
            model=self.config.model,
            system=SYSTEM_CRITERIA,
            user=json.dumps({"jd": jd, "requirements": requirements}, ensure_ascii=False),
        )
        criteria = CriteriaPayload.model_validate(payload).criteria
        if not criteria:
            raise ValueError("模型未生成筛选条件")
        return criteria

    @staticmethod
    def _build_documents(
        package: CandidatePackage,
        extractions: dict[str, ExtractionResult],
        redact: bool,
        max_chars: int = 180_000,
    ) -> list[dict[str, Any]]:
        documents: list[dict[str, Any]] = []
        used = 0
        for file in package.files:
            result = extractions.get(file.file_id)
            if not result:
                continue
            units = []
            for unit in result.units:
                text = redact_pii(unit.text) if redact else unit.text
                remaining = max_chars - used
                if remaining <= 0:
                    break
                text = text[:remaining]
                used += len(text)
                units.append(
                    {
                        "locator_kind": unit.locator_kind,
                        "locator_value": unit.locator_value,
                        "text": text,
                    }
                )
            documents.append(
                {
                    "file_id": file.file_id,
                    "relative_path": file.relative_path,
                    "material_role": file.material_role,
                    "extraction_status": result.status,
                    "units": units,
                }
            )
        return documents

    async def analyze(
        self,
        package: CandidatePackage,
        extractions: dict[str, ExtractionResult],
        criteria: list[Criterion],
    ) -> AnalysisResult:
        active = [item for item in criteria if item.enabled]
        request = {
            "candidate_id": package.candidate_id,
            "criteria": [item.model_dump(mode="json") for item in active],
            "documents": self._build_documents(package, extractions, self.config.redact_pii),
            "output_schema": {
                "facts": {
                    "name": "string|null",
                    "highest_degree": "string|null",
                    "undergraduate_school": "string|null",
                    "current_or_last_company": "string|null",
                    "work_years": "number|null",
                    "skills": ["string"],
                    "summary": "string",
                },
                "judgments": [
                    {
                        "criterion_id": "string",
                        "conclusion": "match|no_match|uncertain",
                        "confidence": "0..1",
                        "reason": "string",
                        "evidence": [
                            {
                                "file_id": "string",
                                "relative_path": "string",
                                "locator_kind": "string",
                                "locator_value": "string",
                                "quote": "string",
                            }
                        ],
                        "needs_external_fact": "boolean",
                    }
                ],
                "recommendation": "recommended|possible|not_recommended|review",
                "overall_reason": "string",
            },
        }
        payload = await self._json_chat(
            model=self.config.model,
            system=SYSTEM_ANALYZE,
            user=json.dumps(request, ensure_ascii=False),
        )
        parsed = ModelAnalysisPayload.model_validate(payload)
        valid_file_ids = {item.file_id for item in package.files}
        by_id = {item.criterion_id: item for item in parsed.judgments}
        judgments: list[Judgment] = []
        for criterion in active:
            judgment = by_id.get(criterion.criterion_id)
            if not judgment:
                judgment = Judgment(
                    criterion_id=criterion.criterion_id,
                    conclusion=Conclusion.UNCERTAIN,
                    confidence=0,
                    reason="模型输出缺少该条件判断",
                )
            judgment.evidence = [
                evidence for evidence in judgment.evidence if evidence.file_id in valid_file_ids
            ]
            if judgment.conclusion == Conclusion.MATCH and not judgment.evidence:
                judgment.conclusion = Conclusion.UNCERTAIN
                judgment.reason += "；缺少有效来源证据"
            judgments.append(judgment)
        result = AnalysisResult(
            candidate_id=package.candidate_id,
            facts=parsed.facts,
            judgments=judgments,
            recommendation=(
                parsed.recommendation
                if parsed.recommendation in {"recommended", "possible", "not_recommended", "review"}
                else "review"
            ),
            overall_reason=parsed.overall_reason,
            model=self.config.model,
        )
        result.score = calculate_score(result.judgments, active)
        return result


def calculate_score(judgments: list[Judgment], criteria: list[Criterion]) -> float:
    by_id = {item.criterion_id: item for item in judgments}
    total = sum(item.weight for item in criteria if item.enabled) or 1
    earned = 0.0
    for criterion in criteria:
        if not criterion.enabled:
            continue
        judgment = by_id.get(criterion.criterion_id)
        if not judgment:
            continue
        multiplier = {
            Conclusion.MATCH: 1.0,
            Conclusion.UNCERTAIN: 0.35,
            Conclusion.NO_MATCH: 0.0,
        }[judgment.conclusion]
        earned += criterion.weight * multiplier
    return round(earned / total * 100, 1)


def offline_review_result(
    package: CandidatePackage,
    criteria: list[Criterion],
    reason: str = "未配置 API Key，尚未执行语义分析",
) -> AnalysisResult:
    return AnalysisResult(
        candidate_id=package.candidate_id,
        facts=CandidateFacts(name=package.display_name, summary=reason),
        judgments=[
            Judgment(
                criterion_id=item.criterion_id,
                conclusion=Conclusion.UNCERTAIN,
                confidence=0,
                reason=reason,
            )
            for item in criteria
            if item.enabled
        ],
        recommendation="review",
        overall_reason=reason,
        score=35,
        model="offline",
    )
