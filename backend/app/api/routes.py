"""REST API.

Every endpoint here maps to a real Runtime method backed by real state —
there is no placeholder route that returns canned data. See
app.core.runtime.Runtime for the actual logic; this module is intentionally
thin.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from app.api.schemas_api import (
    ApprovalDecisionRequest, CreateAgentRequest, CreateMissionRequest,
    CreateScenarioRequest, InjectEventRequest, SetSpeedRequest,
    StartScenarioRequest, UpdateAgentRequest,
)
from app.core import persistence
from app.core.runtime import get_runtime
from app.core.schemas import AgentRole, ScenarioDefinition, TaskStatus
from app.scenarios.definitions import register_scenario

router = APIRouter()


# --------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------
@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/readiness")
async def readiness():
    rt = await get_runtime()
    return {"status": "ready", "agents_registered": len(rt.agents)}


# --------------------------------------------------------------------------
# agents
# --------------------------------------------------------------------------
@router.get("/agents")
async def list_agents():
    rt = await get_runtime()
    return rt.list_agent_statuses()


@router.post("/agents", status_code=201)
async def create_agent(body: CreateAgentRequest):
    rt = await get_runtime()
    status = await rt.add_agent(name=body.name, role=body.role, capabilities=body.capabilities,
                                 objective=body.objective)
    return status.model_dump(mode="json")


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    rt = await get_runtime()
    detail = rt.get_agent_detail(agent_id)
    if detail is None:
        raise HTTPException(404, "agent not found")
    return detail


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, body: UpdateAgentRequest):
    rt = await get_runtime()
    agent = rt.agents.get(agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    if body.objective is not None:
        agent.config.objective = body.objective
        agent.status.objective = body.objective
    if body.capabilities is not None:
        agent.config.capabilities = body.capabilities
    if body.enabled is not None:
        agent.config.enabled = body.enabled
    return agent.status.model_dump(mode="json")


@router.delete("/agents/{agent_id}")
async def remove_agent(agent_id: str):
    rt = await get_runtime()
    ok = await rt.remove_agent(agent_id)
    if not ok:
        raise HTTPException(404, "agent not found")
    return {"removed": agent_id}


@router.get("/agents/{agent_id}/events")
async def agent_events(agent_id: str, limit: int = 100):
    rt = await get_runtime()
    if agent_id not in rt.agents:
        raise HTTPException(404, "agent not found")
    decisions = await persistence.load_decisions(agent_id=agent_id, limit=limit)
    messages = [m.model_dump(mode="json") for m in rt.bus.history_for(agent_id, limit=limit)]
    return {"decisions": decisions, "messages": messages}


# --------------------------------------------------------------------------
# missions
# --------------------------------------------------------------------------
@router.get("/missions")
async def list_missions():
    rt = await get_runtime()
    return [m.model_dump(mode="json") for m in rt.missions.values()]


@router.post("/missions", status_code=201)
async def create_mission(body: CreateMissionRequest):
    rt = await get_runtime()
    mission = await rt.create_mission(name=body.name, goal=body.goal,
                                       scenario_key=body.scenario_key, priority=body.priority)
    return mission.model_dump(mode="json")


@router.get("/missions/{mission_id}")
async def get_mission(mission_id: str):
    rt = await get_runtime()
    report = rt.mission_report(mission_id)
    if report is None:
        raise HTTPException(404, "mission not found")
    return report


@router.post("/missions/{mission_id}/cancel")
async def cancel_mission(mission_id: str):
    rt = await get_runtime()
    mission = rt.missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    from app.core.schemas import MissionStatus
    mission.status = MissionStatus.CANCELLED
    for task in rt.tasks.values():
        if task.mission_id == mission_id and task.status in {TaskStatus.PENDING, TaskStatus.ASSIGNED,
                                                               TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED}:
            await rt.update_task_status(task.task_id, TaskStatus.CANCELLED, error="Mission cancelled")
    await persistence.save_mission(mission)
    return mission.model_dump(mode="json")


@router.post("/missions/{mission_id}/retry")
async def retry_mission(mission_id: str):
    rt = await get_runtime()
    mission = rt.missions.get(mission_id)
    if mission is None:
        raise HTTPException(404, "mission not found")
    retried = 0
    for task in rt.tasks.values():
        if task.mission_id == mission_id and task.status == TaskStatus.FAILED:
            task.retries = 0
            await rt.update_task_status(task.task_id, TaskStatus.PENDING, error=None)
            retried += 1
    from app.core.schemas import MissionStatus
    if retried:
        mission.status = MissionStatus.ACTIVE
        await persistence.save_mission(mission)
    return {"mission_id": mission_id, "tasks_reset": retried}


@router.get("/missions/{mission_id}/export")
async def export_mission(mission_id: str):
    rt = await get_runtime()
    report_json = await rt.export_mission_report(mission_id)
    if report_json is None:
        raise HTTPException(404, "mission not found")
    import json
    return json.loads(report_json)


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------
@router.get("/tasks")
async def list_tasks(mission_id: Optional[str] = None, status: Optional[TaskStatus] = None):
    rt = await get_runtime()
    tasks = list(rt.tasks.values())
    if mission_id:
        tasks = [t for t in tasks if t.mission_id == mission_id]
    if status:
        tasks = [t for t in tasks if t.status == status]
    return [t.model_dump(mode="json") for t in tasks]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str):
    rt = await get_runtime()
    task = rt.get_task(task_id)
    if task is None:
        raise HTTPException(404, "task not found")
    return task.model_dump(mode="json")


# --------------------------------------------------------------------------
# approvals (human-in-the-loop for high-impact actions)
# --------------------------------------------------------------------------
@router.get("/approvals")
async def list_approvals():
    rt = await get_runtime()
    return rt.list_pending_approvals()


@router.post("/approvals/{task_id}")
async def decide_approval(task_id: str, body: ApprovalDecisionRequest):
    rt = await get_runtime()
    coordinator_id = rt.get_agent_id(AgentRole.COORDINATOR)
    if coordinator_id is None:
        raise HTTPException(500, "no coordinator agent registered")
    coordinator = rt.agents[coordinator_id]
    if task_id not in rt.pending_approvals:
        raise HTTPException(404, "no pending approval for that task")
    await coordinator.authorize_pending(task_id, body.approve)
    return {"task_id": task_id, "approved": body.approve}


# --------------------------------------------------------------------------
# world state
# --------------------------------------------------------------------------
@router.get("/world")
async def get_world():
    rt = await get_runtime()
    return rt.world.snapshot()


@router.post("/world/events")
async def post_world_event(body: InjectEventRequest):
    rt = await get_runtime()
    return await rt.inject_manual_event(body.kind, body.description, body.entity_id, body.payload)


# --------------------------------------------------------------------------
# communications / decisions
# --------------------------------------------------------------------------
@router.get("/messages")
async def list_messages(agent_id: Optional[str] = None, mission_id: Optional[str] = None,
                         message_type: Optional[str] = None, limit: int = 300):
    rt = await get_runtime()
    if agent_id:
        msgs = rt.bus.history_for(agent_id, limit=limit)
    else:
        msgs = rt.bus.history(limit=limit)
    out = [m.model_dump(mode="json") for m in msgs]
    if mission_id:
        out = [m for m in out if m.get("mission_id") == mission_id]
    if message_type:
        out = [m for m in out if m.get("message_type") == message_type]
    return out


@router.get("/decisions")
async def list_decisions(agent_id: Optional[str] = None, mission_id: Optional[str] = None, limit: int = 200):
    return await persistence.load_decisions(mission_id=mission_id, agent_id=agent_id, limit=limit)


# --------------------------------------------------------------------------
# simulation control
# --------------------------------------------------------------------------
@router.post("/simulation/start")
async def start_simulation(body: StartScenarioRequest):
    rt = await get_runtime()
    try:
        return await rt.start_scenario(body.key)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.post("/simulation/pause")
async def pause_simulation():
    rt = await get_runtime()
    await rt.pause_simulation()
    return {"paused": True}


@router.post("/simulation/resume")
async def resume_simulation():
    rt = await get_runtime()
    await rt.resume_simulation()
    return {"paused": False}


@router.post("/simulation/step")
async def step_simulation():
    rt = await get_runtime()
    t = await rt.step_simulation()
    return {"sim_time": t}


@router.post("/simulation/speed")
async def set_speed(body: SetSpeedRequest):
    rt = await get_runtime()
    rt.set_speed(body.speed)
    return {"speed": rt.simulation.speed}


@router.post("/simulation/reset")
async def reset_simulation():
    rt = await get_runtime()
    await rt.reset_simulation()
    return {"reset": True}


@router.get("/simulation/summary")
async def simulation_summary():
    rt = await get_runtime()
    return rt.dashboard_summary()


# --------------------------------------------------------------------------
# scenarios
# --------------------------------------------------------------------------
@router.get("/scenarios")
async def list_scenarios():
    rt = await get_runtime()
    return await rt.list_scenarios()


@router.post("/scenarios", status_code=201)
async def create_scenario(body: CreateScenarioRequest):
    register_scenario(ScenarioDefinition(**body.model_dump()))
    return {"registered": body.key}
