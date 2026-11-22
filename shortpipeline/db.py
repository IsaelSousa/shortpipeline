"""Fila de jobs em SQLite. Cada job é um short passando pelas etapas."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from . import config

_local = threading.local()
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    topic TEXT,
    status TEXT NOT NULL,          -- queued | running | waiting_approval | done | failed | canceled
    stage TEXT,                    -- etapa atual
    stages TEXT NOT NULL,          -- json {etapa: {status, started, ended, error, detail}}
    data TEXT NOT NULL,            -- json com roteiro, caminhos, resultado do upload...
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_channel ON jobs(channel, created_at);
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    ts REAL NOT NULL,
    level TEXT NOT NULL,
    stage TEXT,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS logs_job ON logs(job_id, id);
CREATE TABLE IF NOT EXISTS used_sources (
    channel TEXT NOT NULL,
    key TEXT NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY (channel, key)
);
"""


def _conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DATA_DIR / "pipeline.db", timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "kind" not in cols:  # migração: tipos de job (short, long, fonte, corte)
            conn.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'short'")
        if "parent_id" not in cols:
            conn.execute("ALTER TABLE jobs ADD COLUMN parent_id TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS jobs_parent ON jobs(parent_id)")
        conn.commit()
        _local.conn = conn
    return conn


@contextmanager
def _tx():
    with _write_lock:
        conn = _conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    d["stages"] = json.loads(d["stages"])
    d["kind"] = d.get("kind") or "short"
    # só as etapas do tipo, na ordem certa; etapas criadas depois do job aparecem como pendentes
    d["stages"] = {s: d["stages"].get(s, {"status": "pending"}) for s in config.stages_for(d["kind"])}
    d["data"] = json.loads(d["data"])
    return d


def create_job(channel: str, topic: str | None = None, kind: str = "short", parent_id: str | None = None,
               data: dict | None = None) -> dict:
    now = time.time()
    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    stages = {s: {"status": "pending"} for s in config.stages_for(kind)}
    with _tx() as c:
        c.execute(
            "INSERT INTO jobs (id, channel, topic, status, stage, stages, data, error, created_at, updated_at,"
            " kind, parent_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, channel, topic or None, "queued", None, json.dumps(stages),
             json.dumps(data or {}, ensure_ascii=False), None, now, now, kind, parent_id),
        )
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    return _row(_conn().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


def list_jobs(channel: str | None = None, limit: int = 100, kind: str | None = None) -> list[dict]:
    where, args = [], []
    if channel:
        where.append("channel=?"); args.append(channel)
    if kind:
        kinds = kind.split(",")
        where.append(f"kind IN ({','.join('?' * len(kinds))})"); args += kinds
    sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT ?"
    return [_row(r) for r in _conn().execute(sql, (*args, limit)).fetchall()]


def list_children(parent_id: str) -> list[dict]:
    rows = _conn().execute("SELECT * FROM jobs WHERE parent_id=? ORDER BY created_at", (parent_id,))
    return [_row(r) for r in rows.fetchall()]


def next_queued() -> dict | None:
    return _row(_conn().execute(
        "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone())


def update_job(job_id: str, **fields) -> dict:
    """Atualiza colunas. `stages` e `data` são mesclados (não substituídos)."""
    with _tx() as c:
        row = _row(c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
        if row is None:
            raise KeyError(job_id)
        if "stages" in fields:
            for name, info in fields.pop("stages").items():
                row["stages"].setdefault(name, {}).update(info)
        if "data" in fields:
            row["data"].update(fields.pop("data"))
        row.update(fields)
        row["updated_at"] = time.time()
        c.execute(
            "UPDATE jobs SET topic=?, status=?, stage=?, stages=?, data=?, error=?, updated_at=? WHERE id=?",
            (row["topic"], row["status"], row["stage"], json.dumps(row["stages"], ensure_ascii=False),
             json.dumps(row["data"], ensure_ascii=False), row["error"], row["updated_at"], job_id),
        )
    return row


def set_stage(job_id: str, stage: str, **info) -> dict:
    return update_job(job_id, stages={stage: info})


def reset_from(job_id: str, stage: str) -> dict:
    """Marca a etapa e todas as seguintes como pendentes e põe o job de volta na fila."""
    job = get_job(job_id)
    order = config.stages_for(job["kind"])
    idx = order.index(stage)
    stages = {s: {"status": "pending", "error": None, "started": None, "ended": None, "detail": None}
              for s in order[idx:]}
    return update_job(job_id, stages=stages, status="queued", stage=None, error=None)


def delete_job(job_id: str) -> None:
    with _tx() as c:
        c.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        c.execute("DELETE FROM logs WHERE job_id=?", (job_id,))


def recover_interrupted() -> int:
    """Jobs que estavam rodando quando o servidor caiu voltam para a fila."""
    with _tx() as c:
        cur = c.execute("UPDATE jobs SET status='queued' WHERE status='running'")
        return cur.rowcount


def log(job_id: str, message: str, level: str = "info", stage: str | None = None) -> None:
    with _tx() as c:
        c.execute("INSERT INTO logs (job_id, ts, level, stage, message) VALUES (?,?,?,?,?)",
                  (job_id, time.time(), level, stage, message))


def get_logs(job_id: str, after_id: int = 0) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM logs WHERE job_id=? AND id>? ORDER BY id LIMIT 1000", (job_id, after_id))
    return [dict(r) for r in rows.fetchall()]


def recent_titles(channel: str, limit: int = 40) -> list[str]:
    titles = []
    for job in list_jobs(channel, limit=limit * 2):
        t = (job["data"].get("script") or {}).get("title")
        if t:
            titles.append(t)
    return titles[:limit]


def source_used(channel: str, key: str) -> bool:
    return _conn().execute("SELECT 1 FROM used_sources WHERE channel=? AND key=?", (channel, key)).fetchone() is not None


def mark_source_used(channel: str, key: str) -> None:
    with _tx() as c:
        c.execute("INSERT OR IGNORE INTO used_sources VALUES (?,?,?)", (channel, key, time.time()))


def stats() -> dict:
    rows = _conn().execute("SELECT channel, status, COUNT(*) n FROM jobs GROUP BY channel, status").fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["channel"], {})[r["status"]] = r["n"]
    return out
