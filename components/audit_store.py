# -*- coding: utf-8 -*-
"""SQLite 持久化审计链。记录会话、运行、工具调用、确认和客服工单。"""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from components.config import SETTINGS


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _conn():
    path = os.environ.get("DRIVEMATE_AUDIT_DB", SETTINGS.audit_db)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _db():
    conn = _conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with _db() as c:
        c.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_text TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                intent TEXT,
                risk_level TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_calls (
                call_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                level TEXT NOT NULL,
                status TEXT NOT NULL,
                backend TEXT,
                arguments_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                latency_ms REAL,
                receipt_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS confirmations (
                confirmation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                tool TEXT NOT NULL,
                decision TEXT NOT NULL,
                decided_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                run_id TEXT,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idempotency_records (
                execution_key TEXT PRIMARY KEY,
                run_id TEXT,
                tool TEXT NOT NULL,
                arguments_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS decision_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                duration_ms REAL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls(run_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_decision_events_run ON decision_events(run_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_confirmations_run ON confirmations(run_id, decided_at);
            """
        )


def create_session(user_id: str, mode: str) -> str:
    init_db()
    session_id = "S-" + uuid.uuid4().hex[:16]
    with _db() as c:
        c.execute("INSERT INTO sessions VALUES (?,?,?,?)", (session_id, user_id, mode, _now()))
    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Return session ownership metadata without exposing unrelated runs."""
    init_db()
    with _db() as c:
        row = c.execute(
            "SELECT session_id,user_id,mode,started_at FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def get_session_history(session_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Return recent completed turns in chronological order for cross-run context."""
    init_db()
    with _db() as c:
        rows = c.execute(
            """SELECT run_id,user_text,result_json,created_at
               FROM runs WHERE session_id=? AND result_json IS NOT NULL
               ORDER BY created_at DESC LIMIT ?""",
            (session_id, max(1, min(int(limit), 20))),
        ).fetchall()
    history = []
    for row in reversed(rows):
        result = json.loads(row["result_json"]) if row["result_json"] else {}
        history.append(
            {
                "run_id": row["run_id"],
                "user": row["user_text"],
                "assistant": str(result.get("reply") or ""),
                "intent": result.get("intent"),
                "created_at": row["created_at"],
            }
        )
    return history


def start_run(session_id: str, user_text: str, snapshot: Dict[str, Any]) -> str:
    init_db()
    run_id = "R-" + uuid.uuid4().hex[:16]
    ts = _now()
    with _db() as c:
        c.execute(
            "INSERT INTO runs(run_id,session_id,user_text,snapshot_json,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (run_id, session_id, user_text, json.dumps(snapshot, ensure_ascii=False), ts, ts),
        )
    return run_id


def finish_run(run_id: str, result: Dict[str, Any]) -> None:
    serializable = {k: v for k, v in result.items() if not str(k).startswith("_")}
    with _db() as c:
        cursor = c.execute(
            "UPDATE runs SET intent=?, risk_level=?, result_json=?, updated_at=? WHERE run_id=?",
            (result.get("intent"), result.get("risk_level"), json.dumps(serializable, ensure_ascii=False), _now(), run_id),
        )
        if cursor.rowcount != 1:
            raise KeyError("run not found: %s" % run_id)


def log_tool_call(run_id: Optional[str], call: Dict[str, Any]) -> str:
    init_db()
    call_id = "C-" + uuid.uuid4().hex[:18]
    if not run_id:
        return call_id
    result_payload = call.get("raw_result") or {"summary": call.get("summary", ""), "result": call.get("result")}
    with _db() as c:
        c.execute(
            """INSERT INTO tool_calls(call_id,run_id,tool,level,status,backend,arguments_json,result_json,latency_ms,receipt_id,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call_id, run_id, call.get("tool", ""), call.get("level", "L0"), call.get("result", "unknown"),
                call.get("backend"), json.dumps(call.get("arguments", {}), ensure_ascii=False),
                json.dumps(result_payload, ensure_ascii=False), call.get("latency_ms"), call.get("receipt_id"), _now(),
            ),
        )
    return call_id


def get_latest_successful_tool_result(run_id: str, tool: str) -> Optional[Dict[str, Any]]:
    """Return the latest persisted success receipt for a tool in this run."""
    init_db()
    with _db() as c:
        row = c.execute(
            """SELECT result_json FROM tool_calls
               WHERE run_id=? AND tool=? AND status='success'
               ORDER BY created_at DESC LIMIT 1""",
            (run_id, tool),
        ).fetchone()
    return json.loads(row["result_json"]) if row and row["result_json"] else None


def log_confirmation(run_id: str, tool: str, decision: str) -> None:
    init_db()
    with _db() as c:
        c.execute(
            "INSERT INTO confirmations VALUES (?,?,?,?,?)",
            ("K-" + uuid.uuid4().hex[:18], run_id, tool, decision, _now()),
        )


def log_ticket(ticket: Dict[str, Any], run_id: Optional[str] = None) -> None:
    init_db()
    ticket_id = str(ticket.get("ticket_id") or ("TK-" + uuid.uuid4().hex[:16]))
    with _db() as c:
        c.execute(
            "INSERT OR REPLACE INTO tickets(ticket_id,run_id,payload_json,created_at) VALUES (?,?,?,?)",
            (ticket_id, run_id, json.dumps(ticket, ensure_ascii=False), _now()),
        )


def _decode_row(row, json_columns: Dict[str, str]):
    if not row:
        return None
    output = dict(row)
    for source, target in json_columns.items():
        raw = output.pop(source, None)
        output[target] = json.loads(raw) if raw else None
    return output


def get_run_context(run_id: str) -> Optional[Dict[str, Any]]:
    """Return the persisted request and latest result needed by confirm/cancel."""
    init_db()
    with _db() as c:
        row = c.execute(
            """SELECT r.run_id,r.session_id,r.user_text,r.snapshot_json,r.intent,
                      r.risk_level,r.result_json,r.created_at,r.updated_at,
                      s.user_id,s.mode
               FROM runs r
               JOIN sessions s ON s.session_id=r.session_id
               WHERE r.run_id=?""",
            (run_id,),
        ).fetchone()
    return _decode_row(
        row,
        {"snapshot_json": "snapshot", "result_json": "result"},
    )


def get_run_trace(run_id: str) -> Dict[str, Any]:
    init_db()
    with _db() as c:
        run = c.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        calls = c.execute("SELECT * FROM tool_calls WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        confirms = c.execute("SELECT * FROM confirmations WHERE run_id=? ORDER BY decided_at", (run_id,)).fetchall()
        tickets = c.execute("SELECT * FROM tickets WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        events = c.execute("SELECT * FROM decision_events WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
    return {
        "run": _decode_row(
            run,
            {"snapshot_json": "snapshot", "result_json": "result"},
        ),
        "tool_calls": [
            _decode_row(
                row,
                {"arguments_json": "arguments", "result_json": "result"},
            )
            for row in calls
        ],
        "confirmations": [dict(row) for row in confirms],
        "tickets": [
            _decode_row(row, {"payload_json": "payload"}) for row in tickets
        ],
        "decision_events": [
            _decode_row(row, {"payload_json": "payload"}) for row in events
        ],
    }


def recent_runs(limit: int = 20) -> List[Dict[str, Any]]:
    init_db()
    with _db() as c:
        rows = c.execute(
            "SELECT run_id,session_id,user_text,intent,risk_level,created_at,updated_at FROM runs ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(x) for x in rows]


def get_idempotency_result(execution_key: str):
    init_db()
    with _db() as c:
        row = c.execute("SELECT result_json FROM idempotency_records WHERE execution_key=?", (execution_key,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["result_json"])
    except Exception:
        return None


def put_idempotency_result(execution_key: str, run_id: Optional[str], tool: str, arguments: Dict[str, Any], result: Dict[str, Any]) -> None:
    init_db()
    with _db() as c:
        c.execute("INSERT OR REPLACE INTO idempotency_records(execution_key,run_id,tool,arguments_json,result_json,created_at) VALUES (?,?,?,?,?,?)",
                  (execution_key, run_id, tool, json.dumps(arguments or {}, ensure_ascii=False),
                   json.dumps(result or {}, ensure_ascii=False), _now()))


def log_decision_event(run_id: Optional[str], stage: str, payload: Dict[str, Any], duration_ms: Optional[float] = None) -> None:
    init_db()
    if not run_id:
        return
    with _db() as c:
        c.execute("INSERT INTO decision_events(event_id,run_id,stage,payload_json,duration_ms,created_at) VALUES (?,?,?,?,?,?)",
                  ("E-" + uuid.uuid4().hex[:18], run_id, stage, json.dumps(payload or {}, ensure_ascii=False), duration_ms, _now()))
