from __future__ import annotations

import hashlib
import mimetypes
import os
import uuid
from pathlib import Path

from resume_agent.domain.models import CandidatePackage, MaterialFile, ScanResult

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def classify_role(path: Path) -> str:
    name = path.name.lower()
    if any(word in name for word in ("简历", "resume", "cv")):
        return "primary_resume"
    if any(word in name for word in ("证书", "certificate", "证明", "获奖")):
        return "certificate"
    if any(word in name for word in ("作品", "portfolio", "案例")):
        return "portfolio"
    if any(word in name for word in ("论文", "publication", "paper", "专利")):
        return "publication"
    if path.suffix.lower() in SUPPORTED_SUFFIXES:
        return "supplementary"
    return "other"


def detect_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    custom = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }
    return custom.get(suffix) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _candidate_id(root: Path, relative_dir: str) -> str:
    value = f"{root.resolve()}::{relative_dir}"
    return "cand_" + uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:20]


def scan_resume_root(root: Path) -> ScanResult:
    root = root.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"简历目录不存在或不是目录：{root}")

    candidates: list[CandidatePackage] = []
    unassigned: list[Path] = []
    errors: list[str] = []

    for entry in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
        if entry.name in IGNORED_NAMES or entry.name.startswith("."):
            continue
        if entry.is_file():
            unassigned.append(entry)
            continue
        if not entry.is_dir():
            continue

        relative_dir = entry.relative_to(root).as_posix()
        candidate_id = _candidate_id(root, relative_dir)
        files: list[MaterialFile] = []
        for path in sorted(entry.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not path.is_file() or path.name in IGNORED_NAMES or path.name.startswith("~$"):
                continue
            relative_path = path.relative_to(entry).as_posix()
            try:
                stat = path.stat()
                content_hash = sha256_file(path)
                files.append(
                    MaterialFile(
                        file_id="file_" + content_hash[:24],
                        candidate_id=candidate_id,
                        absolute_path=path,
                        relative_path=relative_path,
                        media_type=detect_media_type(path),
                        material_role=classify_role(path),
                        content_hash=content_hash,
                        size=stat.st_size,
                        mtime_ns=stat.st_mtime_ns,
                    )
                )
            except (OSError, PermissionError) as exc:
                errors.append(f"{path}: {exc}")

        package_digest = hashlib.sha256()
        for item in files:
            package_digest.update(item.relative_path.encode("utf-8", errors="replace"))
            package_digest.update(b"\0")
            package_digest.update(item.content_hash.encode("ascii"))
            package_digest.update(b"\0")
        candidates.append(
            CandidatePackage(
                candidate_id=candidate_id,
                display_name=entry.name,
                root_path=entry,
                relative_dir=relative_dir,
                package_hash=package_digest.hexdigest(),
                files=files,
            )
        )

    return ScanResult(
        root_path=root,
        candidates=candidates,
        unassigned_files=unassigned,
        errors=errors,
    )


def default_output_dir(resume_root: Path) -> Path:
    return resume_root.resolve().parent / f"{resume_root.name}_筛选输出"


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((path.resolve(), parent.resolve())) == str(parent.resolve())
    except ValueError:
        return False
