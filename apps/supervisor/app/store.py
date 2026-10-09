from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS campaign_snapshots (
                    campaign_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS review_items (
                    id TEXT PRIMARY KEY,
                    case_key TEXT NOT NULL UNIQUE,
                    campaign_id TEXT NOT NULL REFERENCES campaign_snapshots(campaign_id) ON DELETE CASCADE,
                    campaign_name TEXT NOT NULL,
                    contact_ref TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    language TEXT NOT NULL,
                    segment TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ix_review_items_status_created
                    ON review_items(status, created_at DESC);
                CREATE TABLE IF NOT EXISTS auto_retry_runs (
                    attempt_key TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    queued INTEGER NOT NULL,
                    attempted_at TEXT NOT NULL
                );
                """
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def save_campaign(
        self,
        campaign_id: str,
        snapshot: dict[str, Any],
        analysis: dict[str, Any],
        fingerprint: str,
        review_candidates: list[dict[str, Any]],
    ) -> None:
        observed_at = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO campaign_snapshots
                   (campaign_id, fingerprint, snapshot_json, analysis_json, observed_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(campaign_id) DO UPDATE SET
                   fingerprint=excluded.fingerprint,
                   snapshot_json=excluded.snapshot_json,
                   analysis_json=excluded.analysis_json,
                   observed_at=excluded.observed_at""",
                (
                    campaign_id,
                    fingerprint,
                    json.dumps(snapshot, ensure_ascii=False),
                    json.dumps(analysis, ensure_ascii=False),
                    observed_at,
                ),
            )
            for item in review_candidates:
                connection.execute(
                    """INSERT OR IGNORE INTO review_items
                       (id, case_key, campaign_id, campaign_name, contact_ref, call_id,
                        language, segment, outcome, attempt, kind, reason, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()), item["case_key"], item["campaign_id"],
                        item["campaign_name"], item["contact_ref"], item["call_id"],
                        item["language"], item["segment"], item["outcome"], item["attempt"],
                        item["kind"], item["reason"], observed_at,
                    ),
                )
            current_cases = {item["case_key"] for item in review_candidates}
            open_cases = connection.execute(
                "SELECT id, case_key FROM review_items WHERE campaign_id = ? AND status = 'open'",
                (campaign_id,),
            ).fetchall()
            stale_ids = [row["id"] for row in open_cases if row["case_key"] not in current_cases]
            connection.executemany(
                "UPDATE review_items SET status = 'resolved', resolved_at = ? WHERE id = ?",
                [(observed_at, review_id) for review_id in stale_ids],
            )

    def remove_missing_campaigns(self, campaign_ids: set[str]) -> None:
        with self.connect() as connection:
            existing = [row[0] for row in connection.execute("SELECT campaign_id FROM campaign_snapshots")]
            missing = set(existing) - campaign_ids
            connection.executemany(
                "DELETE FROM campaign_snapshots WHERE campaign_id = ?",
                [(campaign_id,) for campaign_id in missing],
            )
            if missing:
                connection.executemany(
                    "DELETE FROM auto_retry_runs WHERE campaign_id = ?",
                    [(campaign_id,) for campaign_id in missing],
                )

    def campaign_rows(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT analysis_json, observed_at FROM campaign_snapshots ORDER BY observed_at DESC"
            ).fetchall()
        return [
            {**json.loads(row["analysis_json"]), "observed_at": row["observed_at"]}
            for row in rows
        ]

    def get_snapshot(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM campaign_snapshots WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return json.loads(row["snapshot_json"]) if row else None

    def get_analysis(self, campaign_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT analysis_json FROM campaign_snapshots WHERE campaign_id = ?",
                (campaign_id,),
            ).fetchone()
        return json.loads(row["analysis_json"]) if row else None

    def review_rows(self, status: str | None = "open") -> list[dict[str, Any]]:
        query = """SELECT id, campaign_id, campaign_name, call_id, language, segment,
                   outcome, attempt, kind, reason, status, created_at, resolved_at
                   FROM review_items"""
        params: tuple[str, ...] = ()
        if status:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def resolve_review(self, review_id: str, status: str) -> dict[str, Any] | None:
        now = datetime.now(UTC).isoformat()
        with self.connect() as connection:
            connection.execute(
                """UPDATE review_items SET status = ?, resolved_at = ?
                   WHERE id = ? AND status = 'open'""",
                (status, now, review_id),
            )
            row = connection.execute("SELECT * FROM review_items WHERE id = ?", (review_id,)).fetchone()
        return dict(row) if row else None

    def has_retry_run(self, attempt_key: str) -> bool:
        with self.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM auto_retry_runs WHERE attempt_key = ?", (attempt_key,)
            ).fetchone() is not None

    def record_retry_run(self, attempt_key: str, campaign_id: str, queued: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO auto_retry_runs VALUES (?, ?, ?, ?)",
                (attempt_key, campaign_id, queued, datetime.now(UTC).isoformat()),
            )

    def last_observed_at(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute("SELECT MAX(observed_at) FROM campaign_snapshots").fetchone()
        return row[0] if row else None
