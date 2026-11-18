"""SQLite persistence: conversation history, answer cache and request metrics.

SQLite is enough here: one container, one writer, tiny rows. A Redis or Postgres service
would add a network dependency and a second thing to deploy for no benefit at this scale.
The file lives on the container's disk, so it resets on redeploy; that is acceptable for
chat sessions and metrics, and the knowledge base itself is baked into the image.
"""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    outcome TEXT NOT NULL,
    model TEXT,
    total_ms INTEGER NOT NULL,
    retrieval_ms INTEGER NOT NULL,
    llm_ms INTEGER NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    cache_hit INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: Path | str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # One shared connection guarded by a lock: FastAPI runs sync work in a thread pool.
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def _execute(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            rows = cursor.fetchall()
            self._conn.commit()
            return rows

    # ---------------------------------------------------------------- conversations

    def add_message(self, session_id: str, role: str, content: str, sources: list[dict] | None = None) -> None:
        self._execute(
            "INSERT INTO messages (session_id, role, content, sources, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, json.dumps(sources or [], ensure_ascii=False), time.time()),
        )

    def get_messages(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._execute(
            "SELECT role, content, sources, created_at FROM messages WHERE session_id = ? ORDER BY id LIMIT ?",
            (session_id, limit),
        )
        return [
            {"role": r["role"], "content": r["content"], "sources": json.loads(r["sources"]), "created_at": r["created_at"]}
            for r in rows
        ]

    def recent_turns(self, session_id: str, turns: int) -> list[dict[str, str]]:
        """The last N user/assistant exchanges, oldest first, for the LLM context window."""
        rows = self._execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, turns * 2),
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_session(self, session_id: str) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.commit()
            return cursor.rowcount

    # ---------------------------------------------------------------- cache

    def cache_get(self, key: str, ttl_seconds: int) -> dict[str, Any] | None:
        rows = self._execute("SELECT payload, created_at FROM cache WHERE key = ?", (key,))
        if not rows or time.time() - rows[0]["created_at"] > ttl_seconds:
            return None
        return json.loads(rows[0]["payload"])

    def cache_set(self, key: str, payload: dict[str, Any]) -> None:
        self._execute(
            "INSERT OR REPLACE INTO cache (key, payload, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(payload, ensure_ascii=False), time.time()),
        )

    # ---------------------------------------------------------------- metrics

    def record_metric(
        self, outcome: str, model: str | None, total_ms: int, retrieval_ms: int, llm_ms: int,
        prompt_tokens: int, completion_tokens: int, cache_hit: bool,
    ) -> None:
        self._execute(
            "INSERT INTO metrics (created_at, outcome, model, total_ms, retrieval_ms, llm_ms, prompt_tokens, "
            "completion_tokens, cache_hit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), outcome, model, total_ms, retrieval_ms, llm_ms, prompt_tokens, completion_tokens, int(cache_hit)),
        )

    def metrics_summary(self) -> dict[str, Any]:
        rows = self._execute("SELECT * FROM metrics ORDER BY id")
        if not rows:
            return {"requests": 0}
        latencies = sorted(r["total_ms"] for r in rows)

        def percentile(p: float) -> int:
            return latencies[min(len(latencies) - 1, int(round(p * (len(latencies) - 1))))]

        outcomes: dict[str, int] = {}
        models: dict[str, int] = {}
        for row in rows:
            outcomes[row["outcome"]] = outcomes.get(row["outcome"], 0) + 1
            if row["model"]:
                models[row["model"]] = models.get(row["model"], 0) + 1
        return {
            "requests": len(rows),
            "outcomes": outcomes,
            "models": models,
            "cache_hits": sum(r["cache_hit"] for r in rows),
            "latency_ms": {"p50": percentile(0.5), "p95": percentile(0.95), "max": latencies[-1]},
            "tokens": {
                "prompt": sum(r["prompt_tokens"] for r in rows),
                "completion": sum(r["completion_tokens"] for r in rows),
            },
        }
