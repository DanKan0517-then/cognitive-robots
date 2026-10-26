"""World Model Bot.

Owns the single shared WorldModel instance. Applies observations into it,
detects conflicting/outdated reports, and broadcasts STATE_UPDATE so the
rest of the team works off one consistent picture.
"""
from __future__ import annotations

from app.agents.base import BaseAgent
from app.core.schemas import AgentState, Message, MessageType, WorldEntity, utcnow


class WorldModelBot(BaseAgent):
    async def handle_message(self, message: Message) -> None:
        if message.message_type != MessageType.OBSERVATION:
            return
        self._set_state(AgentState.REASONING)

        payload = message.payload
        entity_id = payload.get("entity_id")
        result = {"conflict": None}
        if entity_id:
            existing = self.runtime.world.get_entity(entity_id)
            x = payload.get("raw", {}).get("x", existing.x if existing else 0.0)
            y = payload.get("raw", {}).get("y", existing.y if existing else 0.0)
            entity = WorldEntity(
                entity_id=entity_id,
                kind=payload.get("raw", {}).get("entity_kind", existing.kind if existing else "object"),
                # Keep the entity's stable name once it has one. Every
                # OBSERVATION carries a free-text narration in `description`
                # ("Worker-2 also requests the charging station") -- that is
                # evidence about the entity, not its identity, so it must not
                # permanently overwrite a real label like "Charging Station"
                # on every re-observation. Only a brand-new entity the world
                # model has never seen before falls back to the observation
                # text as a readable placeholder name. Found by actually
                # watching the live map: a resource's label kept mutating
                # into whatever sentence last mentioned it.
                label=existing.label if existing else payload.get("description", entity_id),
                x=x, y=y,
                zone_id=payload.get("raw", {}).get("zone_id"),
                attributes={**(existing.attributes if existing else {}),
                            "confidence": payload.get("confidence"),
                            "last_observation": payload.get("description")},
                last_updated=utcnow(),
            )
            result = await self.runtime.world.upsert_entity(entity)

        decision = self.record_decision(
            objective="Integrate observation into the shared world state",
            observations=[payload.get("description", "")],
            memory_refs=[],
            candidate_actions=["apply_update", "flag_conflict", "discard_outdated"],
            selected_action="flag_conflict" if result.get("conflict") else "apply_update",
            rationale="Conflict check against previous entity position/timestamp"
                      if result.get("conflict") else "No conflicting prior state found",
            confidence=payload.get("confidence", 0.5),
            mission_id=message.mission_id,
        )

        await self.send(
            receiver_id=None, message_type=MessageType.STATE_UPDATE,
            payload={"entity_id": entity_id, "snapshot": self.runtime.world.snapshot(),
                     "conflict": result.get("conflict")},
            mission_id=message.mission_id, correlation_id=message.correlation_id,
        )
        self.runtime.notify_world_update()
        self._set_state(AgentState.IDLE)
