"""Unit tests for the message bus, schema validation and world model —
the structural backbone everything else depends on.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from app.core.message_bus import MessageBus
from app.core.schemas import Message, MessageStatus, MessageType, WorldEntity
from app.core.world_model import WorldModel


# --------------------------------------------------------------------------
# Message schema validation (spec 11.3: schemas reject invalid payloads)
# --------------------------------------------------------------------------
def test_message_requires_dict_payload():
    with pytest.raises(ValidationError):
        Message(sender_id="a", message_type=MessageType.OBSERVATION, payload=["not", "a", "dict"])


def test_message_requires_valid_enum_type():
    with pytest.raises(ValidationError):
        Message(sender_id="a", message_type="not_a_real_type", payload={})


def test_message_defaults_are_sane():
    msg = Message(sender_id="a", message_type=MessageType.OBSERVATION, payload={"k": "v"})
    assert msg.status == MessageStatus.PENDING
    assert msg.message_id.startswith("msg_")
    assert msg.correlation_id.startswith("corr_")


# --------------------------------------------------------------------------
# Message bus delivery (spec 11.2: messages reach the correct recipients)
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_direct_message_reaches_only_its_recipient():
    bus = MessageBus()
    received_a, received_b = [], []

    async def handler_a(m: Message):
        received_a.append(m)

    async def handler_b(m: Message):
        received_b.append(m)

    bus.subscribe("agent-a", handler_a)
    bus.subscribe("agent-b", handler_b)

    msg = Message(sender_id="sender", receiver_id="agent-a", message_type=MessageType.OBSERVATION, payload={})
    result = await bus.publish(msg)

    assert len(received_a) == 1
    assert len(received_b) == 0
    assert result.status == MessageStatus.DELIVERED


@pytest.mark.asyncio
async def test_broadcast_reaches_every_subscriber():
    bus = MessageBus()
    counts = {"a": 0, "b": 0}

    async def handler_a(m):
        counts["a"] += 1

    async def handler_b(m):
        counts["b"] += 1

    bus.subscribe_broadcast(handler_a)
    bus.subscribe_broadcast(handler_b)

    await bus.publish(Message(sender_id="x", receiver_id=None, message_type=MessageType.BROADCAST, payload={}))
    assert counts == {"a": 1, "b": 1}


@pytest.mark.asyncio
async def test_message_to_unknown_recipient_is_marked_failed():
    bus = MessageBus()
    result = await bus.publish(Message(sender_id="x", receiver_id="nobody-home",
                                        message_type=MessageType.OBSERVATION, payload={}))
    assert result.status == MessageStatus.FAILED


@pytest.mark.asyncio
async def test_ack_and_timeout():
    bus = MessageBus()

    async def auto_ack(m: Message):
        bus.acknowledge(m.message_id)

    bus.subscribe("acker", auto_ack)
    acked = await bus.publish_and_wait_ack(
        Message(sender_id="x", receiver_id="acker", message_type=MessageType.TASK_ASSIGNMENT, payload={}),
        timeout=1.0,
    )
    assert acked.status == MessageStatus.ACKNOWLEDGED

    bus2 = MessageBus()
    bus2.subscribe("silent", lambda m: asyncio.sleep(0))  # never acks
    timed_out = await bus2.publish_and_wait_ack(
        Message(sender_id="x", receiver_id="silent", message_type=MessageType.TASK_ASSIGNMENT, payload={}),
        timeout=0.1,
    )
    assert timed_out.status == MessageStatus.TIMED_OUT


@pytest.mark.asyncio
async def test_history_for_agent_includes_sent_and_received():
    bus = MessageBus()
    bus.subscribe("a", lambda m: asyncio.sleep(0))
    bus.subscribe("b", lambda m: asyncio.sleep(0))
    await bus.publish(Message(sender_id="a", receiver_id="b", message_type=MessageType.OBSERVATION, payload={}))
    await bus.publish(Message(sender_id="b", receiver_id="a", message_type=MessageType.ACK, payload={}))
    history = bus.history_for("a")
    assert len(history) == 2


# --------------------------------------------------------------------------
# World model: conflict detection + timeline (spec 4.b)
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_world_model_upsert_and_snapshot():
    world = WorldModel(width=10, height=10)
    await world.upsert_entity(WorldEntity(entity_id="e1", kind="bot", label="Bot 1", x=1, y=1))
    snap = world.snapshot()
    assert len(snap["entities"]) == 1
    assert snap["entities"][0]["entity_id"] == "e1"


@pytest.mark.asyncio
async def test_world_model_flags_implausible_same_tick_jump():
    world = WorldModel(width=10, height=10)
    from datetime import datetime, timezone
    same_instant = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await world.upsert_entity(WorldEntity(entity_id="e1", kind="bot", label="Bot", x=0, y=0,
                                           last_updated=same_instant), conflict_check=False)
    result = await world.upsert_entity(WorldEntity(entity_id="e1", kind="bot", label="Bot", x=9, y=9,
                                                     last_updated=same_instant), conflict_check=True)
    assert result["conflict"] is not None
    assert result["conflict"]["entity_id"] == "e1"


@pytest.mark.asyncio
async def test_world_model_reset_clears_everything():
    world = WorldModel()
    await world.upsert_entity(WorldEntity(entity_id="e1", kind="bot", label="Bot", x=0, y=0))
    await world.tick()
    await world.reset()
    assert world.entities == {}
    assert world.sim_time == 0
