from __future__ import annotations

from pydantic import BaseModel, Field

from resume_agent.domain.models import AnalysisResult, Criterion, ScanResult
from resume_agent.storage.database import Database


class AuditReport(BaseModel):
    passed: bool
    candidate_count: int
    file_count: int
    analysis_count: int
    findings: list[str] = Field(default_factory=list)


def audit_run(
    scan: ScanResult,
    criteria: list[Criterion],
    analyses: list[AnalysisResult],
    database: Database | None = None,
) -> AuditReport:
    findings: list[str] = []
    expected_candidates = {item.candidate_id for item in scan.candidates}
    result_candidates = {item.candidate_id for item in analyses}
    missing_candidates = expected_candidates - result_candidates
    extra_candidates = result_candidates - expected_candidates
    if missing_candidates:
        findings.append(f"有 {len(missing_candidates)} 个候选人没有分析终态")
    if extra_candidates:
        findings.append(f"结果中有 {len(extra_candidates)} 个不在当前目录的候选人")
    enabled = {item.criterion_id for item in criteria if item.enabled}
    for result in analyses:
        judged = {item.criterion_id for item in result.judgments}
        if judged != enabled:
            findings.append(f"{result.candidate_id} 的条件覆盖不完整")
    offline_count = sum(result.model == "offline" for result in analyses)
    if offline_count:
        findings.append(f"有 {offline_count} 个候选人尚未执行模型语义分析")
    if scan.unassigned_files:
        findings.append(f"根目录有 {len(scan.unassigned_files)} 个未归属文件")
    if scan.errors:
        findings.append(f"扫描期间有 {len(scan.errors)} 个文件错误")
    if database:
        expected_files = {file.file_id for candidate in scan.candidates for file in candidate.files}
        database_files: dict[str, dict] = {}
        for candidate in scan.candidates:
            for row in database.files_for_candidate(candidate.candidate_id):
                database_files[row["file_id"]] = row
        if expected_files != set(database_files):
            findings.append("当前目录文件ID集合与数据库活动文件集合不一致")
        pending = [row for row in database_files.values() if row["extraction_status"] == "pending"]
        problematic = [
            row
            for row in database_files.values()
            if row["extraction_status"] in {"failed", "encrypted", "empty"}
        ]
        if pending:
            findings.append(f"有 {len(pending)} 个文件没有提取终态")
        if problematic:
            findings.append(f"有 {len(problematic)} 个文件需要人工复核")
    return AuditReport(
        passed=not findings,
        candidate_count=len(scan.candidates),
        file_count=scan.file_count,
        analysis_count=len(analyses),
        findings=findings,
    )
