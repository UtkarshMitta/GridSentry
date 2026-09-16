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

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import db
from agents import llm, orchestrator
from models import Health, PipelineEvent, RunCreated, RunDetail, RunSummary, SiteInput

INTERRUPTED = "Run interrupted: the API restarted before this analysis finished. Start a new analysis."


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Runs left 'running' by a previous process will never finish.
    db.fail_orphaned_runs(INTERRUPTED)
    yield


API_VERSION = "0.1.0"

app = FastAPI(
    title="GridSentry API",
    version=API_VERSION,
    lifespan=lifespan,
    summary="Autonomous NEPA environmental permit agent.",
    description=(
        "Submit coordinates and an optional footprint; the 3-agent pipeline screens live federal "
        "datasets (USFWS NWI + IPaC, FEMA NFHL, USGS PAD-US + NLCD) and returns a cited assessment.\n\n"
        "Start a run with `POST /runs`, follow it on `GET /runs/{run_id}/events` (Server-Sent Events), "
        "then read the finished report from `GET /runs/{run_id}`."
    ),
)
# Open by default (the hosted demo is called from any origin); set
# ALLOWED_ORIGINS to a comma-separated list to restrict a private deployment.
# A blank value means "unset", not "allow nothing".
_origins = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
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
    complete = {"type": "complete", "progress": 1.0}
    try:
        try:
            gis, report = await orchestrator.run_pipeline(
                run_id, site_input, lambda e: _emit(run_id, e)
            )
            # Persist before publishing 'complete', so a client that fetches
            # the run on 'complete' never finds it missing or still running.
            db.update_run(
                run_id,
                status="complete",
                # The resolved project name ("<locality> Solar Energy Center")
                # is only known after ingestion; the row was created with a
                # "Site @ lat, lon" placeholder.
                name=gis.site.name,
                gis=gis.model_dump(),
                report=report.model_dump(),
                events=_events[run_id] + [complete],
            )
            _events[run_id].append(complete)
        except Exception as exc:  # pipeline or persistence failure → error event
            _events[run_id].append({"type": "error", "message": str(exc) or type(exc).__name__})
            try:
                db.update_run(run_id, status="error", events=_events[run_id])
            except Exception:
                pass  # storage is down too; live subscribers still get the error
    finally:
        await _emit(run_id, None)  # always wake SSE subscribers
    await asyncio.sleep(BUFFER_TTL_S)
    _events.pop(run_id, None)
    _conditions.pop(run_id, None)


@app.post("/runs", response_model=RunCreated, status_code=201, tags=["runs"],
          summary="Start an assessment")
async def create_run(site: SiteInput) -> RunCreated:
    run_id = uuid.uuid4().hex[:12]
    name = site.name or f"Site @ {site.lat:.4f}, {site.lon:.4f}"
    db.create_run(run_id, datetime.now(timezone.utc).isoformat(), name, site.lat, site.lon, site.project_type)
    _events[run_id] = []
    task = asyncio.create_task(_execute(run_id, site))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return RunCreated(run_id=run_id)


@app.get("/runs", response_model=list[RunSummary], tags=["runs"],
         summary="List recent runs (newest first)")
async def list_runs(
    limit: int = Query(20, ge=1, le=100),
    ids: Optional[str] = Query(None, description="Comma-separated run ids; restricts the list to those runs."),
) -> list[dict[str, Any]]:
    # ids absent → list every run; ids present (even empty) → only those runs.
    wanted = None
    if ids is not None:
        wanted = [run_id.strip() for run_id in ids.split(",")[:100] if run_id.strip()]
    return db.list_runs(limit, wanted)


@app.get("/runs/{run_id}", response_model=RunDetail, tags=["runs"],
         summary="Fetch a run, with its report once complete",
         responses={404: {"description": "Run not found"}})
async def get_run(run_id: str) -> dict[str, Any]:
    run = db.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.get(
    "/runs/{run_id}/events",
    tags=["runs"],
    summary="Live progress (Server-Sent Events)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "A `text/event-stream` of PipelineEvent objects, ending with `complete` or `error`.",
            "content": {"text/event-stream": {"schema": PipelineEvent.model_json_schema()}},
        },
        404: {"description": "Run not found"},
    },
)
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
            # Never yield while holding the lock: a stalled client would block
            # the pipeline's _emit (which needs the same lock).
            timed_out = False
            async with cond:
                try:
                    await asyncio.wait_for(cond.wait(), timeout=30)
                except asyncio.TimeoutError:
                    timed_out = True
            if timed_out:
                yield ": keepalive\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/health", response_model=Health, tags=["ops"], summary="Liveness and configuration")
async def health() -> Health:
    return Health(status="ok", engine=llm.engine(), version=API_VERSION)
