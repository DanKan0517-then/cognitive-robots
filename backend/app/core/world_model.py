"""Shared world state: the single source of truth about the environment.

Only the World Model agent writes here on behalf of the system (after
validating observations); everyone else reads. A timeline of every change is
kept so state transitions can be replayed and inspected.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.core.schemas import WorldEntity, WorldEvent, utcnow


@dataclass
class TimelineEntry:
    timestamp: datetime
    kind: str  # "entity_update" | "entity_added" | "entity_removed" | "event"
    detail: dict[str, Any]


class WorldModel:
    def __init__(self, width: int = 10, height: int = 10):
        self.width = width
        self.height = height
        self.entities: dict[str, WorldEntity] = {}
        self.zones: dict[str, dict[str, Any]] = {}
        self.events: list[WorldEvent] = []
        self.timeline: list[TimelineEntry] = []
        self._lock = asyncio.Lock()
        self.sim_time: int = 0

    async def reset(self, width: int = 10, height: int = 10):
        async with self._lock:
            self.width, self.height = width, height
            self.entities.clear()
            self.zones.clear()
            self.events.clear()
            self.timeline.clear()
            self.sim_time = 0

    async def upsert_entity(self, entity: WorldEntity, conflict_check: bool = True) -> dict[str, Any]:
        """Add/update an entity. Detects conflicting rapid updates (an entity
        reported in two incompatible places within the same tick) and flags
        them rather than silently overwriting.
        """
        async with self._lock:
            existing = self.entities.get(entity.entity_id)
            conflict = None
            if conflict_check and existing is not None:
                moved_far = abs(existing.x - entity.x) + abs(existing.y - entity.y)
                same_tick = existing.last_updated.replace(microsecond=0) == entity.last_updated.replace(microsecond=0)
                if moved_far > max(self.width, self.height) and same_tick:
                    conflict = {
                        "entity_id": entity.entity_id,
                        "previous": {"x": existing.x, "y": existing.y},
                        "incoming": {"x": entity.x, "y": entity.y},
                    }
            self.entities[entity.entity_id] = entity
            self.timeline.append(TimelineEntry(
                timestamp=utcnow(),
                kind="entity_added" if existing is None else "entity_update",
                detail={"entity_id": entity.entity_id, "kind": entity.kind, "x": entity.x, "y": entity.y},
            ))
            return {"conflict": conflict}

    async def remove_entity(self, entity_id: str) -> None:
        async with self._lock:
            if entity_id in self.entities:
                del self.entities[entity_id]
                self.timeline.append(TimelineEntry(
                    timestamp=utcnow(), kind="entity_removed", detail={"entity_id": entity_id}
                ))

    async def set_zone(self, zone_id: str, zone: dict[str, Any]) -> None:
        async with self._lock:
            self.zones[zone_id] = zone

    async def record_event(self, event: WorldEvent) -> None:
        async with self._lock:
            self.events.append(event)
            self.timeline.append(TimelineEntry(
                timestamp=event.timestamp, kind="event",
                detail={"event_id": event.event_id, "kind": event.kind, "description": event.description},
            ))

    async def tick(self) -> int:
        async with self._lock:
            self.sim_time += 1
            return self.sim_time

    def snapshot(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "sim_time": self.sim_time,
            "entities": [e.model_dump(mode="json") for e in self.entities.values()],
            "zones": self.zones,
            "recent_events": [e.model_dump(mode="json") for e in self.events[-30:]],
        }

    def entities_by_kind(self, kind: str) -> list[WorldEntity]:
        return [e for e in self.entities.values() if e.kind == kind]

    def get_entity(self, entity_id: str) -> Optional[WorldEntity]:
        return self.entities.get(entity_id)
