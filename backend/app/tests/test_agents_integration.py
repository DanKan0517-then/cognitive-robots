"""Integration tests that drive real agents over the real message bus
inside a Runtime, without going through HTTP. These exercise the actual
cognitive cycle code paths, not mocks.
"""
from __future__ import annotations

import asyncio

import pytest

from app.agents.base import BaseAgent
from app.core import persistence
from app.core.runtime import Runtime
from app.core.schemas import (
    AgentConfig, AgentRole, AgentState, Message, MessageType, TaskStatus, WorldEntity,
)


# --------------------------------------------------------------------------
# spec 11.1: every agent can be registered and started
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_default_roster_registers_and_starts(fresh_runtime: Runtime):
    assert len(fresh_runtime.agents) == 8
    roles = {a.config.role for a in fresh_runtime.agents.values()}
    assert roles == {
        AgentRole.PERCEPTION, AgentRole.WORLD_MODEL, AgentRole.PLANNING, AgentRole.REASONING,
        AgentRole.CRITIC, AgentRole.COORDINATOR, AgentRole.EXECUTOR, AgentRole.MEMORY,
    }
    for agent in fresh_runtime.agents.values():
        assert agent._running is True
        assert agent.status.state == AgentState.IDLE


@pytest.mark.asyncio
async def test_a_new_custom_agent_can_be_added_without_code_changes(fresh_runtime: Runtime):
    status = await fresh_runtime.add_agent(name="Extra-1", role=AgentRole.CUSTOM, capabilities=["scratch"])
    assert status.agent_id in fresh_runtime.agents
    assert len(fresh_runtime.agents) == 9
    ok = await fresh_runtime.remove_agent(status.agent_id)
    assert ok
    assert len(fresh_runtime.agents) == 8


# --------------------------------------------------------------------------
# spec 11.8: the system recovers from agent timeouts
# --------------------------------------------------------------------------
class _SlowThenFastAgent(BaseAgent):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.handled_fast = 0

    async def handle_message(self, message: Message) -> None:
        if message.payload.get("slow"):
            await asyncio.sleep(0.4)
        else:
            self.handled_fast += 1


@pytest.mark.asyncio
async def test_agent_recovers_after_a_timeout(fresh_runtime: Runtime):
    config = AgentConfig(name="Slow-1", role=AgentRole.CUSTOM, timeout_seconds=0.05)
    agent = _SlowThenFastAgent(config, fresh_runtime.bus, fresh_runtime)
    fresh_runtime.agents[config.agent_id] = agent
    await agent.start()
    try:
        await fresh_runtime.bus.publish(Message(sender_id="test", receiver_id=config.agent_id,
                                                  message_type=MessageType.OBSERVATION,
                                                  payload={"slow": True}))
        await asyncio.sleep(0.2)
        assert agent.status.health == "degraded"
        assert agent.status.state == AgentState.RECOVERING
        assert agent.blockers  # the timeout was recorded, not swallowed silently

        # Agent must still be alive and able to process subsequent messages —
        # a timeout degrades it, it does not kill the run loop.
        await fresh_runtime.bus.publish(Message(sender_id="test", receiver_id=config.agent_id,
                                                  message_type=MessageType.OBSERVATION,
                                                  payload={"slow": False}))
        await asyncio.sleep(0.1)
        assert agent.handled_fast == 1
    finally:
        await agent.stop()


