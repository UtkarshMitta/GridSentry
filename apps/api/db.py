"""SQLite persistence for analysis runs."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).parent / "gridsentry.db"
_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                name TEXT NOT NULL,
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                project_type TEXT NOT NULL,
                status TEXT NOT NULL,
                gis_json TEXT,
                report_json TEXT,
                events_json TEXT
            )
            """
        )
        _conn.commit()
    return _conn


def create_run(run_id: str, created_at: str, name: str, lat: float, lon: float, project_type: str) -> None:
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO runs (id, created_at, name, lat, lon, project_type, status, events_json) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, created_at, name, lat, lon, project_type, "running", "[]"),
        )
        conn.commit()


def update_run(run_id: str, **fields: Any) -> None:
    mapping = {
        "status": lambda v: v,
        "gis": lambda v: json.dumps(v),
        "report": lambda v: json.dumps(v),
        "events": lambda v: json.dumps(v),
    }
    cols, vals = [], []
    for key, value in fields.items():
        col = {"gis": "gis_json", "report": "report_json", "events": "events_json"}.get(key, key)
        cols.append(f"{col} = ?")
        vals.append(mapping[key](value))
    with _lock:
        conn = _get_conn()
        conn.execute(f"UPDATE runs SET {', '.join(cols)} WHERE id = ?", (*vals, run_id))
        conn.commit()


def get_run(run_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        row = _get_conn().execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return _row_to_dict(row)


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    with _lock:
        rows = _get_conn().execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r, include_payloads=False) for r in rows]


def _row_to_dict(row: sqlite3.Row, include_payloads: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "created_at": row["created_at"],
        "name": row["name"],
        "lat": row["lat"],
        "lon": row["lon"],
        "project_type": row["project_type"],
        "status": row["status"],
    }
    if include_payloads:
        out["gis"] = json.loads(row["gis_json"]) if row["gis_json"] else None
        out["report"] = json.loads(row["report_json"]) if row["report_json"] else None
        out["events"] = json.loads(row["events_json"]) if row["events_json"] else []
    else:
        report = json.loads(row["report_json"]) if row["report_json"] else None
        out["risk_level"] = report["risk_level"] if report else None
        out["risk_score"] = report["risk_score"] if report else None
    return out
