from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from resume_agent.domain.models import (
    AnalysisResult,
    CandidatePackage,
    CandidateState,
    Criterion,
    ExtractionResult,
)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS candidates (
  candidate_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  root_path TEXT NOT NULL,
  relative_dir TEXT NOT NULL,
  package_hash TEXT NOT NULL,
  state TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  file_id TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  media_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime_ns INTEGER NOT NULL,
  extraction_status TEXT NOT NULL,
  extractor_version TEXT,
  extraction_json TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS candidate_files (
  candidate_id TEXT NOT NULL,
  file_id TEXT NOT NULL,
  absolute_path TEXT NOT NULL,
  relative_path TEXT NOT NULL,
  material_role TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY(candidate_id, file_id),
  FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id),
  FOREIGN KEY(file_id) REFERENCES files(file_id)
);
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY,
  resume_root TEXT NOT NULL,
  output_root TEXT NOT NULL,
  jd TEXT NOT NULL,
  requirements TEXT NOT NULL,
  criteria_hash TEXT NOT NULL,
  config_json TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS criteria (
  run_id TEXT NOT NULL,
  criterion_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  criterion_json TEXT NOT NULL,
  PRIMARY KEY(run_id, criterion_id, version),
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
CREATE TABLE IF NOT EXISTS analyses (
  run_id TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  package_hash TEXT NOT NULL,
  criteria_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  result_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(run_id, candidate_id),
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id)
);
CREATE TABLE IF NOT EXISTS manual_fields (
  candidate_id TEXT PRIMARY KEY,
  hr_status TEXT NOT NULL DEFAULT '',
  owner TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  candidate_id TEXT,
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_candidate_files_candidate ON candidate_files(candidate_id, active);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        with self.connection() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_scan(self, packages: list[CandidatePackage]) -> None:
        now = utc_now()
        current_ids = {item.candidate_id for item in packages}
        with self.connection() as conn:
            conn.execute("UPDATE candidates SET active=0, updated_at=?", (now,))
            conn.execute("UPDATE candidate_files SET active=0")
            for package in packages:
                conn.execute(
                    """INSERT INTO candidates(candidate_id,display_name,root_path,relative_dir,
                       package_hash,state,active,updated_at) VALUES(?,?,?,?,?,?,1,?)
                       ON CONFLICT(candidate_id) DO UPDATE SET display_name=excluded.display_name,
                       root_path=excluded.root_path,relative_dir=excluded.relative_dir,
                       package_hash=excluded.package_hash,active=1,updated_at=excluded.updated_at""",
                    (
                        package.candidate_id,
                        package.display_name,
                        str(package.root_path),
                        package.relative_dir,
                        package.package_hash,
                        CandidateState.DISCOVERED,
                        now,
                    ),
                )
                for file in package.files:
                    conn.execute(
                        """INSERT INTO files(file_id,content_hash,media_type,size,mtime_ns,
                           extraction_status,updated_at) VALUES(?,?,?,?,?,?,?)
                           ON CONFLICT(file_id) DO UPDATE SET size=excluded.size,
                           mtime_ns=excluded.mtime_ns,updated_at=excluded.updated_at""",
                        (
                            file.file_id,
                            file.content_hash,
                            file.media_type,
                            file.size,
                            file.mtime_ns,
                            file.extraction_status,
                            now,
                        ),
                    )
                    conn.execute(
                        """INSERT INTO candidate_files(candidate_id,file_id,absolute_path,
                           relative_path,material_role,active) VALUES(?,?,?,?,?,1)
                           ON CONFLICT(candidate_id,file_id) DO UPDATE SET
                           absolute_path=excluded.absolute_path,relative_path=excluded.relative_path,
                           material_role=excluded.material_role,active=1""",
                        (
                            package.candidate_id,
                            file.file_id,
                            str(file.absolute_path),
                            file.relative_path,
                            file.material_role,
                        ),
                    )
            if current_ids:
                placeholders = ",".join("?" for _ in current_ids)
                conn.execute(
                    f"UPDATE candidates SET active=0 WHERE candidate_id NOT IN ({placeholders})",
                    tuple(current_ids),
                )

    def cached_extraction(self, file_id: str, extractor_version: str) -> ExtractionResult | None:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT extraction_json,extractor_version FROM files WHERE file_id=?", (file_id,)
            ).fetchone()
        if not row or not row["extraction_json"] or row["extractor_version"] != extractor_version:
            return None
        return ExtractionResult.model_validate_json(row["extraction_json"])

    def save_extraction(self, result: ExtractionResult) -> None:
        with self.connection() as conn:
            conn.execute(
                """UPDATE files SET extraction_status=?,extractor_version=?,extraction_json=?,
                   updated_at=? WHERE file_id=?""",
                (
                    result.status,
                    result.extractor_version,
                    result.model_dump_json(),
                    utc_now(),
                    result.file_id,
                ),
            )

    def update_material_roles(self, candidate_id: str, roles: dict[str, str]) -> None:
        if not roles:
            return
        with self.connection() as conn:
            for file_id, role in roles.items():
                conn.execute(
                    """UPDATE candidate_files SET material_role=?
                       WHERE candidate_id=? AND file_id=? AND active=1""",
                    (role, candidate_id, file_id),
                )

    def set_candidate_state(self, candidate_id: str, state: CandidateState) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE candidates SET state=?,updated_at=? WHERE candidate_id=?",
                (state, utc_now(), candidate_id),
            )

    def create_run(
        self,
        run_id: str,
        resume_root: Path,
        output_root: Path,
        jd: str,
        requirements: str,
        criteria_hash: str,
        config_json: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO runs(run_id,resume_root,output_root,jd,requirements,criteria_hash,
                   config_json,status,started_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    run_id,
                    str(resume_root),
                    str(output_root),
                    jd,
                    requirements,
                    criteria_hash,
                    config_json,
                    "running",
                    utc_now(),
                ),
            )

    def save_criteria(self, run_id: str, criteria: list[Criterion]) -> None:
        with self.connection() as conn:
            for item in criteria:
                conn.execute(
                    """INSERT OR REPLACE INTO criteria(run_id,criterion_id,version,criterion_json)
                       VALUES(?,?,?,?)""",
                    (run_id, item.criterion_id, item.version, item.model_dump_json()),
                )

    def save_analysis(
        self,
        run_id: str,
        package_hash: str,
        criteria_hash: str,
        result: AnalysisResult,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO analyses(run_id,candidate_id,package_hash,criteria_hash,
                   model,result_json,updated_at) VALUES(?,?,?,?,?,?,?)""",
                (
                    run_id,
                    result.candidate_id,
                    package_hash,
                    criteria_hash,
                    result.model,
                    result.model_dump_json(),
                    utc_now(),
                ),
            )

    def find_cached_analysis(
        self, package_hash: str, criteria_hash: str, model: str
    ) -> AnalysisResult | None:
        with self.connection() as conn:
            row = conn.execute(
                """SELECT result_json FROM analyses WHERE package_hash=? AND criteria_hash=?
                   AND model=? ORDER BY updated_at DESC LIMIT 1""",
                (package_hash, criteria_hash, model),
            ).fetchone()
        return AnalysisResult.model_validate_json(row["result_json"]) if row else None

    def finish_run(self, run_id: str, status: str = "completed") -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE runs SET status=?,finished_at=? WHERE run_id=?",
                (status, utc_now(), run_id),
            )

    def analyses_for_run(self, run_id: str) -> list[AnalysisResult]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT result_json FROM analyses WHERE run_id=? ORDER BY updated_at", (run_id,)
            ).fetchall()
        return [AnalysisResult.model_validate_json(row["result_json"]) for row in rows]

    def list_candidates(self, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM candidates"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY display_name"
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(query).fetchall()]

    def manual_fields_for(self, candidate_id: str) -> dict[str, str]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT hr_status,owner,note FROM manual_fields WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        return dict(row) if row else {"hr_status": "", "owner": "", "note": ""}

    def save_manual_fields(
        self,
        candidate_id: str,
        hr_status: str,
        owner: str,
        note: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO manual_fields(candidate_id,hr_status,owner,note,updated_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET
                   hr_status=excluded.hr_status,owner=excluded.owner,note=excluded.note,
                   updated_at=excluded.updated_at""",
                (candidate_id, hr_status, owner, note, utc_now()),
            )

    def all_manual_fields(self) -> dict[str, dict[str, str]]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT candidate_id,hr_status,owner,note FROM manual_fields"
            ).fetchall()
        return {
            row["candidate_id"]: {
                "hr_status": row["hr_status"],
                "owner": row["owner"],
                "note": row["note"],
            }
            for row in rows
        }

    def files_for_candidate(self, candidate_id: str) -> list[dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(
                """SELECT f.*,cf.absolute_path,cf.relative_path,cf.material_role,cf.active
                   FROM files f JOIN candidate_files cf ON f.file_id=cf.file_id
                   WHERE cf.candidate_id=? AND cf.active=1 ORDER BY cf.relative_path""",
                (candidate_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        run_id: str | None = None,
        candidate_id: str | None = None,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """INSERT INTO events(run_id,candidate_id,event_type,payload_json,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    run_id,
                    candidate_id,
                    event_type,
                    json.dumps(payload, ensure_ascii=False),
                    utc_now(),
                ),
            )
