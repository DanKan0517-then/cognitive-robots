"""Memory and Learning Bot.

Persists outcomes (success/failure) as structured, searchable records and
extracts an explicit lesson when a pattern repeats. "Learning" here means a
measurable, inspectable policy nudge (a lesson record that future Planning
decisions can retrieve and that shows up in the dashboard) — not merely
storing a transcript.
"""
from __future__ import annotations

from collections import Counter

from app.agents.base import BaseAgent
from app.core.schemas import AgentState, Message, MessageType

FAILURE_PATTERN_THRESHOLD = 2


class MemoryBot(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._failure_counts: Counter[str] = Counter()

    def reset_episodic_state(self) -> None:
        self._failure_counts.clear()
        super().reset_episodic_state()

    async def handle_message(self, message: Message) -> None:
        if message.message_type == MessageType.EXECUTION_RESULT:
            await self._on_execution_result(message)
        elif message.message_type == MessageType.VERIFICATION_RESULT:
            await self._on_verification(message)
        elif message.message_type == MessageType.INFO_REQUEST and message.payload.get("reason") == "memory_lookup":
            await self._on_lookup(message)

    async def _on_execution_result(self, message: Message) -> None:
        self._set_state(AgentState.REASONING)
        payload = message.payload
        action = payload.get("action", "unknown")
        success = payload.get("success", False)
        tag = f"action:{action}"

        content = (f"Task {payload.get('task_id')} executed action '{action}' "
                   f"-> {'success' if success else 'failure'}: {payload.get('detail') or payload.get('error')}")
        await self.memory.record_outcome(self.config.agent_id, message.mission_id, content, [tag, "outcome"])

        selected_action = "record_outcome"
        if not success:
            self._failure_counts[action] += 1
            if self._failure_counts[action] >= FAILURE_PATTERN_THRESHOLD:
                lesson = (f"Action '{action}' has failed {self._failure_counts[action]} time(s) "
                          f"this session — Planning should prefer alternate candidates for this action.")
                await self.memory.record_failure_pattern(self.config.agent_id, message.mission_id,
                                                           lesson, [tag, "failure_pattern"])
                selected_action = "record_failure_pattern"

        self.record_decision(
            objective="Persist execution outcome and extract any recurring-failure lesson",
            observations=[content], memory_refs=[],
            candidate_actions=["record_outcome", "record_failure_pattern"],
            selected_action=selected_action,
            rationale=f"failure_count_for_action={self._failure_counts[action]}",
            confidence=1.0, mission_id=message.mission_id, task_id=payload.get("task_id"),
        )
        self._set_state(AgentState.IDLE)

    async def _on_verification(self, message: Message) -> None:
        payload = message.payload
        content = f"Task {payload.get('task_id')} verification: {payload.get('detail')}"
        await self.memory.record_outcome(self.config.agent_id, message.mission_id, content,
                                          ["verification"])

    async def _on_lookup(self, message: Message) -> None:
        recs = await self.memory.retrieve(mission_id=message.mission_id, limit=5)
        await self.send(
            receiver_id=message.sender_id, message_type=MessageType.INFO_RESPONSE,
            payload={"records": recs}, mission_id=message.mission_id,
            correlation_id=message.correlation_id,
        )
