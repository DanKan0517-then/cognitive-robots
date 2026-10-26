"""SQLite-backed persistence via SQLAlchemy (async).

Missions, tasks, messages, decisions, memory records and world events are
all written here so the system survives a backend restart and so the
dashboard can reconstruct mission history.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DB_PATH = os.environ.get("COGROBOT_DB_PATH", "./cognitive_robots.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

# 8 concurrent agents (plus HTTP requests, plus the simulation tick loop) all
# write decisions/messages/missions through this one SQLite file. SQLite only
# ever allows a single writer at a time, so without these two settings
# concurrent writers intermittently fail with "database is locked" instead of
# waiting for the lock: WAL mode lets readers proceed while a write is in
# flight, and busy_timeout makes a blocked writer retry internally for up to
# 30s instead of raising immediately. This was caught by a flaky run of the
# automated test suite under real concurrent agent load, not by inspection.
engine = create_async_engine(DATABASE_URL, echo=False, future=True, connect_args={"timeout": 30})


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class MissionRow(Base):
    __tablename__ = "missions"
    mission_id = Column(String, primary_key=True)
    name = Column(String)
    goal = Column(Text)
    scenario_key = Column(String)
    status = Column(String)
    priority = Column(Float)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    outcome = Column(Text, nullable=True)
    data = Column(Text)  # full JSON blob of the Mission model


class TaskRow(Base):
    __tablename__ = "tasks"
    task_id = Column(String, primary_key=True)
    mission_id = Column(String, index=True)
    status = Column(String)
    assigned_agent_id = Column(String, nullable=True)
    updated_at = Column(DateTime)
    data = Column(Text)


class MessageRow(Base):
    __tablename__ = "messages"
    message_id = Column(String, primary_key=True)
    correlation_id = Column(String, index=True)
    sender_id = Column(String, index=True)
    receiver_id = Column(String, index=True, nullable=True)
    message_type = Column(String)
    mission_id = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime)
    data = Column(Text)


class DecisionRow(Base):
    __tablename__ = "decisions"
    decision_id = Column(String, primary_key=True)
    agent_id = Column(String, index=True)
    mission_id = Column(String, nullable=True, index=True)
    task_id = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime)
    data = Column(Text)


class MemoryRow(Base):
    __tablename__ = "memory_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String, index=True)
    mission_id = Column(String, nullable=True, index=True)
    kind = Column(String)  # "outcome" | "lesson" | "failure_pattern"
    content = Column(Text)
    tags = Column(Text)  # JSON list
    created_at = Column(DateTime)


class EventRow(Base):
    __tablename__ = "world_events"
    event_id = Column(String, primary_key=True)
    kind = Column(String)
    timestamp = Column(DateTime)
    data = Column(Text)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def save_mission(mission) -> None:
    async with async_session() as session:
        row = await session.get(MissionRow, mission.mission_id)
        payload = dict(
            name=mission.name, goal=mission.goal, scenario_key=mission.scenario_key,
            status=mission.status.value, priority=mission.priority,
            created_at=mission.created_at, updated_at=mission.updated_at,
            outcome=mission.outcome, data=mission.model_dump_json(),
        )
        if row is None:
            row = MissionRow(mission_id=mission.mission_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        await session.commit()


async def save_task(task) -> None:
    async with async_session() as session:
        row = await session.get(TaskRow, task.task_id)
        payload = dict(
            mission_id=task.mission_id, status=task.status.value,
            assigned_agent_id=task.assigned_agent_id, updated_at=task.updated_at,
            data=task.model_dump_json(),
        )
        if row is None:
            row = TaskRow(task_id=task.task_id, **payload)
            session.add(row)
        else:
            for k, v in payload.items():
                setattr(row, k, v)
        await session.commit()


async def save_message(message) -> None:
    async with async_session() as session:
        row = MessageRow(
            message_id=message.message_id, correlation_id=message.correlation_id,
            sender_id=message.sender_id, receiver_id=message.receiver_id,
            message_type=message.message_type.value, mission_id=message.mission_id,
            timestamp=message.timestamp, data=message.model_dump_json(),
        )
        session.add(row)
        await session.commit()


async def save_decision(decision) -> None:
    async with async_session() as session:
        row = DecisionRow(
            decision_id=decision.decision_id, agent_id=decision.agent_id,
            mission_id=decision.mission_id, task_id=decision.task_id,
            timestamp=decision.timestamp, data=decision.model_dump_json(),
        )
        session.add(row)
        await session.commit()


async def save_memory(agent_id: str, mission_id: Optional[str], kind: str, content: str,
                       tags: list[str], created_at: datetime) -> None:
    async with async_session() as session:
        row = MemoryRow(agent_id=agent_id, mission_id=mission_id, kind=kind,
                         content=content, tags=json.dumps(tags), created_at=created_at)
        session.add(row)
        await session.commit()


async def query_memory(agent_id: Optional[str] = None, mission_id: Optional[str] = None,
                        tag: Optional[str] = None, limit: int = 20) -> list[dict[str, Any]]:
    async with async_session() as session:
        stmt = select(MemoryRow).order_by(MemoryRow.created_at.desc()).limit(limit * 3)
        if agent_id:
            stmt = stmt.where(MemoryRow.agent_id == agent_id)
        if mission_id:
            stmt = stmt.where(MemoryRow.mission_id == mission_id)
        rows = (await session.execute(stmt)).scalars().all()
        out = []
        for r in rows:
            tags = json.loads(r.tags or "[]")
            if tag and tag not in tags:
                continue
            out.append({
                "agent_id": r.agent_id, "mission_id": r.mission_id, "kind": r.kind,
                "content": r.content, "tags": tags, "created_at": r.created_at.isoformat(),
            })
            if len(out) >= limit:
                break
        return out


async def load_missions() -> list[dict[str, Any]]:
    async with async_session() as session:
        rows = (await session.execute(select(MissionRow))).scalars().all()
        return [json.loads(r.data) for r in rows]


async def load_tasks_for_mission(mission_id: str) -> list[dict[str, Any]]:
    async with async_session() as session:
        rows = (await session.execute(select(TaskRow).where(TaskRow.mission_id == mission_id))).scalars().all()
        return [json.loads(r.data) for r in rows]


async def load_messages(mission_id: Optional[str] = None, limit: int = 300) -> list[dict[str, Any]]:
    async with async_session() as session:
        stmt = select(MessageRow).order_by(MessageRow.timestamp.desc()).limit(limit)
        if mission_id:
            stmt = stmt.where(MessageRow.mission_id == mission_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [json.loads(r.data) for r in reversed(rows)]


async def load_decisions(mission_id: Optional[str] = None, agent_id: Optional[str] = None,
                          limit: int = 200) -> list[dict[str, Any]]:
    async with async_session() as session:
        stmt = select(DecisionRow).order_by(DecisionRow.timestamp.desc()).limit(limit)
        if mission_id:
            stmt = stmt.where(DecisionRow.mission_id == mission_id)
        if agent_id:
            stmt = stmt.where(DecisionRow.agent_id == agent_id)
        rows = (await session.execute(stmt)).scalars().all()
        return [json.loads(r.data) for r in reversed(rows)]


async def reset_all() -> None:
    """Wipe all tables (used by the simulation reset control)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
