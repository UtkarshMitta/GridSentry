"""GridSentry API — ingestion, agent pipeline, SSE progress, run storage."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency) so TAVILY/OPENAI keys are picked up."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import db
from agents import orchestrator
from models import SiteInput

INTERRUPTED = "Run interrupted: the API restarted before this analysis finished. Start a new analysis."


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs left 'running' by a previous process will never finish.
    db.fail_orphaned_runs(INTERRUPTED)
    yield


app = FastAPI(title="GridSentry API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Live event buffers per run: events list + condition for SSE subscribers.
_events: dict[str, list[dict[str, Any]]] = {}
_conditions: dict[str, asyncio.Condition] = {}
# Strong references: the event loop only weakly references tasks, so an
# un-referenced pipeline task can be garbage-collected mid-run.
_tasks: set[asyncio.Task] = set()
# How long a finished run's live buffer is kept before SSE replays from SQLite.
BUFFER_TTL_S = 300


def _condition(run_id: str) -> asyncio.Condition:
    if run_id not in _conditions:
        _conditions[run_id] = asyncio.Condition()
    return _conditions[run_id]


async def _emit(run_id: str, event: Optional[dict[str, Any]]) -> None:
    """Append an event (None = just notify) and wake SSE subscribers."""
    if event is not None:
        _events.setdefault(run_id, []).append(event)
    cond = _condition(run_id)
    async with cond:
        cond.notify_all()


async def _execute(run_id: str, site_input: SiteInput) -> None:
    try:
        gis, report = await orchestrator.run_pipeline(
            run_id, site_input, lambda e: _emit(run_id, e)
        )
        _events[run_id].append({"type": "complete", "progress": 1.0})
        db.update_run(
            run_id,
            status="complete",
            gis=gis.model_dump(),
            report=report.model_dump(),
            events=_events[run_id],
        )
    except Exception as exc:  # surface pipeline failures to the client
        _events[run_id].append({"type": "error", "message": str(exc) or type(exc).__name__})
        db.update_run(run_id, status="error", events=_events[run_id])
    # Wake SSE subscribers only after the DB reflects the terminal state, so a
    # client that fetches the run on 'complete' never sees it still running.
    await _emit(run_id, None)
    await asyncio.sleep(BUFFER_TTL_S)
    _events.pop(run_id, None)
    _conditions.pop(run_id, None)


@app.post("/runs")
async def create_run(site: SiteInput) -> dict[str, str]:
    run_id = uuid.uuid4().hex[:12]
    name = site.name or f"Site @ {site.lat:.4f}, {site.lon:.4f}"
    db.create_run(run_id, datetime.now(timezone.utc).isoformat(), name, site.lat, site.lon, site.project_type)
    _events[run_id] = []
    task = asyncio.create_task(_execute(run_id, site))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"run_id": run_id}


@app.get("/runs")
async def list_runs() -> list[dict[str, Any]]:
    return db.list_runs()


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    async def generator():
        # Not executing in this process: replay what was persisted and end the
        # stream. A run still marked 'running' here was orphaned by a restart.
        if run_id not in _events:
            events = [e for e in run["events"] if e.get("type") not in ("complete", "error")]
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
            if run["status"] == "complete":
                terminal = {"type": "complete", "progress": 1.0}
            else:
                if run["status"] == "running":
                    db.update_run(run_id, status="error")
                terminal = next(
                    (e for e in reversed(run["events"]) if e.get("type") == "error"),
                    {"type": "error", "message": INTERRUPTED},
                )
            yield f"data: {json.dumps(terminal)}\n\n"
            return

        index = 0
        cond = _condition(run_id)
        while True:
            buffer = _events.get(run_id, [])
            while index < len(buffer):
                event = buffer[index]
                index += 1
                yield f"data: {json.dumps(event)}\n\n"
                if event["type"] in ("complete", "error"):
                    return
            async with cond:
                try:
                    await asyncio.wait_for(cond.wait(), timeout=30)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
