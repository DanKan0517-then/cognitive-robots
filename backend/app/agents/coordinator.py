"""Mission Coordinator Bot.

The final authority: ranks competing tasks by urgency/confidence/deadline,
allocates them to the Executor, resolves resource conflicts between tasks
that target the same entity, and reassigns/replans on failure. High-impact
actions (as flagged by the Critic's risk policy) are queued for explicit
approval instead of auto-authorized.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.schemas import (
    AgentRole, AgentState, Message, MessagePriority, MessageType, TaskStatus,
)

AUTO_APPROVE_ACTIONS = {"continue_patrol", "log_and_ignore", "monitor_remotely",
                         "wait_for_clearance", "queue_for_resource"}


class MissionCoordinatorBot(BaseAgent):
    async def handle_message(self, message: Message) -> None:
        if message.message_type == MessageType.APPROVAL:
            await self._authorize(message)
        elif message.message_type == MessageType.PROPOSAL and message.payload.get("is_replan"):
            await self._authorize_replan(message)
        elif message.message_type == MessageType.ALERT:
            await self._handle_alert(message)
        elif message.message_type == MessageType.EXECUTION_RESULT:
            await self._on_execution_result(message)
        elif message.message_type == MessageType.VERIFICATION_RESULT:
            await self._on_verification(message)

    async def _authorize(self, message: Message) -> None:
        self._set_state(AgentState.NEGOTIATING)
        payload = message.payload
        task_id = payload.get("task_id")
        task = self.runtime.get_task(task_id)
        if task is None:
            return

        conflict_task_id = self.runtime.find_conflicting_active_task(task)
        candidates = ["authorize_and_dispatch", "queue_pending_resource", "require_human_approval"]

        if conflict_task_id:
            other = self.runtime.get_task(conflict_task_id)
            if other and other.priority >= task.priority:
                selected = "queue_pending_resource"
                await self.runtime.update_task_status(task_id, TaskStatus.BLOCKED,
                                                        error=f"Resource conflict with higher-priority task {conflict_task_id}")
                self.record_decision(
                    objective="Resolve resource conflict between concurrent tasks",
                    observations=[f"conflicts_with={conflict_task_id}"],
                    memory_refs=[], candidate_actions=candidates, selected_action=selected,
                    rationale=f"Task {conflict_task_id} has priority {other.priority:.2f} >= {task.priority:.2f}",
                    confidence=payload.get("confidence", 0.5), mission_id=message.mission_id, task_id=task_id,
                )
                self._set_state(AgentState.BLOCKED)
                return

        requires_human = payload.get("selected_action") not in AUTO_APPROVE_ACTIONS and task.priority >= 0.85
        selected = "require_human_approval" if requires_human else "authorize_and_dispatch"

        self.record_decision(
            objective="Authorize approved plan and allocate to an executor",
            observations=[f"selected_action={payload.get('selected_action')}"],
            memory_refs=[], candidate_actions=candidates, selected_action=selected,
            rationale="High-impact action at high priority routed for human approval"
                      if requires_human else "Within auto-approval policy",
            confidence=payload.get("confidence", 0.5), mission_id=message.mission_id, task_id=task_id,
            requires_approval=requires_human,
        )

        if requires_human:
            self.runtime.queue_for_approval(task_id, payload)
            self._set_state(AgentState.WAITING_FOR_AGENT)
            return

        await self._dispatch_task(message, task_id, payload.get("selected_action"))

    async def authorize_pending(self, task_id: str, approve: bool) -> None:
        """Called by the REST layer when a human approves/rejects a queued action."""
        payload = self.runtime.pop_pending_approval(task_id)
        if payload is None:
            return
        if approve:
            await self._dispatch_task(None, task_id, payload.get("selected_action"), mission_id=payload.get("mission_id"))
        else:
            await self.runtime.update_task_status(task_id, TaskStatus.CANCELLED, error="Rejected by operator")

    async def _dispatch_task(self, message, task_id: str, action: str, mission_id: str | None = None) -> None:
        task = self.runtime.get_task(task_id)
        if task is None:
            return
        bot_id = self.runtime.pick_executor_bot()
        await self.runtime.update_task_status(task_id, TaskStatus.ASSIGNED, assigned_agent_id=bot_id)
        self._set_state(AgentState.EXECUTING)
        await self.send(
            receiver_id=self.runtime.get_agent_id(AgentRole.EXECUTOR),
            message_type=MessageType.TASK_ASSIGNMENT,
            payload={"task_id": task_id, "action": action, "bot_entity_id": bot_id,
                     "entity_id": (message.payload.get("entity_id") if message else None)},
            mission_id=mission_id or (message.mission_id if message else task.mission_id),
            task_id=task_id, priority=MessagePriority.HIGH,
        )

    async def _authorize_replan(self, message: Message) -> None:
        task_id = message.payload.get("task_id")
        action = message.payload.get("selected_action")
        if action == "abandon_task":
            await self.runtime.update_task_status(task_id, TaskStatus.CANCELLED, error="Abandoned after replanning")
            self.record_decision(
                objective="Decide fate of repeatedly-failing task", observations=[], memory_refs=[],
                candidate_actions=["abandon_task"], selected_action="abandon_task",
                rationale="Replan exhausted retries", confidence=0.4,
                mission_id=message.mission_id, task_id=task_id,
            )
            return
        await self._dispatch_task(message, task_id, action)

    async def _handle_alert(self, message: Message) -> None:
        task_id = message.payload.get("task_id")
        self.runtime.queue_for_approval(task_id, {**message.payload, "selected_action": "escalate_immediately",
                                                    "mission_id": message.mission_id})
        self.record_decision(
            objective="Handle planning deadlock escalation",
            observations=[message.payload.get("reason", "")], memory_refs=[],
            candidate_actions=["require_human_approval", "abandon_task"],
            selected_action="require_human_approval",
            rationale="Planning exceeded revision rounds; routed to operator",
            confidence=0.3, mission_id=message.mission_id, task_id=task_id,
            requires_approval=True,
        )

    async def _on_execution_result(self, message: Message) -> None:
        task_id = message.payload.get("task_id")
        success = message.payload.get("success", False)
        if success:
            await self.runtime.update_task_status(task_id, TaskStatus.COMPLETED, result=message.payload)
        else:
            task = self.runtime.get_task(task_id)
            if task and task.retries < task.max_retries:
                await self.runtime.increment_task_retry(task_id)
                await self.send(
                    receiver_id=self.runtime.get_agent_id(AgentRole.PLANNING),
                    message_type=MessageType.REPLAN_REQUEST,
                    payload={"task_id": task_id, "reason": message.payload.get("error", "execution failed")},
                    mission_id=message.mission_id, task_id=task_id, priority=MessagePriority.HIGH,
                )
            else:
                await self.runtime.update_task_status(task_id, TaskStatus.FAILED, error=message.payload.get("error"))

    async def _on_verification(self, message: Message) -> None:
        """Only act here when execution itself reported success but the
        post-condition check failed (task.status == COMPLETED at this
        point). If execution already failed, `_on_execution_result` is the
        sole owner of replanning for that attempt — firing a second
        REPLAN_REQUEST here would double-execute the same task.
        """
        task_id = message.payload.get("task_id")
        verified = message.payload.get("verified", False)
        task = self.runtime.get_task(task_id)

        if not verified and task is not None and task.status == TaskStatus.COMPLETED:
            if task.retries < task.max_retries:
                await self.runtime.increment_task_retry(task_id)
                await self.runtime.update_task_status(task_id, TaskStatus.IN_PROGRESS,
                                                        error="Post-condition not verified after reported success")
                await self.send(
                    receiver_id=self.runtime.get_agent_id(AgentRole.PLANNING),
                    message_type=MessageType.REPLAN_REQUEST,
                    payload={"task_id": task_id, "reason": "verification_failed"},
                    mission_id=message.mission_id, task_id=task_id, priority=MessagePriority.HIGH,
                )
            else:
                await self.runtime.update_task_status(task_id, TaskStatus.FAILED,
                                                        error="Verification failed after max retries")
        self.runtime.notify_mission_progress(message.mission_id)
