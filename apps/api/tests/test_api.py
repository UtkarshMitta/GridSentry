"""HTTP API: run lifecycle, SSE stream, persistence, validation."""
from __future__ import annotations

import json
import time

import pytest
from conftest import developable_status, jur, wetland
from fastapi.testclient import TestClient

import db
import geodata
import grounding
import land_status


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
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["version"]
    assert body["engine"] == "deterministic"   # no keys in the test env


def test_run_list_is_typed_and_limited(client):
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    wait_complete(client, run_id)
    [row] = client.get("/runs", params={"limit": 1}).json()
    assert row["id"] == run_id and row["status"] == "complete"
    assert row["risk_level"] in ("high", "moderate", "low") and isinstance(row["risk_score"], int)
    assert "gis" not in row and "events" not in row     # summary rows stay small
    assert client.get("/runs", params={"limit": 0}).status_code == 422


def test_openapi_documents_the_report_shape(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"RunDetail", "RunSummary", "Report", "LandStatus", "PipelineEvent"} <= set(schemas)
    assert "designation_code" in schemas["LandStatus"]["properties"]


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


def test_run_list_exposes_the_verdict(client, monkeypatch):
    """History rows distinguish a gated 'not viable' run from a scored one."""
    import land_status
    from models import LandStatus

    async def gated(lat, lon, acreage=300.0):
        return LandStatus(developable=False, category="federal_protected", manager_code="NPS",
                          unit_name="Grand Canyon National Park", designation="National Park",
                          designation_code="NP", verified=True, method="padus")

    monkeypatch.setattr(land_status, "check", gated)
    run_id = client.post("/runs", json={"lat": 36.2, "lon": -111.9}).json()["run_id"]
    wait_complete(client, run_id)
    row = next(r for r in client.get("/runs").json() if r["id"] == run_id)
    assert row["verdict"] == "not_viable"


def test_run_detail_does_not_duplicate_report_fields(client):
    """Detail rows carry the report itself; a second (unset) copy of the verdict
    on the envelope would contradict it."""
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    run = wait_complete(client, run_id)
    assert "verdict" not in run and "risk_level" not in run
    assert run["report"]["verdict"] == "assessed"


def test_run_list_can_be_restricted_to_given_ids(client):
    """The public demo shares one database; the UI asks only for its own runs."""
    mine = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    someone_else = client.post("/runs", json={"lat": 38.5, "lon": -98.5}).json()["run_id"]
    wait_complete(client, mine)
    wait_complete(client, someone_else)
    rows = client.get("/runs", params={"ids": mine}).json()
    assert [r["id"] for r in rows] == [mine]
    assert client.get("/runs", params={"ids": ""}).json() == []
    assert len(client.get("/runs").json()) == 2   # unfiltered still lists everything


def test_completed_run_is_renamed_to_the_resolved_site_name(client):
    """History rows should read like the report, not 'Site @ 42.9, -74.3'."""
    run_id = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    run = wait_complete(client, run_id)
    assert run["name"] == run["gis"]["site"]["name"]
    assert not run["name"].startswith("Site @")


def test_ids_filter_tolerates_spaces_and_blanks(client):
    mine = client.post("/runs", json={"lat": 42.9, "lon": -74.3}).json()["run_id"]
    wait_complete(client, mine)
    rows = client.get("/runs", params={"ids": f" {mine} , ,"}).json()
    assert [r["id"] for r in rows] == [mine]


def test_blank_allowed_origins_does_not_block_every_origin(monkeypatch):
    """An empty env var means 'unset' — not 'allow no origin at all'."""
    import importlib

    import main

    monkeypatch.setenv("ALLOWED_ORIGINS", "  ")
    assert importlib.reload(main)._origins == ["*"]
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example, https://b.example")
    assert importlib.reload(main)._origins == ["https://a.example", "https://b.example"]
    monkeypatch.delenv("ALLOWED_ORIGINS")
    importlib.reload(main)
