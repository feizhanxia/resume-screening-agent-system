from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from resume_agent.audit.coverage import audit_run
from resume_agent.config import WorkspacePaths, default_config, load_api_key
from resume_agent.criteria.compiler import compile_criteria
from resume_agent.llm.deepseek import DeepSeekClient
from resume_agent.reporting.excel import export_excel
from resume_agent.scanning.scanner import scan_resume_root
from resume_agent.storage.database import Database
from resume_agent.workers.engine import ScreeningEngine


async def _run(args) -> int:
    resume_root = Path(args.resume_root)
    output_root = Path(args.output_root)
    workspace = WorkspacePaths.create(output_root)
    database = Database(workspace.database)
    scan = scan_resume_root(resume_root)
    config = default_config()
    api_key = load_api_key()
    if api_key and not args.allow_cloud:
        raise SystemExit(
            "检测到 DeepSeek API Key。CLI 云端分析必须显式添加 --allow-cloud；"
            "PDF/DOCX 原文件不会上传，但脱敏后的提取文本会发送至配置的 API。"
        )
    llm = DeepSeekClient(api_key, config) if api_key else None
    criteria = await compile_criteria(args.jd, args.requirements, llm)
    print(
        json.dumps(
            [item.model_dump(mode="json") for item in criteria], ensure_ascii=False, indent=2
        )
    )
    engine = ScreeningEngine(
        database,
        config,
        api_key,
        progress=lambda event: print(f"[{event.event}] {event.message}"),
    )
    run_id, analyses = await engine.run(scan, criteria, args.jd, args.requirements, output_root)
    audit = audit_run(scan, criteria, analyses, database)
    output = export_excel(
        workspace.outputs / f"简历分析_{run_id}.xlsx",
        run_id,
        scan,
        criteria,
        analyses,
        audit,
    )
    print(f"结果：{output}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="本地优先简历筛选智能体")
    parser.add_argument("resume_root")
    parser.add_argument("output_root")
    parser.add_argument("--jd", required=True)
    parser.add_argument("--requirements", default="")
    parser.add_argument(
        "--allow-cloud",
        action="store_true",
        help="明确同意把脱敏后的简历文本发送至配置的 DeepSeek API",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
