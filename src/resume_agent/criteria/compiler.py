from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel

from resume_agent.domain.models import Criterion, CriterionKind

PROMPT_VERSION = "criteria-2-fast"
CRITERIA_CACHE_LIMIT = 24


class CriteriaCompilation(BaseModel):
    criteria: list[Criterion]
    source: Literal["model", "local_draft"]
    warning: str = ""


def _slug(value: str, index: int) -> str:
    digest = hashlib.sha1(value.encode("utf-8"), usedforsecurity=False).hexdigest()[:10]
    return f"criterion.{index:02d}.{digest}"


def _kind_for(text: str) -> CriterionKind:
    if any(word in text for word in ("必须", "要求", "以上", "精通", "本科", "硕士", "博士")):
        return CriterionKind.REQUIRED
    if any(word in text for word in ("加分", "优先", "更佳", "竞赛", "论文")):
        return CriterionKind.BONUS
    return CriterionKind.SCORED


def heuristic_compile(jd: str, requirements: str = "") -> list[Criterion]:
    raw = f"{jd}\n{requirements}"
    lines = []
    for line in raw.splitlines():
        clean = re.sub(r"^[\s●•·\-*\d.、（）()]+", "", line).strip()
        clean = re.sub(r"^(岗位职责|任职要求|专业技能|加分项)[:：]?\s*", "", clean)
        if len(clean) >= 4:
            lines.append(clean)
    if not lines and raw.strip():
        lines = [
            segment.strip() for segment in re.split(r"[。；;]", raw) if len(segment.strip()) >= 4
        ]

    unique: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = re.sub(r"\s+", "", line)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(line[:240])
    criteria = []
    for index, line in enumerate(unique[:30], 1):
        kind = _kind_for(line)
        name = re.split(r"[：:，,。；;]", line, maxsplit=1)[0][:32]
        if len(name) < 3:
            name = line[:32]
        criteria.append(
            Criterion(
                criterion_id=_slug(line, index),
                name=name,
                definition=line,
                kind=kind,
                weight=15
                if kind == CriterionKind.REQUIRED
                else (8 if kind == CriterionKind.BONUS else 10),
                requires_external_fact=any(
                    word in line.lower()
                    for word in ("前20", "top 20", "985", "211", "双一流", "排名", "顶级期刊")
                ),
            )
        )
    return criteria


def criteria_fingerprint(criteria: list[Criterion]) -> str:
    canonical = [
        item.model_dump(mode="json")
        for item in sorted(criteria, key=lambda value: value.criterion_id)
        if item.enabled
    ]
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def jd_cache_fingerprint(jd: str, requirements: str, model: str) -> str:
    """Identify a successful JD compilation without persisting the original JD."""
    payload = {
        "jd": jd.replace("\r\n", "\n").replace("\r", "\n").strip(),
        "requirements": requirements.replace("\r\n", "\n").replace("\r", "\n").strip(),
        "model": model.strip(),
        "prompt_version": PROMPT_VERSION,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def encode_criteria_cache(criteria: list[Criterion]) -> str:
    payload = [item.model_dump(mode="json") for item in criteria]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_criteria_cache(raw: str) -> list[Criterion]:
    payload = json.loads(raw)
    if not isinstance(payload, list) or not payload or len(payload) > CRITERIA_CACHE_LIMIT:
        raise ValueError("条件缓存结构无效")
    return [Criterion.model_validate(item) for item in payload]


async def compile_criteria(
    jd: str,
    requirements: str = "",
    llm_client: Any | None = None,
) -> list[Criterion]:
    if not jd.strip() and not requirements.strip():
        raise ValueError("JD 和筛选要求不能同时为空")
    if llm_client is None:
        return heuristic_compile(jd, requirements)
    return await llm_client.compile_criteria(jd, requirements)


async def compile_criteria_fast(
    jd: str,
    requirements: str,
    llm_client: Any | None,
    *,
    timeout_seconds: float,
    on_attempt: Callable[[int, int], None] | None = None,
) -> CriteriaCompilation:
    if not jd.strip() and not requirements.strip():
        raise ValueError("JD 和筛选要求不能同时为空")
    if llm_client is None:
        return CriteriaCompilation(
            criteria=heuristic_compile(jd, requirements),
            source="local_draft",
            warning="未配置 API Key",
        )
    try:
        criteria = await asyncio.wait_for(
            llm_client.compile_criteria(jd, requirements, on_attempt=on_attempt),
            timeout=timeout_seconds,
        )
        return CriteriaCompilation(criteria=criteria, source="model")
    except Exception as exc:
        return CriteriaCompilation(
            criteria=heuristic_compile(jd, requirements),
            source="local_draft",
            warning=type(exc).__name__,
        )
