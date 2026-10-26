"""Episodic memory + retrieval interface.

Kept behind a small interface so a vector index can be swapped in later
without touching callers. The current implementation uses structured
records (persisted to SQLite) with keyword/tag retrieval — genuinely
searchable, not a transcript dump.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from app.core import persistence
from app.core.schemas import utcnow


class MemoryStore:
    async def record_outcome(self, agent_id: str, mission_id: Optional[str], content: str,
                              tags: list[str]) -> None:
        await persistence.save_memory(agent_id, mission_id, "outcome", content, tags, utcnow())

    async def record_lesson(self, agent_id: str, mission_id: Optional[str], content: str,
                             tags: list[str]) -> None:
        await persistence.save_memory(agent_id, mission_id, "lesson", content, tags, utcnow())

    async def record_failure_pattern(self, agent_id: str, mission_id: Optional[str], content: str,
                                      tags: list[str]) -> None:
        await persistence.save_memory(agent_id, mission_id, "failure_pattern", content, tags, utcnow())

    async def retrieve(self, *, agent_id: Optional[str] = None, mission_id: Optional[str] = None,
                        tag: Optional[str] = None, limit: int = 5) -> list[dict[str, Any]]:
        return await persistence.query_memory(agent_id=agent_id, mission_id=mission_id, tag=tag, limit=limit)

    async def retrieve_text(self, **kwargs) -> list[str]:
        recs = await self.retrieve(**kwargs)
        return [r["content"] for r in recs]


_store: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store
