"""GridSentry API — ingestion, agent pipeline, SSE progress, run storage."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import db
from agents import orchestrator
from models import SiteInput

app = FastAPI(title="GridSentry API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Live event buffers per run: events list + condition for SSE subscribers.
_events: dict[str, list[dict[str, Any]]] = {}
_conditions: dict[str, asyncio.Condition] = {}


def _condition(run_id: str) -> asyncio.Condition:
    if run_id not in _conditions:
        _conditions[run_id] = asyncio.Condition()
    return _conditions[run_id]


async def _emit(run_id: str, event: dict[str, Any]) -> None:
    _events.setdefault(run_id, []).append(event)
    cond = _condition(run_id)
    async with cond:
        cond.notify_all()


async def _execute(run_id: str, site_input: SiteInput) -> None:
    try:
        gis, report = await orchestrator.run_pipeline(
            run_id, site_input, lambda e: _emit(run_id, e)
        )
        db.update_run(
            run_id,
            status="complete",
            gis=gis.model_dump(),
            report=report.model_dump(),
            events=_events.get(run_id, []),
        )
        await _emit(run_id, {"type": "complete", "progress": 1.0})
    except Exception as exc:  # surface pipeline failures to the client
        db.update_run(run_id, status="error", events=_events.get(run_id, []))
        await _emit(run_id, {"type": "error", "message": str(exc)})


@app.post("/runs")
async def create_run(site: SiteInput) -> dict[str, str]:
    run_id = uuid.uuid4().hex[:12]
    name = site.name or f"Site @ {site.lat:.4f}, {site.lon:.4f}"
    db.create_run(run_id, datetime.now(timezone.utc).isoformat(), name, site.lat, site.lon, site.project_type)
    _events[run_id] = []
    asyncio.create_task(_execute(run_id, site))
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
        # Replay persisted events if the live buffer is gone (e.g. reload after restart)
        if run_id not in _events and run["events"]:
            for event in run["events"]:
                yield f"data: {json.dumps(event)}\n\n"
            yield f"data: {json.dumps({'type': 'complete' if run['status'] == 'complete' else 'error', 'progress': 1.0})}\n\n"
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
