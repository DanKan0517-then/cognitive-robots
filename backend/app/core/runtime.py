"""Runtime: wires the message bus, world model, simulation engine, agent
registry, mission/task state machine and WebSocket event fan-out together.

This is the one object the API layer talks to. Every control in the
dashboard (start/pause/reset, inject event, approve/reject, add/remove
agent, switch scenario, export report) maps to a method here, and every
method here is backed by real state changes — nothing is decorative.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from app.agents import AGENT_CLASS_REGISTRY
from app.agents.base import BaseAgent
from app.core import persistence
from app.core.message_bus import MessageBus
from app.core.schemas import (
    AgentConfig, AgentRole, AgentStatus, DecisionRecord, Message, MessageType,
    Mission, MissionStatus, Task, TaskStatus, WorldEntity, WorldEvent, new_id, utcnow,
)
from app.core.simulation import SimulationEngine
from app.core.world_model import WorldModel
from app.scenarios.definitions import get_scenario, list_scenarios

logger = logging.getLogger("runtime")

DEFAULT_ROSTER = [
    ("Perception-1", AgentRole.PERCEPTION, ["camera_sim", "event_ingest"]),
    ("WorldModel-1", AgentRole.WORLD_MODEL, ["state_tracking"]),
    ("Planning-1", AgentRole.PLANNING, ["task_decomposition"]),
    ("Reasoning-1", AgentRole.REASONING, ["hypothesis_generation"]),
    ("Critic-1", AgentRole.CRITIC, ["plan_review"]),
    ("Coordinator-1", AgentRole.COORDINATOR, ["task_allocation", "conflict_resolution"]),
    ("Executor-1", AgentRole.EXECUTOR, ["action_execution"]),
    ("Memory-1", AgentRole.MEMORY, ["episodic_memory", "retrieval"]),
]


class ConnectionManager:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def register(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._queues.append(q)
        return q

    def unregister(self, q: asyncio.Queue) -> None:
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        envelope = {"type": event_type, "data": data}
        for q in list(self._queues):
            try:
                q.put_nowait(envelope)
            except asyncio.QueueFull:
                logger.warning("Dropping WS event for a slow client (queue full)")


class Runtime:
    def __init__(self):
        self.world = WorldModel()
        self.bus = MessageBus(on_message=self._on_message)
        self.simulation = SimulationEngine(self.world)
        self.agents: dict[str, BaseAgent] = {}
        self.missions: dict[str, Mission] = {}
        self.tasks: dict[str, Task] = {}
        self.pending_approvals: dict[str, dict[str, Any]] = {}
        self.connections = ConnectionManager()
        self.active_scenario_key: Optional[str] = None
        self._active_mission_id: Optional[str] = None
        self._lock = asyncio.Lock()
        # notify_* below fire persistence writes + WS broadcasts as detached
        # background tasks (so agent code calling them stays sync). Detached
        # means untracked: nothing awaits them, so on shutdown the event loop
        # can close with a decision/message write still in flight, which
        # intermittently surfaced as "database is locked" / "Event loop is
        # closed" under concurrent test load. Tracking them here lets
        # shutdown() drain every in-flight write before the DB engine and
        # connection manager go away, instead of abandoning them.
        self._background_tasks: set[asyncio.Task] = set()

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    # ------------------------------------------------------------------
    # startup / shutdown
    # ------------------------------------------------------------------
    async def init(self) -> None:
        await persistence.init_db()
        for name, role, caps in DEFAULT_ROSTER:
            await self.add_agent(name=name, role=role, capabilities=caps, objective=f"Serve as the {role.value} bot")

    async def shutdown(self) -> None:
        """Stop the simulation and every agent, then wait for any in-flight
        background persistence/broadcast tasks to finish (or be cancelled)
        before the caller tears down the DB engine or the event loop."""
        await self.simulation.stop()
        for agent in list(self.agents.values()):
            await agent.stop()
        pending = list(self._background_tasks)
        for task in pending:
            if not task.done():
                task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def add_agent(self, *, name: str, role: AgentRole, capabilities: list[str],
                         objective: str = "", agent_id: Optional[str] = None) -> AgentStatus:
        cls = AGENT_CLASS_REGISTRY.get(role, BaseAgent)
        config = AgentConfig(agent_id=agent_id or new_id("agent"), name=name, role=role,
                              capabilities=capabilities, objective=objective)
        agent = cls(config, self.bus, self)
        self.agents[config.agent_id] = agent
        await agent.start()
        await self.connections.broadcast("agent_added", agent.status.model_dump(mode="json"))
        return agent.status

    async def remove_agent(self, agent_id: str) -> bool:
        agent = self.agents.pop(agent_id, None)
        if agent is None:
            return False
        await agent.stop()
        await self.connections.broadcast("agent_removed", {"agent_id": agent_id})
        return True

    def get_agent_id(self, role: AgentRole) -> Optional[str]:
        for agent in self.agents.values():
            if agent.config.role == role and agent.config.enabled:
                return agent.config.agent_id
        return None

    def list_agent_statuses(self) -> list[dict[str, Any]]:
        return [a.status.model_dump(mode="json") for a in self.agents.values()]

    def get_agent_detail(self, agent_id: str) -> Optional[dict[str, Any]]:
        agent = self.agents.get(agent_id)
        if agent is None:
            return None
        return {
            "status": agent.status.model_dump(mode="json"),
            "config": agent.config.model_dump(mode="json"),
            "recent_observations": agent.recent_observations[-20:],
            "recent_decisions": [d.model_dump(mode="json") for d in agent.recent_decisions[-20:]],
            "recent_messages": [m.model_dump(mode="json") for m in agent.recent_messages[-30:]],
            "blockers": agent.blockers[-10:],
        }

    # ------------------------------------------------------------------
    # message bus hook: persist + broadcast every message
    # ------------------------------------------------------------------
    async def _on_message(self, message: Message) -> None:
        try:
            await persistence.save_message(message)
        except Exception:
            logger.exception("Failed to persist message %s", message.message_id)
        await self.connections.broadcast("message", message.model_dump(mode="json"))

    def notify_agent_state_change(self, status: AgentStatus) -> None:
        self._spawn(self.connections.broadcast("agent_state", status.model_dump(mode="json")))

    def notify_decision(self, decision: DecisionRecord) -> None:
        async def _go():
            try:
                await persistence.save_decision(decision)
            except Exception:
                logger.exception("Failed to persist decision %s", decision.decision_id)
            await self.connections.broadcast("decision", decision.model_dump(mode="json"))
        self._spawn(_go())

    def notify_world_update(self) -> None:
        self._spawn(self.connections.broadcast("world_update", self.world.snapshot()))

    def notify_mission_progress(self, mission_id: Optional[str]) -> None:
        if not mission_id:
            return
        self._spawn(self.connections.broadcast("mission_progress", self.mission_report(mission_id) or {}))

    # ------------------------------------------------------------------
    # mission / task state machine
    # ------------------------------------------------------------------
    def active_mission_goal(self, mission_id: Optional[str]) -> Optional[str]:
        if mission_id and mission_id in self.missions:
            return self.missions[mission_id].goal
        if self._active_mission_id:
            return self.missions[self._active_mission_id].goal
        return None

    async def create_mission(self, name: str, goal: str, scenario_key: str, priority: float = 0.5) -> Mission:
        mission = Mission(name=name, goal=goal, scenario_key=scenario_key, status=MissionStatus.ACTIVE,
                           priority=priority)
        self.missions[mission.mission_id] = mission
        self._active_mission_id = mission.mission_id
        await persistence.save_mission(mission)
        await self.connections.broadcast("mission_created", mission.model_dump(mode="json"))
        return mission

    async def create_task(self, *, mission_id: str, title: str, description: str, priority: float,
                           target_entity_id: Optional[str] = None) -> Task:
        task = Task(mission_id=mission_id, title=title, description=description, priority=priority,
                    target_entity_id=target_entity_id)
        self.tasks[task.task_id] = task
        mission = self.missions.get(mission_id)
        if mission:
            mission.task_ids.append(task.task_id)
            mission.updated_at = utcnow()
            if mission.status == MissionStatus.COMPLETED:
                # A scripted event fired a new task after the mission had
                # already closed out its earlier tasks (e.g. a second
                # resource request arriving a tick after the first was
                # resolved). The mission is genuinely not done yet, so
                # reopen it rather than letting this task orphan silently.
                mission.status = MissionStatus.ACTIVE
                mission.outcome = None
            await persistence.save_mission(mission)
        await persistence.save_task(task)
        await self.connections.broadcast("task_created", task.model_dump(mode="json"))
        return task

    def get_task(self, task_id: Optional[str]) -> Optional[Task]:
        if not task_id:
            return None
        return self.tasks.get(task_id)

    async def update_task_status(self, task_id: str, status: TaskStatus, *, assigned_agent_id: Optional[str] = None,
                                  result: Optional[dict[str, Any]] = None, error: Optional[str] = None) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            return
        task.status = status
        task.updated_at = utcnow()
        if assigned_agent_id:
            task.assigned_agent_id = assigned_agent_id
        if result is not None:
            task.result = result
        if error is not None:
            task.error = error
        await persistence.save_task(task)
        await self.connections.broadcast("task_updated", task.model_dump(mode="json"))
        if status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}:
            await self._maybe_complete_mission(task.mission_id)

    async def increment_task_retry(self, task_id: str) -> None:
        task = self.tasks.get(task_id)
        if task is None:
            return
        task.retries += 1
        await persistence.save_task(task)

    async def _maybe_complete_mission(self, mission_id: str) -> None:
        mission = self.missions.get(mission_id)
        if mission is None or mission.status != MissionStatus.ACTIVE:
            return
        tasks = [t for t in self.tasks.values() if t.mission_id == mission_id]
        if tasks and all(t.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED} for t in tasks):
            any_failed = any(t.status == TaskStatus.FAILED for t in tasks)
            mission.status = MissionStatus.COMPLETED
            mission.outcome = "Completed with some failed tasks" if any_failed else "Completed successfully"
            mission.updated_at = utcnow()
            await persistence.save_mission(mission)
            await self.connections.broadcast("mission_completed", mission.model_dump(mode="json"))

    def find_conflicting_active_task(self, task: Task) -> Optional[str]:
        if not task.target_entity_id:
            return None
        for other in self.tasks.values():
            if other.task_id == task.task_id:
                continue
            if other.target_entity_id == task.target_entity_id and \
               other.status in {TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS}:
                return other.task_id
        return None

    def pick_executor_bot(self) -> Optional[str]:
        bots = self.simulation.pick_patrol_bots()
        if not bots:
            return None
        idle = [b for b in bots if b.attributes.get("status") not in {"investigating", "patrolling"}]
        return (idle[0] if idle else bots[0]).entity_id

    def queue_for_approval(self, task_id: str, payload: dict[str, Any]) -> None:
        self.pending_approvals[task_id] = payload
        self._spawn(self.connections.broadcast("approval_requested",
                                                         {"task_id": task_id, **payload}))

    def pop_pending_approval(self, task_id: str) -> Optional[dict[str, Any]]:
        return self.pending_approvals.pop(task_id, None)

    def list_pending_approvals(self) -> list[dict[str, Any]]:
        return [{"task_id": k, **v} for k, v in self.pending_approvals.items()]

    # ------------------------------------------------------------------
    # scenarios / simulation control
    # ------------------------------------------------------------------
    async def list_scenarios(self) -> list[dict[str, Any]]:
        return [s.model_dump(mode="json") for s in list_scenarios()]

    async def start_scenario(self, key: str) -> dict[str, Any]:
        scenario = get_scenario(key)
        if scenario is None:
            raise ValueError(f"Unknown scenario '{key}'")

        await self.simulation.stop()
        await self.world.reset(scenario.map_width, scenario.map_height)
        self.pending_approvals.clear()
        self.tasks.clear()
        for agent in self.agents.values():
            agent.reset_episodic_state()

        for zone in scenario.zones:
            await self.world.set_zone(zone["zone_id"], zone)
        for ent in scenario.initial_entities:
            entity = WorldEntity(**ent)
            await self.world.upsert_entity(entity, conflict_check=False)

        mission = await self.create_mission(name=scenario.name, goal=scenario.mission_goal,
                                             scenario_key=key, priority=0.6)
        self.active_scenario_key = key

        async def emit_event(evt: WorldEvent) -> None:
            perception_id = self.get_agent_id(AgentRole.PERCEPTION)
            if not perception_id:
                return
            entity_id = evt.payload.get("entity_id")
            msg = Message(
                sender_id="simulator", receiver_id=perception_id, message_type=MessageType.EVENT_NOTICE,
                payload={"kind": evt.kind, "description": evt.description, "entity_id": entity_id,
                         "x": self.world.get_entity(entity_id).x if entity_id and self.world.get_entity(entity_id) else None,
                         "y": self.world.get_entity(entity_id).y if entity_id and self.world.get_entity(entity_id) else None,
                         "entity_kind": self.world.get_entity(entity_id).kind if entity_id and self.world.get_entity(entity_id) else None,
                         "zone_id": self.world.get_entity(entity_id).zone_id if entity_id and self.world.get_entity(entity_id) else None},
                mission_id=mission.mission_id,
            )
            await self.bus.publish(msg)

        async def on_tick(t: int) -> None:
            await self.connections.broadcast("tick", {"sim_time": t})
            self.notify_world_update()

        self.simulation.configure(scenario.scripted_events, emit_event, on_tick)
        await self.simulation.start()

        return {"mission": mission.model_dump(mode="json"), "world": self.world.snapshot()}

    async def pause_simulation(self) -> None:
        await self.simulation.pause()

    async def resume_simulation(self) -> None:
        await self.simulation.resume()

    async def step_simulation(self) -> int:
        return await self.simulation.step()

    def set_speed(self, speed: float) -> None:
        self.simulation.set_speed(speed)

    async def reset_simulation(self) -> None:
        await self.simulation.stop()
        await self.world.reset()
        self.missions.clear()
        self.tasks.clear()
        self.pending_approvals.clear()
        self.bus.clear()
        for agent in self.agents.values():
            agent.reset_episodic_state()
        self.active_scenario_key = None
        self._active_mission_id = None
        await persistence.reset_all()
        await self.connections.broadcast("simulation_reset", {})

    async def inject_manual_event(self, kind: str, description: str, entity_id: Optional[str] = None,
                                   payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        evt = await self.simulation.inject_event(kind, description, entity_id, payload)
        perception_id = self.get_agent_id(AgentRole.PERCEPTION)
        if perception_id:
            ent = self.world.get_entity(entity_id) if entity_id else None
            msg = Message(
                sender_id="operator", receiver_id=perception_id, message_type=MessageType.EVENT_NOTICE,
                payload={"kind": kind, "description": description, "entity_id": entity_id,
                         "x": ent.x if ent else None, "y": ent.y if ent else None,
                         "entity_kind": ent.kind if ent else None, "zone_id": ent.zone_id if ent else None},
                mission_id=self._active_mission_id,
            )
            await self.bus.publish(msg)
        return evt.model_dump(mode="json")

    # ------------------------------------------------------------------
    # reporting
    # ------------------------------------------------------------------
    def mission_report(self, mission_id: str) -> Optional[dict[str, Any]]:
        mission = self.missions.get(mission_id)
        if mission is None:
            return None
        tasks = [t.model_dump(mode="json") for t in self.tasks.values() if t.mission_id == mission_id]
        done = sum(1 for t in self.tasks.values() if t.mission_id == mission_id
                   and t.status == TaskStatus.COMPLETED)
        total = sum(1 for t in self.tasks.values() if t.mission_id == mission_id)
        return {
            "mission": mission.model_dump(mode="json"),
            "tasks": tasks,
            "progress": {"completed": done, "total": total},
        }

    async def export_mission_report(self, mission_id: str) -> Optional[str]:
        report = self.mission_report(mission_id)
        if report is None:
            return None
        messages = await persistence.load_messages(mission_id=mission_id, limit=1000)
        decisions = await persistence.load_decisions(mission_id=mission_id, limit=1000)
        report["messages"] = messages
        report["decisions"] = decisions
        return json.dumps(report, indent=2, default=str)

    def dashboard_summary(self) -> dict[str, Any]:
        statuses = [a.status for a in self.agents.values()]
        active_missions = [m for m in self.missions.values() if m.status == MissionStatus.ACTIVE]
        return {
            "agents": {
                "total": len(statuses),
                "active": sum(1 for s in statuses if s.state not in {"idle", "stopped", "failed"}),
                "idle": sum(1 for s in statuses if s.state == "idle"),
                "failed": sum(1 for s in statuses if s.state == "failed"),
            },
            "missions": {
                "active": len(active_missions),
                "total": len(self.missions),
            },
            "tasks": {
                "pending": sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING),
                "in_progress": sum(1 for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS),
                "blocked": sum(1 for t in self.tasks.values() if t.status == TaskStatus.BLOCKED),
                "completed": sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED),
                "failed": sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED),
            },
            "pending_approvals": len(self.pending_approvals),
            "sim_time": self.world.sim_time,
            "simulation_running": self.simulation.running,
            "simulation_paused": self.simulation.paused,
            "active_scenario": self.active_scenario_key,
        }


_runtime: Optional[Runtime] = None


async def get_runtime() -> Runtime:
    global _runtime
    if _runtime is None:
        _runtime = Runtime()
        await _runtime.init()
    return _runtime
