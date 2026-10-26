"""Reasoning and Analysis Bot.

Takes observations plus retrieved memory and produces an interpretation —
explicitly separate from the raw evidence — with a confidence score and
competing alternatives. Requests more observation when evidence is thin
rather than asserting a conclusion it can't support.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.schemas import AgentRole, AgentState, Message, MessagePriority, MessageType

MIN_CONFIDENCE_TO_ACT = 0.55


class ReasoningBot(BaseAgent):
    async def handle_message(self, message: Message) -> None:
        if message.message_type != MessageType.OBSERVATION:
            return
        self._set_state(AgentState.REASONING)

        payload = message.payload
        observation_text = f"{payload.get('kind')}: {payload.get('description')}"
        self.recent_observations.append(observation_text)
        self.recent_observations = self.recent_observations[-40:]

        objective = self.runtime.active_mission_goal(message.mission_id) or "Assess the current situation"
        result = await self.reason(objective, self.recent_observations[-8:],
                                    context={"entity_id": payload.get("entity_id")})

        mem_recs = await self.memory.retrieve(agent_id=self.config.agent_id, limit=5)
        memory_refs = [r["content"][:80] for r in mem_recs]

        needs_more_evidence = result.confidence < MIN_CONFIDENCE_TO_ACT

        decision = self.record_decision(
            objective=objective,
            observations=self.recent_observations[-8:],
            memory_refs=memory_refs,
            candidate_actions=[result.conclusion] + result.alternatives,
            selected_action=result.conclusion,
            rationale=result.rationale,
            confidence=result.confidence,
            mission_id=message.mission_id,
            risks=["Low evidence volume"] if needs_more_evidence else [],
        )

        if needs_more_evidence:
            await self.send(
                receiver_id=self.runtime.get_agent_id(AgentRole.PERCEPTION),
                message_type=MessageType.INFO_REQUEST,
                payload={"reason": "confidence_below_threshold", "entity_id": payload.get("entity_id"),
                         "current_confidence": result.confidence},
                mission_id=message.mission_id, correlation_id=message.correlation_id,
                priority=MessagePriority.NORMAL,
            )
        else:
            await self.send(
                receiver_id=None, message_type=MessageType.INFO_RESPONSE,
                payload={"analysis": result.conclusion, "confidence": result.confidence,
                         "alternatives": result.alternatives, "rationale": result.rationale,
                         "entity_id": payload.get("entity_id"), "requires_planning": True,
                         "source_observation": observation_text, "llm_source": result.source},
                mission_id=message.mission_id, correlation_id=message.correlation_id,
                priority=MessagePriority.HIGH,
            )
        self._set_state(AgentState.IDLE)
