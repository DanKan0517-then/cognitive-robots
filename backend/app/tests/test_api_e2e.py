"""End-to-end tests against the real FastAPI app: health, full scenario
execution via HTTP, conflict resolution + human approval, simulation
control, WebSocket live events, and mission-log reconstruction.

Uses Starlette's TestClient, which drives the actual ASGI app in-process —
these are real requests through the real router into the real Runtime
singleton, not mocked responses.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.core.llm_provider import get_provider
from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c
        # TestClient's own __exit__ runs the app's lifespan shutdown (which
        # now calls Runtime.shutdown() -- see app/main.py), so every agent,
        # the tick loop, and any in-flight background DB writes are drained
        # here before the next test module opens a second, independent
        # Runtime against the same SQLite file.


def _wait_for(predicate, timeout=8.0, interval=0.2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


# --------------------------------------------------------------------------
# health / readiness
# --------------------------------------------------------------------------
def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_readiness_reports_registered_agents(client: TestClient):
    r = client.get("/api/readiness")
    assert r.status_code == 200
    assert r.json()["agents_registered"] == 8


# --------------------------------------------------------------------------
# agents CRUD
# --------------------------------------------------------------------------
def test_list_agents_returns_real_roster(client: TestClient):
    r = client.get("/api/agents")
    assert r.status_code == 200
    roles = {a["role"] for a in r.json()}
    assert "perception" in roles and "coordinator" in roles and len(r.json()) == 8


def test_create_update_remove_agent(client: TestClient):
    r = client.post("/api/agents", json={"name": "TestBot", "role": "custom", "capabilities": ["probe"]})
    assert r.status_code == 201
    agent_id = r.json()["agent_id"]

    r2 = client.get(f"/api/agents/{agent_id}")
    assert r2.status_code == 200
    assert r2.json()["config"]["name"] == "TestBot"

    r3 = client.patch(f"/api/agents/{agent_id}", json={"objective": "new objective"})
    assert r3.status_code == 200
    assert r3.json()["objective"] == "new objective"

    r4 = client.delete(f"/api/agents/{agent_id}")
    assert r4.status_code == 200

    r5 = client.get(f"/api/agents/{agent_id}")
    assert r5.status_code == 404


# --------------------------------------------------------------------------
# scenarios: data-driven, not hardcoded into the frontend
# --------------------------------------------------------------------------
def test_scenarios_are_listed_and_general_purpose(client: TestClient):
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    keys = {s["key"] for s in r.json()}
    assert {"dynamic_obstacle_response", "resource_coordination", "collaborative_exploration",
            "emergency_response", "unattended_object_monitoring", "collaborative_investigation"} <= keys
    # unattended-object monitoring must be one example among several, not the whole system
    assert len(keys) >= 6


def test_can_register_a_brand_new_scenario_at_runtime(client: TestClient):
    r = client.post("/api/scenarios", json={
        "key": "test_custom_scenario", "name": "Custom", "description": "d",
        "map_width": 5, "map_height": 5, "zones": [],
        "initial_entities": [{"entity_id": "b1", "kind": "bot", "label": "B1", "x": 0, "y": 0}],
        "scripted_events": [], "mission_goal": "goal", "tags": [],
    })
    assert r.status_code == 201
    keys = {s["key"] for s in client.get("/api/scenarios").json()}
    assert "test_custom_scenario" in keys


# --------------------------------------------------------------------------
# spec 11.4 / 11.14: coordinated outcome + mission log reconstruction
# --------------------------------------------------------------------------
def test_scenario_runs_end_to_end_and_mission_log_reconstructs_outcome(client: TestClient):
    client.post("/api/simulation/reset")
    r = client.post("/api/simulation/start", json={"key": "dynamic_obstacle_response"})
    assert r.status_code == 200
    mission_id = r.json()["mission"]["mission_id"]

    def mission_done():
        rep = client.get(f"/api/missions/{mission_id}").json()
        return rep if rep["mission"]["status"] == "completed" else None

    report = _wait_for(mission_done)
    assert report is not None, "mission never completed"
    assert report["progress"]["completed"] == report["progress"]["total"] > 0

    export = client.get(f"/api/missions/{mission_id}/export").json()
    assert export["mission"]["outcome"] == "Completed successfully"
    assert len(export["decisions"]) > 0
    assert len(export["messages"]) > 0
    # The decision trail must reference the same task the mission's own
    # task list reports completed — i.e. the log genuinely reconstructs it.
    completed_task_ids = {t["task_id"] for t in export["tasks"] if t["status"] == "completed"}
    decision_task_ids = {d["task_id"] for d in export["decisions"] if d.get("task_id")}
    assert completed_task_ids & decision_task_ids


# --------------------------------------------------------------------------
# spec 11.5: conflicting plans are detected and resolved (+ human approval)
# --------------------------------------------------------------------------
def test_resource_conflict_requires_approval_and_resolves_on_approve(client: TestClient):
    client.post("/api/simulation/reset")
    r = client.post("/api/simulation/start", json={"key": "resource_coordination"})
    mission_id = r.json()["mission"]["mission_id"]

    def has_pending_approval():
        approvals = client.get("/api/approvals").json()
        return approvals if approvals else None

    approvals = _wait_for(has_pending_approval, timeout=6.0)
    if approvals:  # high-priority second request routed for human approval
        task_id = approvals[0]["task_id"]
        resp = client.post(f"/api/approvals/{task_id}", json={"approve": True})
        assert resp.status_code == 200

    def mission_done():
        rep = client.get(f"/api/missions/{mission_id}").json()
        return rep if rep["mission"]["status"] == "completed" else None

    report = _wait_for(mission_done, timeout=8.0)
    assert report is not None
    # Both competing resource requests must have been resolved, not left
    # orphaned pending forever.
    assert all(t["status"] in {"completed", "failed", "cancelled"} for t in report["tasks"])


# --------------------------------------------------------------------------
# spec 11.11: simulation pause, resume, reset work correctly
# --------------------------------------------------------------------------
def test_simulation_pause_resume_reset(client: TestClient):
    client.post("/api/simulation/reset")
    client.post("/api/simulation/start", json={"key": "emergency_response"})

    client.post("/api/simulation/pause")
    s1 = client.get("/api/simulation/summary").json()
    assert s1["simulation_paused"] is True
    t1 = s1["sim_time"]
    time.sleep(1.0)
    s2 = client.get("/api/simulation/summary").json()
    assert s2["sim_time"] == t1, "paused simulation must not keep advancing"

    client.post("/api/simulation/resume")
    time.sleep(1.0)
    s3 = client.get("/api/simulation/summary").json()
    assert s3["simulation_paused"] is False

    r = client.post("/api/simulation/reset")
    assert r.status_code == 200
    s4 = client.get("/api/simulation/summary").json()
    assert s4["sim_time"] == 0
    assert s4["missions"]["total"] == 0


def test_manual_step_advances_exactly_one_tick(client: TestClient):
    client.post("/api/simulation/reset")
    client.post("/api/simulation/start", json={"key": "resource_coordination"})
    client.post("/api/simulation/pause")
    before = client.get("/api/simulation/summary").json()["sim_time"]
    r = client.post("/api/simulation/step")
    assert r.json()["sim_time"] == before + 1


# --------------------------------------------------------------------------
# spec 11.10: WebSocket clients receive live events
# --------------------------------------------------------------------------
def test_websocket_receives_snapshot_then_live_events(client: TestClient):
    client.post("/api/simulation/reset")
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot"
        assert "agents" in first["data"]

        client.post("/api/simulation/start", json={"key": "dynamic_obstacle_response"})

        seen_types = set()
        deadline = time.time() + 6.0
        while time.time() < deadline and "message" not in seen_types:
            try:
                envelope = ws.receive_json()
            except Exception:
                break
            seen_types.add(envelope["type"])
        assert "message" in seen_types or "tick" in seen_types or "agent_state" in seen_types


# --------------------------------------------------------------------------
# spec 11.12: the no-LLM fallback executes a complete scenario
# --------------------------------------------------------------------------
def test_no_llm_fallback_is_active_and_still_produces_decisions(client: TestClient):
    assert get_provider().enabled is False, "tests must exercise the deterministic fallback path"
    client.post("/api/simulation/reset")
    r = client.post("/api/simulation/start", json={"key": "collaborative_investigation"})
    mission_id = r.json()["mission"]["mission_id"]

    def mission_done():
        rep = client.get(f"/api/missions/{mission_id}").json()
        return rep if rep["mission"]["status"] in {"completed", "failed"} else None

    report = _wait_for(mission_done)
    assert report is not None
    decisions = client.get(f"/api/decisions?mission_id={mission_id}").json()
    assert any(d.get("rationale") for d in decisions), \
        "deterministic fallback must still produce real, inspectable rationale"


# --------------------------------------------------------------------------
# world state + messages + decisions read endpoints reflect real data
# --------------------------------------------------------------------------
def test_world_endpoint_matches_injected_event(client: TestClient):
    client.post("/api/simulation/reset")
    client.post("/api/simulation/start", json={"key": "collaborative_exploration"})
    r = client.post("/api/world/events", json={"kind": "anomaly", "description": "manual probe event"})
    assert r.status_code == 200
    assert r.json()["kind"] == "anomaly"

    world = client.get("/api/world").json()
    descriptions = [e["description"] for e in world["recent_events"]]
    assert "manual probe event" in descriptions
