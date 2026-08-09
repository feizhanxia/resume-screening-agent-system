from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

from openpyxl import Workbook

from resume_agent.domain.models import CandidatePackage
from resume_agent.safety import excel_safe_value
from resume_agent.scanning.scanner import ensure_safe_member_path, sha256_file


def safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned[:80] or "未命名候选人"


def safe_relative_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(value)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(f"材料路径必须是相对路径：{value}")
    if not posix.parts or any(part in {"", ".", ".."} for part in posix.parts):
        raise ValueError(f"材料路径包含不安全片段：{value}")
    return Path(*posix.parts)


def copy_candidate_packages(
    packages: list[CandidatePackage],
    candidate_ids: set[str],
    output_root: Path,
    run_name: str,
    category: str = "入选",
) -> Path:
    selected = [item for item in packages if item.candidate_id in candidate_ids]
    destination_root = (
        output_root.resolve() / "候选人材料" / safe_name(run_name) / safe_name(category)
    )
    destination_root.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    for rank, package in enumerate(selected, 1):
        folder = destination_root / (
            f"{rank:03d}_{safe_name(package.display_name)}_{package.candidate_id.removeprefix('cand_')[:8]}"
        )
        for file in package.files:
            source = ensure_safe_member_path(file.absolute_path, package.root_path)
            relative = safe_relative_path(file.relative_path)
            target = folder / relative
            if target.parent.resolve().is_relative_to(folder.resolve()) is False:
                raise ValueError(f"材料目标路径越界：{file.relative_path}")
            target.parent.mkdir(parents=True, exist_ok=True)
            status = "copied"
            if target.exists() and sha256_file(target) == file.content_hash:
                status = "skipped_same_hash"
            else:
                shutil.copy2(source, target)
            target_hash = sha256_file(target)
            if target_hash != file.content_hash:
                target.unlink(missing_ok=True)
                raise OSError(f"复制校验失败：{file.relative_path}")
            manifest_rows.append(
                [
                    package.candidate_id,
                    package.display_name,
                    str(source),
                    str(target),
                    file.content_hash,
                    status,
                    datetime.now().isoformat(timespec="seconds"),
                ]
            )
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "材料复制清单"
    sheet.append(["候选人ID", "候选人", "来源", "目标", "SHA-256", "状态", "时间"])
    for row in manifest_rows:
        sheet.append([excel_safe_value(value) for value in row])
    manifest_path = destination_root.parent / "manifest.xlsx"
    workbook.save(manifest_path)
    return manifest_path
