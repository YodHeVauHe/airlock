"""SQLite persistence: tasks, artifacts metadata, and the durable event log."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    lane TEXT NOT NULL DEFAULT 'analyze',
    status TEXT NOT NULL DEFAULT 'queued',
    driver TEXT NOT NULL DEFAULT '',
    torture INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    explain TEXT,
    receipt TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    name TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'file',
    FOREIGN KEY(task_id) REFERENCES tasks(id)
);
CREATE TABLE IF NOT EXISTS events (
    task_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (task_id, seq)
);
"""


class Store:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # --- tasks ---

    def create_task(self, task_id: str, goal: str, lane: str, driver: str, torture: bool) -> None:
        now = time.time()
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO tasks (id, goal, lane, status, driver, torture, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (task_id, goal, lane, "queued", driver, int(torture), now, now),
            )

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock, self._conn() as c:
            c.execute(f"UPDATE tasks SET {cols} WHERE id=?", (*fields.values(), task_id))

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn() as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- artifacts ---

    def add_artifact(self, task_id: str, name: str, path: str, size: int, kind: str = "file") -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO artifacts (task_id, name, path, size, kind) VALUES (?,?,?,?,?)",
                (task_id, name, path, size, kind),
            )

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT name, path, size, kind FROM artifacts WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    # --- durable event log ---

    def append_event(self, task_id: str, ev: dict[str, Any]) -> None:
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO events (task_id, seq, data) VALUES (?,?,?)",
                (task_id, ev["seq"], json.dumps(ev, default=str)),
            )

    def load_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock, self._conn() as c:
            rows = c.execute(
                "SELECT data FROM events WHERE task_id=? ORDER BY seq", (task_id,)
            ).fetchall()
        return [json.loads(r["data"]) for r in rows]
