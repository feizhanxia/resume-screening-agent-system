from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from resume_agent.domain.models import RunConfig

APP_NAME = "简历筛选工作台"
KEYRING_SERVICE = "resume-screening-agent"
KEYRING_USER = "deepseek-api-key"


class WorkspacePaths(BaseModel):
    root: Path
    database: Path
    cache: Path
    outputs: Path
    logs: Path

    @classmethod
    def create(cls, output_root: Path) -> WorkspacePaths:
        root = output_root.resolve() / ".resume-agent"
        paths = cls(
            root=root,
            database=root / "resume-agent.db",
            cache=root / "cache",
            outputs=output_root.resolve() / "简历筛选结果",
            logs=root / "logs",
        )
        for directory in (paths.root, paths.cache, paths.outputs, paths.logs):
            directory.mkdir(parents=True, exist_ok=True)
        return paths


def load_api_key() -> str | None:
    value = os.getenv("DEEPSEEK_API_KEY")
    if value:
        return value.strip()
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def save_api_key(value: str) -> None:
    value = value.strip()
    if not value:
        raise ValueError("API Key 不能为空")
    if not value.startswith("sk-"):
        raise ValueError("API Key 格式不正确")
    import keyring

    keyring.set_password(KEYRING_SERVICE, KEYRING_USER, value)


def default_config() -> RunConfig:
    return RunConfig(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        audit_model=os.getenv("DEEPSEEK_AUDIT_MODEL", "deepseek-v4-pro"),
        api_base=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
