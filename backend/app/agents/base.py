"""Base cognitive agent.

Implements the Observe -> Retrieve Memory -> Reason -> Form Goal -> Plan ->
Critique -> Coordinate -> Execute -> Verify -> Reflect cycle as an
interruptible async loop. Agents do not blindly march through every phase
on every tick — `handle_message` can be triggered at any time by an
incoming message (event-driven), independent of the scheduled cycle.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.core.llm_provider import ReasoningResult, get_provider
from app.core.memory_store import get_memory_store
from app.core.message_bus import MessageBus
from app.core.schemas import (
    AgentConfig, AgentRole, AgentState, AgentStatus, DecisionRecord, Message,
    MessagePriority, MessageType, new_id, utcnow,
)

logger = logging.getLogger("agent")


class BaseAgent:
    def __init__(self, config: AgentConfig, bus: MessageBus, runtime: "Runtime"):
        self.config = config
        self.bus = bus
        self.runtime = runtime
        self.status = AgentStatus(agent_id=config.agent_id, name=config.name,
                                   role=config.role, objective=config.objective)
        self.llm = get_provider()
        self.memory = get_memory_store()
        self._inbox: asyncio.Queue[Message] = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.recent_observations: list[str] = []
        self.recent_decisions: list[DecisionRecord] = []
        self.recent_messages: list[Message] = []
        self.blockers: list[str] = []

        bus.subscribe(self.config.agent_id, self._on_message)
        bus.subscribe_broadcast(self._on_message)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name=f"agent-{self.config.agent_id}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._set_state(AgentState.STOPPED)

    def reset_episodic_state(self) -> None:
        """Clear this agent's per-run cognitive state (observations,
        decisions, message history, blockers) without tearing down the
        agent itself. Called on a full simulation reset so a fresh scenario
        starts from a genuinely clean slate instead of reasoning over
        leftover observations from a previous run. Subclasses that keep
        their own episodic counters (e.g. PlanningBot's revision rounds,
        MemoryBot's failure counts) override this and call super().
        """
        self.recent_observations.clear()
        self.recent_decisions.clear()
        self.recent_messages.clear()
        self.blockers.clear()
        self.status.messages_sent = 0
        self.status.messages_received = 0
        self.status.decisions_made = 0
        self.status.error = None
        self.status.health = "healthy"
        self._set_state(AgentState.IDLE)

    async def _run_loop(self) -> None:
        try:
            while self._running:
                try:
                    msg = await asyncio.wait_for(self._inbox.get(), timeout=2.0)
                    await self._dispatch(msg)
                except asyncio.TimeoutError:
                    await self.on_idle_tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent %s crashed: %s", self.config.agent_id, exc)
            self.status.health = "unresponsive"
            self.status.error = str(exc)
            self._set_state(AgentState.FAILED)

    async def _on_message(self, message: Message) -> None:
        if message.sender_id == self.config.agent_id:
            return  # ignore our own broadcasts
        self.status.messages_received += 1
        self.recent_messages.append(message)
        self.recent_messages = self.recent_messages[-50:]
        await self._inbox.put(message)
        if message.requires_ack:
            self.bus.acknowledge(message.message_id)

    async def _dispatch(self, message: Message) -> None:
        try:
            await asyncio.wait_for(self.handle_message(message), timeout=self.config.timeout_seconds)
        except asyncio.TimeoutError:
            self.status.health = "degraded"
            self.blockers.append(f"Timed out handling {message.message_type.value} from {message.sender_id}")
            self._set_state(AgentState.RECOVERING)
            logger.warning("Agent %s timed out on message %s", self.config.agent_id, message.message_id)
        except Exception as exc:  # noqa: BLE001
            self.status.health = "degraded"
            self.status.error = str(exc)
            self.blockers.append(str(exc))
            logger.exception("Agent %s failed handling message: %s", self.config.agent_id, exc)

    # Override in subclasses
    async def handle_message(self, message: Message) -> None:
        raise NotImplementedError

    async def on_idle_tick(self) -> None:
        """Called periodically when the inbox is empty. Default: no-op."""
        return

    # ------------------------------------------------------------------
    # helpers used by subclasses
    # ------------------------------------------------------------------
    def _set_state(self, state: AgentState) -> None:
        self.status.state = state
        self.status.last_updated = utcnow()
        self.runtime.notify_agent_state_change(self.status)

    async def send(self, *, receiver_id: Optional[str], message_type: MessageType,
                    payload: dict[str, Any], priority: MessagePriority = MessagePriority.NORMAL,
                    mission_id: Optional[str] = None, task_id: Optional[str] = None,
                    correlation_id: Optional[str] = None) -> Message:
        msg = Message(
            sender_id=self.config.agent_id, receiver_id=receiver_id, message_type=message_type,
            payload=payload, priority=priority, mission_id=mission_id, task_id=task_id,
            correlation_id=correlation_id or new_id("corr"),
        )
        self.status.messages_sent += 1
        await self.bus.publish(msg)
        return msg

    async def reason(self, objective: str, observations: list[str],
                      context: Optional[dict[str, Any]] = None) -> ReasoningResult:
        self._set_state(AgentState.REASONING)
        mem = await self.memory.retrieve_text(agent_id=self.config.agent_id, limit=5)
        result = await self.llm.reason(objective=objective, observations=observations,
                                        memory=mem, context=context)
        return result

    def record_decision(self, *, objective: str, observations: list[str], memory_refs: list[str],
                         candidate_actions: list[str], selected_action: Optional[str],
                         rationale: str, confidence: float, mission_id: Optional[str] = None,
                         task_id: Optional[str] = None, requires_approval: bool = False,
                         constraints: Optional[list[str]] = None,
                         risks: Optional[list[str]] = None) -> DecisionRecord:
        rec = DecisionRecord(
            agent_id=self.config.agent_id, mission_id=mission_id, task_id=task_id,
            objective=objective, observations=observations, memory_refs=memory_refs,
            candidate_actions=candidate_actions, selected_action=selected_action,
            rationale=rationale, confidence=confidence, requires_approval=requires_approval,
            constraints=constraints or [], risks=risks or [],
        )
        self.status.decisions_made += 1
        self.recent_decisions.append(rec)
        self.recent_decisions = self.recent_decisions[-30:]
        self.runtime.notify_decision(rec)
        return rec