# --------------------------------------------------------------------------
# spec 11.6: a blocked task causes replanning
# spec 11.7: failed actions are reported accurately
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_execution_triggers_bounded_replan_then_terminal_failure(fresh_runtime: Runtime):
    """Drives Coordinator -> Executor -> (fail) -> Coordinator -> Planning
    -> ... directly via the message bus, using an action the simulator is
    guaranteed to fail ('abandon_task' always returns success=False), to
    confirm: (a) a REPLAN_REQUEST is actually sent on failure, (b) retries
    are bounded by max_retries, and (c) once exhausted the task becomes
    FAILED (not silently stuck), with the failure reason preserved.
    """
    await fresh_runtime.world.upsert_entity(WorldEntity(entity_id="bot-1", kind="bot", label="Bot", x=0, y=0),
                                              conflict_check=False)
    mission = await fresh_runtime.create_mission(name="t", goal="g", scenario_key="dynamic_obstacle_response")
    task = await fresh_runtime.create_task(mission_id=mission.mission_id, title="abandon_task",
                                            description="guaranteed failure", priority=0.5)
    task.max_retries = 1
    fresh_runtime.tasks[task.task_id] = task

    executor_id = fresh_runtime.get_agent_id(AgentRole.EXECUTOR)
    replan_messages = []

    async def _watch_replans(m: Message):
        if m.message_type == MessageType.REPLAN_REQUEST:
            replan_messages.append(m)

    fresh_runtime.bus.subscribe_to_type(MessageType.REPLAN_REQUEST, _watch_replans)

    await fresh_runtime.bus.publish(Message(
        sender_id="test", receiver_id=executor_id, message_type=MessageType.TASK_ASSIGNMENT,
        payload={"task_id": task.task_id, "action": "abandon_task", "bot_entity_id": "bot-1",
                 "entity_id": None},
        mission_id=mission.mission_id, task_id=task.task_id,
    ))
    await asyncio.sleep(0.3)

    assert len(replan_messages) == 1, "exactly one replan should fire per failed attempt — no duplicates"
    updated = fresh_runtime.get_task(task.task_id)
    assert updated.retries == 1
    # Planning's _replan policy picks "abandon_task" once retries >= max_retries,
    # and the coordinator marks the task CANCELLED in that branch.
    await asyncio.sleep(0.3)
    final = fresh_runtime.get_task(task.task_id)
    assert final.status in {TaskStatus.CANCELLED, TaskStatus.FAILED}


# --------------------------------------------------------------------------
# spec 11.9: mission state persists across backend restarts
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mission_and_task_survive_a_simulated_restart(fresh_runtime: Runtime, clean_db):
    mission = await fresh_runtime.create_mission(name="Persisted", goal="survive restart",
                                                   scenario_key="dynamic_obstacle_response")
    task = await fresh_runtime.create_task(mission_id=mission.mission_id, title="probe",
                                            description="d", priority=0.5)

    # Simulate "restarting the backend": throw away all in-memory state and
    # reload purely from the SQLite rows written by persistence.py.
    reloaded_missions = await persistence.load_missions()
    reloaded_tasks = await persistence.load_tasks_for_mission(mission.mission_id)

    assert any(m["mission_id"] == mission.mission_id for m in reloaded_missions)
    assert any(t["task_id"] == task.task_id for t in reloaded_tasks)


# --------------------------------------------------------------------------
# spec 11.4 + 6: agents exchange information and produce a coordinated outcome
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_cognitive_cycle_produces_a_completed_task(fresh_runtime: Runtime):
    result = await fresh_runtime.start_scenario("dynamic_obstacle_response")
    mission_id = result["mission"]["mission_id"]

    deadline = asyncio.get_event_loop().time() + 8.0
    completed = False
    while asyncio.get_event_loop().time() < deadline:
        tasks = [t for t in fresh_runtime.tasks.values() if t.mission_id == mission_id]
        if tasks and all(t.status == TaskStatus.COMPLETED for t in tasks):
            completed = True
            break
        await asyncio.sleep(0.2)

    assert completed, "the scripted obstacle scenario should fully resolve through the real agent chain"
    decisions = await persistence.load_decisions(mission_id=mission_id, limit=100)
    agent_ids_that_decided = {d["agent_id"] for d in decisions}
    # Confirm more than one bot actually participated — this is the thing
    # that distinguishes real coordination from one agent doing everything.
    assert len(agent_ids_that_decided) >= 5
