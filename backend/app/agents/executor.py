"""Action Executor Bot.

The only agent allowed to touch the simulation. Never reports success
before the simulation actually returns an execution result, and performs a
separate verification pass against the post-action world state rather than
trusting the execution call's own claim.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.schemas import AgentRole, AgentState, Message, MessagePriority, MessageType, TaskStatus


class ExecutorBot(BaseAgent):
    async def handle_message(self, message: Message) -> None:
        if message.message_type != MessageType.TASK_ASSIGNMENT:
            return
        self._set_state(AgentState.EXECUTING)
        payload = message.payload
        task_id = payload.get("task_id")
        action = payload.get("action")
        bot_entity_id = payload.get("bot_entity_id")
        entity_id = payload.get("entity_id")

        await self.runtime.update_task_status(task_id, TaskStatus.IN_PROGRESS)

        result = await self.runtime.simulation.execute_action(
            bot_entity_id=bot_entity_id, action=action, target_entity_id=entity_id,
        )

        self.record_decision(
            objective=f"Execute authorized action: {action}",
            observations=[f"bot={bot_entity_id}", f"target={entity_id}"],
            memory_refs=[], candidate_actions=[action], selected_action=action,
            rationale=result.get("detail", ""), confidence=1.0 if result.get("success") else 0.2,
            mission_id=message.mission_id, task_id=task_id,
        )

        await self.send(
            receiver_id=None, message_type=MessageType.EXECUTION_RESULT,
            payload={"task_id": task_id, "action": action, "success": result.get("success", False),
                     "detail": result.get("detail", ""), "error": result.get("error"),
                     "bot_entity_id": bot_entity_id},
            mission_id=message.mission_id, task_id=task_id, priority=MessagePriority.HIGH,
        )

        self._set_state(AgentState.VERIFYING)
        verified = await self.runtime.simulation.verify_action(
            bot_entity_id=bot_entity_id, action=action, target_entity_id=entity_id, expected=result,
        )
        await self.send(
            receiver_id=None, message_type=MessageType.VERIFICATION_RESULT,
            payload={"task_id": task_id, "verified": verified.get("verified", False),
                     "detail": verified.get("detail", "")},
            mission_id=message.mission_id, task_id=task_id, priority=MessagePriority.HIGH,
        )
        self._set_state(AgentState.COMPLETED if verified.get("verified") else AgentState.RECOVERING)
