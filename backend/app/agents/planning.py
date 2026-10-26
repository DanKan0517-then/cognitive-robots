"""Planning Bot.

Turns an analysis (or a replan request) into a concrete proposed plan: a
short sequence of candidate actions grounded in the current world state,
submitted to the Critic before anything is authorized. Revises on
critique, up to a bounded number of rounds, rather than looping forever.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.core.schemas import AgentRole, AgentState, Message, MessagePriority, MessageType

MAX_REVISION_ROUNDS = 3


def _candidate_actions_for(entity_kind: str, analysis: str) -> list[str]:
    analysis_l = analysis.lower()
    if "blocked" in analysis_l or "obstacle" in analysis_l:
        return ["reroute_around_obstacle", "wait_for_clearance", "request_alternate_path"]
    if "unattended" in analysis_l or "hazard" in analysis_l or "anomaly" in analysis_l:
        return ["dispatch_bot_to_investigate", "monitor_remotely", "escalate_immediately"]
    if "resource" in entity_kind:
        return ["allocate_resource", "queue_for_resource", "request_additional_resource"]
    return ["dispatch_bot_to_location", "continue_patrol", "log_and_ignore"]


class PlanningBot(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._revision_rounds: dict[str, int] = {}

    def reset_episodic_state(self) -> None:
        self._revision_rounds.clear()
        super().reset_episodic_state()

    async def handle_message(self, message: Message) -> None:
        if message.message_type == MessageType.INFO_RESPONSE and message.payload.get("requires_planning"):
            await self._plan_from_analysis(message)
        elif message.message_type == MessageType.CRITIQUE:
            await self._revise_plan(message)
        elif message.message_type == MessageType.REPLAN_REQUEST:
            await self._replan(message)

    async def _plan_from_analysis(self, message: Message) -> None:
        self._set_state(AgentState.PLANNING)
        payload = message.payload
        entity_id = payload.get("entity_id")
        entity = self.runtime.world.get_entity(entity_id) if entity_id else None
        entity_kind = entity.kind if entity else "unknown"

        candidates = _candidate_actions_for(entity_kind, payload.get("analysis", ""))
        selected = candidates[0]

        mission_id = message.mission_id
        task = await self.runtime.create_task(
            mission_id=mission_id, title=selected,
            description=f"Planned in response to: {payload.get('analysis')}",
            priority=min(0.95, payload.get("confidence", 0.5) + 0.1),
            target_entity_id=entity_id,
        )

        self.record_decision(
            objective="Form an executable plan from the latest analysis",
            observations=[payload.get("source_observation", "")],
            memory_refs=[],
            candidate_actions=candidates,
            selected_action=selected,
            rationale=f"Entity kind={entity_kind}; derived from analysis confidence={payload.get('confidence')}",
            confidence=payload.get("confidence", 0.5),
            mission_id=mission_id, task_id=task.task_id,
            requires_approval=True,
        )

        await self.send(
            receiver_id=self.runtime.get_agent_id(AgentRole.CRITIC),
            message_type=MessageType.PROPOSAL,
            payload={"task_id": task.task_id, "selected_action": selected,
                     "candidates": candidates, "entity_id": entity_id,
                     "confidence": payload.get("confidence", 0.5),
                     "analysis": payload.get("analysis", "")},
            mission_id=mission_id, task_id=task.task_id,
            correlation_id=message.correlation_id, priority=MessagePriority.HIGH,
        )
        self._set_state(AgentState.NEGOTIATING)

    async def _revise_plan(self, message: Message) -> None:
        task_id = message.payload.get("task_id")
        rounds = self._revision_rounds.get(task_id, 0) + 1
        self._revision_rounds[task_id] = rounds

        task = self.runtime.get_task(task_id)
        if task is None:
            return

        critique_notes = message.payload.get("notes", "")
        candidates = message.payload.get("remaining_candidates") or ["escalate_to_coordinator"]
        selected = candidates[0] if rounds <= MAX_REVISION_ROUNDS else "escalate_to_coordinator"

        self.record_decision(
            objective="Revise plan in response to critic feedback",
            observations=[critique_notes],
            memory_refs=[],
            candidate_actions=candidates,
            selected_action=selected,
            rationale=f"Revision round {rounds}/{MAX_REVISION_ROUNDS}. Critique: {critique_notes}",
            confidence=max(0.1, message.payload.get("confidence", 0.5) - 0.1 * rounds),
            mission_id=message.mission_id, task_id=task_id,
            requires_approval=True,
        )

        if rounds > MAX_REVISION_ROUNDS:
            await self.send(
                receiver_id=self.runtime.get_agent_id(AgentRole.COORDINATOR),
                message_type=MessageType.ALERT,
                payload={"task_id": task_id, "reason": "max_revision_rounds_exceeded",
                         "last_critique": critique_notes},
                mission_id=message.mission_id, task_id=task_id,
                priority=MessagePriority.HIGH,
            )
            return

        await self.send(
            receiver_id=self.runtime.get_agent_id(AgentRole.CRITIC),
            message_type=MessageType.PROPOSAL,
            payload={"task_id": task_id, "selected_action": selected, "candidates": candidates,
                     "revision_round": rounds, "confidence": message.payload.get("confidence", 0.5)},
            mission_id=message.mission_id, task_id=task_id,
            correlation_id=message.correlation_id, priority=MessagePriority.HIGH,
        )

    async def _replan(self, message: Message) -> None:
        self._set_state(AgentState.PLANNING)
        task_id = message.payload.get("task_id")
        task = self.runtime.get_task(task_id)
        if task is None:
            return
        candidates = ["retry_with_alternate_route", "reassign_to_other_agent", "abandon_task"]
        selected = candidates[0] if task.retries < task.max_retries else candidates[-1]

        self.record_decision(
            objective="Replan after execution failure/block",
            observations=[message.payload.get("reason", "")],
            memory_refs=[],
            candidate_actions=candidates,
            selected_action=selected,
            rationale=f"Task had {task.retries}/{task.max_retries} prior retries",
            confidence=0.5,
            mission_id=message.mission_id, task_id=task_id,
            requires_approval=True,
        )

        await self.send(
            receiver_id=self.runtime.get_agent_id(AgentRole.COORDINATOR),
            message_type=MessageType.PROPOSAL,
            payload={"task_id": task_id, "selected_action": selected, "is_replan": True,
                     "candidates": candidates},
            mission_id=message.mission_id, task_id=task_id,
            correlation_id=message.correlation_id, priority=MessagePriority.HIGH,
        )
