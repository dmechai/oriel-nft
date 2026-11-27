from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .settings import data_dir

SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  api_key_enc TEXT NOT NULL,
  vision_model TEXT DEFAULT '',
  text_model TEXT DEFAULT '',
  image_model TEXT DEFAULT '',
  edit_model TEXT DEFAULT '',
  image_api TEXT NOT NULL DEFAULT 'openai_images',
  is_default INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  target_count INTEGER NOT NULL DEFAULT 100,
  width INTEGER NOT NULL DEFAULT 1024,
  height INTEGER NOT NULL DEFAULT 1024,
  style_notes TEXT DEFAULT '',
  subject_mode TEXT NOT NULL DEFAULT 'recognizable',
  skill_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  provider_id TEXT,
  analysis_json TEXT,
  style_contract_json TEXT,
  plan_json TEXT,
  collection_seed INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  label TEXT DEFAULT '',
  path TEXT NOT NULL,
  meta_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS nfts (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  token_id INTEGER NOT NULL,
  image_path TEXT NOT NULL,
  attributes_json TEXT NOT NULL,
  locked INTEGER NOT NULL DEFAULT 0,
  flagged INTEGER NOT NULL DEFAULT 0,
  flag_reason TEXT DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trials (
  project_id TEXT PRIMARY KEY,
  signature TEXT NOT NULL,
  images_json TEXT NOT NULL,
  approved INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  message TEXT DEFAULT '',
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id, kind);
CREATE INDEX IF NOT EXISTS idx_nfts_project ON nfts(project_id, token_id);
CREATE INDEX IF NOT EXISTS idx_jobs_project ON jobs(project_id, created_at);
"""


class Database:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.init()

    def path(self):
        return data_dir() / "oriel.sqlite"

    def init(self) -> None:
        with self.session() as conn:
            conn.executescript(SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(providers)")}
            if "edit_model" not in columns:
                conn.execute("ALTER TABLE providers ADD COLUMN edit_model TEXT DEFAULT ''")

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        data_dir()
        conn = sqlite3.connect(self.path(), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL").fetchone()
        try:
            with self._lock:
                yield conn
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def q(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self.session() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None

    def run(self, sql: str, params: tuple = ()) -> None:
        with self.session() as conn:
            conn.execute(sql, params)
