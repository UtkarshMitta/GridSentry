"""HTTP API: run lifecycle, SSE stream, persistence, validation."""
from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import db
import geodata
import grounding
import land_status
from conftest import developable_status, jur, wetland


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(db, "_conn", None)

    async def fake_jur(lat, lon):
        return jur()

    async def fake_check(lat, lon, acreage=300.0):
        return developable_status()

    async def fake_fetch(lat, lon, acreage, state_code=None):
        return {"wetlands": [wetland()], "habitats": [], "flood_zones": [], "protected_lands": [],
                "provenance": {"wetlands": "live", "species": "live", "flood": "live", "protected": "live"}}

    monkeypatch.setattr(grounding, "resolve_jurisdiction", fake_jur)
    monkeypatch.setattr(land_status, "check", fake_check)
    monkeypatch.setattr(geodata, "fetch_all", fake_fetch)

    import main

    with TestClient(main.app) as c:
        yield c


def wait_complete(client, run_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def sse_events(client, run_id):
    events = []
    with client.stream("GET", f"/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
                if events[-1]["type"] in ("complete", "error"):
                    break
    return events


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_full_run_lifecycle(client):
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3, "project_type": "solar", "acreage": 120}).json()["run_id"]
    events = sse_events(client, run_id)
    assert events[-1]["type"] == "complete"
    assert {e.get("agent") for e in events} >= {"system", "geolocation", "legal", "critic"}
    run = wait_complete(client, run_id)
    assert run["status"] == "complete"
    assert run["report"]["risk_level"] in ("high", "moderate", "low")
    assert run["gis"]["site"]["acreage"] == 120
    listed = client.get("/runs").json()
    assert listed[0]["id"] == run_id and listed[0]["risk_level"] == run["report"]["risk_level"]


def test_sse_replays_after_completion(client):
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    wait_complete(client, run_id)
    events = sse_events(client, run_id)
    assert events[-1]["type"] == "complete" and len(events) > 5


@pytest.mark.parametrize("body", [
    {"lat": 91, "lon": 0}, {"lat": 0, "lon": 181}, {"lat": 0, "lon": 0, "project_type": "coal"},
    {"lat": 0, "lon": 0, "acreage": 0}, {"lat": 0, "lon": 0, "acreage": -5}, {"lat": 0, "lon": 0, "acreage": 0.04},
])
def test_invalid_input_rejected(client, body):
    assert client.post("/runs", json=body).status_code == 422


def test_unknown_run_404(client):
    assert client.get("/runs/nope").status_code == 404
    assert client.get("/runs/nope/events").status_code == 404


def test_orphaned_running_run_terminates_stream(client):
    """A run left 'running' by a previous process must not hang the SSE stream."""
    db.create_run("orphan", "2026-01-01T00:00:00+00:00", "x", 1.0, 1.0, "solar")
    events = sse_events(client, "orphan")
    assert events[-1]["type"] == "error"
    assert client.get("/runs/orphan").json()["status"] == "error"


def test_pipeline_exception_surfaces_as_error(client, monkeypatch):
    async def boom(lat, lon, acreage, state_code=None):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(geodata, "fetch_all", boom)
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    events = sse_events(client, run_id)
    assert events[-1]["type"] == "error" and "kaboom" in events[-1]["message"]
    assert wait_complete(client, run_id)["status"] == "error"


def test_persistence_failure_surfaces_as_error_not_complete(client, monkeypatch):
    """If saving the finished run fails, subscribers must get an error promptly —
    not hang, and not a 'complete' for a run that was never stored."""
    real_update = db.update_run

    def failing_update(run_id, **fields):
        if fields.get("status") in ("complete", "error"):
            raise db.sqlite3.OperationalError("attempt to write a readonly database")
        return real_update(run_id, **fields)

    monkeypatch.setattr(db, "update_run", failing_update)
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    events = sse_events(client, run_id)
    assert events[-1]["type"] == "error"
    assert not any(e["type"] == "complete" for e in events)
