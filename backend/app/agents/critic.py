"""Critic Bot.

Independently reviews every proposal before it reaches the Mission
Coordinator. Applies explicit, inspectable policies rather than a vibe:
confidence floor, risk-escalation rule, and a missing-evidence check.
Approves, requests revision (with a concrete reason and the remaining
candidate actions), or escalates.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.schemas import AgentRole, AgentState, Message, MessagePriority, MessageType

CONFIDENCE_FLOOR = 0.45
HIGH_RISK_ACTIONS = {"escalate_immediately", "dispatch_bot_to_investigate", "allocate_resource"}
HIGH_RISK_CONFIDENCE_FLOOR = 0.65


class CriticBot(BaseAgent):
    async def handle_message(self, message: Message) -> None:
        if message.message_type != MessageType.PROPOSAL:
            return
        self._set_state(AgentState.REASONING)

        payload = message.payload
        selected_action = payload.get("selected_action", "")
        confidence = payload.get("confidence", 0.0)
        candidates = payload.get("candidates", [])
        task_id = payload.get("task_id")

        issues: list[str] = []
        if confidence < CONFIDENCE_FLOOR:
            issues.append(f"Confidence {confidence:.2f} below floor {CONFIDENCE_FLOOR}")
        if selected_action in HIGH_RISK_ACTIONS and confidence < HIGH_RISK_CONFIDENCE_FLOOR:
            issues.append(f"'{selected_action}' is high-impact and needs confidence "
                          f">= {HIGH_RISK_CONFIDENCE_FLOOR} (has {confidence:.2f})")
        if not candidates:
            issues.append("No alternative candidates were considered")

        approve = len(issues) == 0

        self.record_decision(
            objective="Review proposed plan for missing evidence, weak assumptions, unsafe actions",
            observations=[f"selected_action={selected_action}", f"confidence={confidence}"],
            memory_refs=[],
            candidate_actions=["approve", "request_revision", "escalate"],
            selected_action="approve" if approve else "request_revision",
            rationale="; ".join(issues) if issues else "No policy violations found",
            confidence=confidence,
            mission_id=message.mission_id, task_id=task_id,
            risks=issues,
        )

        if approve:
            await self.send(
                receiver_id=self.runtime.get_agent_id(AgentRole.COORDINATOR),
                message_type=MessageType.APPROVAL,
                payload={"task_id": task_id, "selected_action": selected_action,
                         "confidence": confidence, "approved_by": self.config.agent_id,
                         "entity_id": payload.get("entity_id")},
                mission_id=message.mission_id, task_id=task_id,
                correlation_id=message.correlation_id, priority=MessagePriority.HIGH,
            )
        else:
            remaining = [c for c in candidates if c != selected_action]
            await self.send(
                receiver_id=message.sender_id,
                message_type=MessageType.CRITIQUE,
                payload={"task_id": task_id, "notes": "; ".join(issues),
                         "remaining_candidates": remaining, "confidence": confidence},
                mission_id=message.mission_id, task_id=task_id,
                correlation_id=message.correlation_id, priority=MessagePriority.HIGH,
            )
        self._set_state(AgentState.IDLE)
