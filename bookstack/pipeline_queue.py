"""
pipeline_queue.py — CA パイプライン専用ジョブキュー（SQLite）
=============================================================
責任範囲: キュレーションジョブの管理のみ。
l_mail.db（ラボメン通知）とは完全に分離する。

使い方:
    from bookstack.pipeline_queue import PipelineQueue

    q = PipelineQueue()
    q.enqueue("page_update", page_id=42, page_path="research/my-note", page_title="My Note")
    job = q.dequeue()
    q.mark_done(job["id"])
"""

import sqlite3
import json
import time
from pathlib import Path

# DB パス（プロジェクトルート/data/pipeline_queue.db）
_DEFAULT_DB = Path(__file__).parent.parent / "data" / "pipeline_queue.db"


class PipelineQueue:
    def __init__(self, db_path: str | Path = None):
        self.db_path = Path(db_path) if db_path else _DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """テーブルを初期化する（存在しない場合のみ作成）。"""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pipeline_jobs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type  TEXT    NOT NULL,
                    page_id     INTEGER,
                    page_path   TEXT,
                    page_title  TEXT,
                    payload     TEXT,
                    status      TEXT    NOT NULL DEFAULT 'pending',
                    created_at  REAL    NOT NULL,
                    updated_at  REAL    NOT NULL,
                    error       TEXT
                )
            """)
            # インデックス
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_status_created
                ON pipeline_jobs(status, created_at)
            """)

    def enqueue(
        self,
        event_type: str,
        page_id: int = None,
        page_path: str = None,
        page_title: str = None,
        payload: dict = None,
    ) -> int:
        """
        ジョブをキューに追加する。
        重複チェック: 同一 page_id + status=pending が既にある場合はスキップ。

        Returns:
            job_id（新規作成時）or -1（重複スキップ時）
        """
        now = time.time()
        with self._connect() as conn:
            # 重複チェック（同一ページが pending 中なら追加しない）
            if page_id:
                existing = conn.execute(
                    "SELECT id FROM pipeline_jobs WHERE page_id=? AND status='pending'",
                    (page_id,)
                ).fetchone()
                if existing:
                    return -1

            cur = conn.execute(
                """INSERT INTO pipeline_jobs
                   (event_type, page_id, page_path, page_title, payload, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                (
                    event_type,
                    page_id,
                    page_path,
                    page_title,
                    json.dumps(payload or {}),
                    now,
                    now,
                )
            )
            return cur.lastrowid

    def dequeue(self) -> dict | None:
        """
        pending の最古ジョブを取り出して processing にする。
        Returns: job dict or None
        """
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """SELECT * FROM pipeline_jobs
                   WHERE status='pending'
                   ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE pipeline_jobs SET status='processing', updated_at=? WHERE id=?",
                (now, row["id"])
            )
            job = dict(row)
            job["payload"] = json.loads(job["payload"] or "{}")
            return job

    def mark_done(self, job_id: int):
        """ジョブを完了にする。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE pipeline_jobs SET status='done', updated_at=? WHERE id=?",
                (time.time(), job_id)
            )

    def mark_failed(self, job_id: int, error: str = ""):
        """ジョブを失敗にする。"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE pipeline_jobs SET status='failed', updated_at=?, error=? WHERE id=?",
                (time.time(), error, job_id)
            )

    def list_jobs(self, status: str = None, limit: int = 50) -> list[dict]:
        """ジョブ一覧を返す。"""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM pipeline_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM pipeline_jobs ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            result = []
            for row in rows:
                job = dict(row)
                job["payload"] = json.loads(job["payload"] or "{}")
                result.append(job)
            return result

    def stats(self) -> dict:
        """ステータス別件数を返す。"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM pipeline_jobs GROUP BY status"
            ).fetchall()
            return {row["status"]: row["cnt"] for row in rows}


if __name__ == "__main__":
    # 動作確認
    q = PipelineQueue("/tmp/test_pipeline_queue.db")
    jid = q.enqueue("page_update", page_id=42, page_path="research/my-note", page_title="My Note")
    print(f"enqueued: {jid}")
    job = q.dequeue()
    print(f"dequeued: {job}")
    q.mark_done(job["id"])
    print(f"stats: {q.stats()}")
    print("OK")
