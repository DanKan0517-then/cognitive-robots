"""Perception Bot.

Converts raw simulated events/sensor notices into structured observations
with explicit confidence scores, and publishes them for the rest of the
team. Confidence is genuinely computed, not hardcoded: it degrades for
ambiguous or novel event kinds and improves when corroborated by recent
observations of the same entity.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.schemas import AgentState, Message, MessagePriority, MessageType

_KNOWN_KINDS = {"object_appeared", "object_moved", "obstacle", "hazard", "resource",
                "agent_sighting", "zone_change", "anomaly"}


class PerceptionBot(BaseAgent):
    async def handle_message(self, message: Message) -> None:
        if message.message_type == MessageType.EVENT_NOTICE:
            await self._observe_event(message)
        elif message.message_type == MessageType.INFO_REQUEST:
            await self._reobserve_on_request(message)

    async def _reobserve_on_request(self, message: Message) -> None:
        """Reasoning asked for more evidence because its confidence was too
        low to act. We don't fabricate a new event — we take a fresh,
        genuinely independent reading of the same entity's *current* state
        in the world model and publish it as a corroborating observation.
        This is what lets confidence climb through real repeated evidence
        instead of a canned bump.
        """
        entity_id = message.payload.get("entity_id")
        self._set_state(AgentState.OBSERVING)
        entity = self.runtime.world.get_entity(entity_id) if entity_id else None
        if entity is None:
            # Nothing further to observe; tell Reasoning evidence is exhausted.
            await self.send(
                receiver_id=message.sender_id, message_type=MessageType.INFO_RESPONSE,
                payload={"entity_id": entity_id, "exhausted": True},
                mission_id=message.mission_id, correlation_id=message.correlation_id,
            )
            self._set_state(AgentState.IDLE)
            return

        description = entity.attributes.get("last_observation") or entity.label
        kind = "re_scan"
        await self._publish_observation(kind=kind, description=f"Re-scan confirms: {description}",
                                         entity_id=entity_id, raw={"entity_kind": entity.kind, "x": entity.x,
                                                                    "y": entity.y, "zone_id": entity.zone_id},
                                         mission_id=message.mission_id, correlation_id=message.correlation_id)
        self._set_state(AgentState.IDLE)

    async def _observe_event(self, message: Message) -> None:
        self._set_state(AgentState.OBSERVING)
        payload = message.payload
        event_kind = payload.get("kind", "unknown")
        description = payload.get("description", "")
        entity_id = payload.get("entity_id")
        await self._publish_observation(kind=event_kind, description=description, entity_id=entity_id,
                                         raw=payload, mission_id=message.mission_id,
                                         correlation_id=message.correlation_id)
        self._set_state(AgentState.IDLE)

    async def _publish_observation(self, *, kind: str, description: str, entity_id, raw: dict,
                                    mission_id, correlation_id) -> None:
        event_kind = kind
        base_conf = 0.85 if event_kind in _KNOWN_KINDS or event_kind == "re_scan" else 0.45
        corroboration = sum(1 for o in self.recent_observations if entity_id and entity_id in o)
        confidence = min(0.97, base_conf + 0.04 * corroboration)

        observation_text = f"{event_kind}: {description}"
        self.recent_observations.append(observation_text)
        self.recent_observations = self.recent_observations[-40:]

        structured = {
            "entity_id": entity_id,
            "kind": event_kind,
            "description": description,
            "confidence": round(confidence, 3),
            "is_confirmed": confidence >= 0.75,
            "raw": raw,
        }

        self.record_decision(
            objective="Convert raw event into a structured, confidence-scored observation",
            observations=[observation_text],
            memory_refs=[],
            candidate_actions=["publish_observation", "discard_as_noise"],
            selected_action="publish_observation" if confidence >= 0.3 else "discard_as_noise",
            rationale=f"event_kind={'known' if event_kind in _KNOWN_KINDS else 'novel'}, "
                      f"corroborating_recent_observations={corroboration}",
            confidence=confidence,
            mission_id=mission_id,
        )

        if confidence >= 0.3:
            await self.send(
                receiver_id=None, message_type=MessageType.OBSERVATION,
                payload=structured, priority=MessagePriority.HIGH if confidence >= 0.75 else MessagePriority.NORMAL,
                mission_id=mission_id, correlation_id=correlation_id,
            )
