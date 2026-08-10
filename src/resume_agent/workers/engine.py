from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable

from resume_agent.criteria.compiler import criteria_fingerprint
from resume_agent.domain.models import (
    AnalysisResult,
    CandidatePackage,
    CandidateState,
    Criterion,
    ExtractionStatus,
    ProgressEvent,
    RunConfig,
    ScanResult,
)
from resume_agent.extraction.service import ExtractionService
from resume_agent.facts.universities import (
    UniversityCatalog,
    apply_university_resolutions,
)
from resume_agent.llm.deepseek import (
    DeepSeekClient,
    ModelCallError,
    offline_review_result,
    safe_error_message,
    safe_error_payload,
)
from resume_agent.storage.database import Database

ProgressCallback = Callable[[ProgressEvent], None]


def effective_worker_count(configured: int, candidate_count: int) -> int:
    return max(0, min(configured, candidate_count))


class ScreeningEngine:
    def __init__(
        self,
        database: Database,
        config: RunConfig,
        api_key: str | None = None,
        progress: ProgressCallback | None = None,
    ):
        self.database = database
        self.config = config
        self.progress = progress or (lambda event: None)
        self.llm = DeepSeekClient(api_key, config) if api_key else None
        self.extractions = ExtractionService(database, config.extraction_concurrency)
        try:
            self.university_catalog = UniversityCatalog.load_default()
        except (OSError, TypeError, ValueError):
            self.university_catalog = None
        self.pause_event = asyncio.Event()
        self.pause_event.set()
        self.cancel_event = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._completed = 0
        self._degraded = 0
        self._failed = 0

    def pause(self) -> None:
        self.pause_event.clear()

    def resume(self) -> None:
        self.pause_event.set()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.pause_event.set()

    def _emit(self, **kwargs) -> None:
        self.progress(ProgressEvent(**kwargs))

    async def run(
        self,
        scan: ScanResult,
        criteria: list[Criterion],
        jd: str,
        requirements: str,
        output_root,
    ) -> tuple[str, list[AnalysisResult]]:
        run_id = "run_" + uuid.uuid4().hex[:16]
        fingerprint = criteria_fingerprint(criteria)
        self.database.save_scan(scan.candidates)
        self.database.create_run(
            run_id,
            scan.root_path,
            output_root,
            jd,
            requirements,
            fingerprint,
            self.config.model_dump_json(),
        )
        self.database.save_criteria(run_id, criteria)
        queue: asyncio.Queue[CandidatePackage | None] = asyncio.Queue(maxsize=50)
        worker_count = effective_worker_count(self.config.worker_count, len(scan.candidates))
        self._completed = 0
        self._degraded = 0
        self._failed = 0
        self._emit(
            event="run_started",
            message=f"任务已启动，实际使用 {worker_count} 个 Worker",
            total=len(scan.candidates),
            payload={"worker_count": worker_count},
        )
        workers = [
            asyncio.create_task(
                self._worker(index + 1, queue, run_id, fingerprint, criteria, len(scan.candidates))
            )
            for index in range(worker_count)
        ]
        for package in scan.candidates:
            await queue.put(package)
        for _ in range(worker_count):
            await queue.put(None)
        await asyncio.gather(*workers)
        results = self.database.analyses_for_run(run_id)
        if self.cancel_event.is_set():
            status = "cancelled"
            message = "任务已取消"
        elif self._degraded or self._failed or len(results) != len(scan.candidates):
            status = "completed_with_errors"
            message = f"部分完成：{len(results)}/{len(scan.candidates)} 名候选人已有结果"
        else:
            status = "completed"
            message = "全部候选人处理完成"
        self.database.finish_run(run_id, status)
        self._emit(
            event="run_finished",
            message=message,
            completed=len(results),
            total=len(scan.candidates),
            payload={
                "status": status,
                "degraded": self._degraded,
                "failed": self._failed,
            },
        )
        return run_id, results

    async def _worker(
        self,
        worker_no: int,
        queue: asyncio.Queue[CandidatePackage | None],
        run_id: str,
        criteria_hash: str,
        criteria: list[Criterion],
        total: int,
    ) -> None:
        while True:
            package = await queue.get()
            if package is None:
                queue.task_done()
                return
            if self.cancel_event.is_set():
                queue.task_done()
                continue
            await self.pause_event.wait()
            self._emit(
                event="candidate_started",
                candidate_id=package.candidate_id,
                message=f"Worker {worker_no} 正在处理 {package.display_name}",
                completed=self._completed,
                total=total,
                worker=worker_no,
            )
            try:
                degraded = await self._run_candidate(package, run_id, criteria_hash, criteria)
                if degraded:
                    self._degraded += 1
            except Exception as exc:
                self._failed += 1
                self.database.set_candidate_state(package.candidate_id, CandidateState.FAILED)
                diagnostic = safe_error_payload(exc)
                self.database.record_event(
                    "candidate_failed",
                    {**diagnostic, "message": safe_error_message(exc)},
                    run_id,
                    package.candidate_id,
                )
                self._emit(
                    event="candidate_failed",
                    candidate_id=package.candidate_id,
                    message=f"{package.display_name}：{safe_error_message(exc)}",
                    completed=self._completed,
                    total=total,
                    worker=worker_no,
                )
            finally:
                self._completed += 1
                self._emit(
                    event="progress",
                    candidate_id=package.candidate_id,
                    message=f"已处理 {self._completed}/{total}",
                    completed=self._completed,
                    total=total,
                    worker=worker_no,
                )
                queue.task_done()

    async def _run_candidate(
        self,
        package: CandidatePackage,
        run_id: str,
        criteria_hash: str,
        criteria: list[Criterion],
    ) -> bool:
        if self.cancel_event.is_set():
            return False
        model_name = self.llm.cache_model if self.llm else "offline"
        cached = self.database.find_cached_analysis(package.package_hash, criteria_hash, model_name)
        if cached:
            cached.candidate_id = package.candidate_id
            if self.university_catalog:
                apply_university_resolutions(cached, criteria, self.university_catalog)
            degraded = cached.prompt_version.endswith("degraded")
            needs_review = degraded or any(
                judgment.needs_external_fact for judgment in cached.judgments
            )
            async with self._write_lock:
                self.database.save_analysis(run_id, package.package_hash, criteria_hash, cached)
            self.database.set_candidate_state(
                package.candidate_id,
                CandidateState.NEEDS_REVIEW if needs_review else CandidateState.COMPLETED,
            )
            return degraded

        self.database.set_candidate_state(package.candidate_id, CandidateState.EXTRACTING)
        unique_files = DeepSeekClient._unique_files(package)
        extraction_results = await asyncio.gather(
            *(self.extractions.extract(file) for file in unique_files)
        )
        extractions = {item.file_id: item for item in extraction_results}
        self.database.set_candidate_state(package.candidate_id, CandidateState.NORMALIZING)
        has_text = any(item.text.strip() for item in extraction_results)
        problematic = [
            item
            for item in extraction_results
            if item.status
            in {ExtractionStatus.FAILED, ExtractionStatus.ENCRYPTED, ExtractionStatus.EMPTY}
        ]
        degraded = False
        routing_reason = ""
        if self.llm and has_text:
            try:
                routing = await self.llm.classify_materials(package, extractions)
                self.database.update_material_roles(package.candidate_id, routing.roles)
                degraded = routing.needs_review
                routing_reason = routing.reason
                if routing.needs_review:
                    self.database.record_event(
                        "material_routing_review",
                        {"message": routing.reason},
                        run_id,
                        package.candidate_id,
                    )
            except Exception as exc:
                degraded = True
                diagnostic = safe_error_payload(exc)
                routing_reason = "材料预分类失败，已使用本地文件名规则"
                self.database.record_event(
                    "material_routing_degraded",
                    {**diagnostic, "message": safe_error_message(exc)},
                    run_id,
                    package.candidate_id,
                )
        self.database.set_candidate_state(package.candidate_id, CandidateState.READY_FOR_ANALYSIS)
        if self.llm and has_text:
            self.database.set_candidate_state(package.candidate_id, CandidateState.ANALYZING)
            try:
                result = await self.llm.analyze(package, extractions, criteria)
            except Exception as exc:
                degraded = True
                diagnostic = safe_error_payload(exc)
                self.database.record_event(
                    "candidate_degraded",
                    {**diagnostic, "message": safe_error_message(exc)},
                    run_id,
                    package.candidate_id,
                )
                public_reason = (
                    str(exc)
                    if isinstance(exc, ModelCallError)
                    else f"模型结构化结果无效：{type(exc).__name__}"
                )
                result = offline_review_result(
                    package,
                    criteria,
                    f"{public_reason}；已保留候选人并标记人工复核",
                    model=f"{self.llm.cache_model}:degraded",
                    prompt_version="routing-v1-degraded",
                )
        else:
            reason = (
                "候选人材料没有可分析文本，需要人工复核"
                if not has_text
                else "未配置 API Key，已完成提取但语义判断待处理"
            )
            result = offline_review_result(package, criteria, reason)
            degraded = True
        if routing_reason:
            result.overall_reason = "；".join(
                value for value in (result.overall_reason, routing_reason) if value
            )
        if self.university_catalog:
            apply_university_resolutions(result, criteria, self.university_catalog)
        self.database.set_candidate_state(package.candidate_id, CandidateState.VERIFYING)
        missing = {item.criterion_id for item in criteria if item.enabled} - {
            item.criterion_id for item in result.judgments
        }
        if missing:
            raise ValueError(f"分析结果缺少 {len(missing)} 个条件")
        needs_review = (
            bool(problematic)
            or any(judgment.needs_external_fact for judgment in result.judgments)
            or degraded
            or result.model == "offline"
        )
        async with self._write_lock:
            self.database.save_analysis(run_id, package.package_hash, criteria_hash, result)
        self.database.set_candidate_state(
            package.candidate_id,
            CandidateState.NEEDS_REVIEW if needs_review else CandidateState.COMPLETED,
        )
        return degraded or bool(problematic) or result.model == "offline"
