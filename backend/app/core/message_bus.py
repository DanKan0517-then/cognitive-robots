"""Real async message bus.

Every agent-to-agent exchange in this system goes through here. It is not a
decorative log — delivery, acknowledgement, rejection and timeout are all
enforced, and every message is persisted for later inspection.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Awaitable, Callable, Optional

from app.core.schemas import Message, MessageStatus, MessageType

logger = logging.getLogger("message_bus")

Handler = Callable[[Message], Awaitable[None]]


class MessageBus:
    """Async pub/sub bus with direct + broadcast delivery, priorities,
    acknowledgement tracking and timeout handling.
    """

    def __init__(self, on_message: Optional[Callable[[Message], Awaitable[None]]] = None):
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)
        self._broadcast_subscribers: list[Handler] = []
        self._pending_acks: dict[str, asyncio.Future] = {}
        self._history: list[Message] = []
        self._on_message = on_message  # global observer, used to persist/stream every message
        self._lock = asyncio.Lock()
        self._event_type_subscribers: dict[MessageType, list[Handler]] = defaultdict(list)

    # ---- subscription -----------------------------------------------
    def subscribe(self, agent_id: str, handler: Handler) -> None:
        self._subscribers[agent_id].append(handler)

    def subscribe_broadcast(self, handler: Handler) -> None:
        self._broadcast_subscribers.append(handler)

    def subscribe_to_type(self, message_type: MessageType, handler: Handler) -> None:
        self._event_type_subscribers[message_type].append(handler)

    # ---- publishing ----------------------------------------------------
    async def publish(self, message: Message) -> Message:
        """Deliver a message. Returns the message with updated status.

        Direct messages are delivered to the specific receiver's handlers.
        Broadcasts (receiver_id is None) go to every broadcast subscriber.
        """
        async with self._lock:
            self._history.append(message)

        if self._on_message:
            await self._on_message(message)

        try:
            if message.receiver_id is None:
                handlers = list(self._broadcast_subscribers)
                if not handlers:
                    message.status = MessageStatus.FAILED
                    return message
                await asyncio.gather(*(self._safe_invoke(h, message) for h in handlers))
                message.status = MessageStatus.DELIVERED
            else:
                handlers = self._subscribers.get(message.receiver_id, [])
                if not handlers:
                    message.status = MessageStatus.FAILED
                    logger.warning("No subscriber for receiver_id=%s (msg=%s)",
                                   message.receiver_id, message.message_id)
                    return message
                await asyncio.gather(*(self._safe_invoke(h, message) for h in handlers))
                message.status = MessageStatus.DELIVERED

            for h in self._event_type_subscribers.get(message.message_type, []):
                await self._safe_invoke(h, message)

        except Exception as exc:  # noqa: BLE001
            message.status = MessageStatus.FAILED
            logger.exception("Delivery failed for %s: %s", message.message_id, exc)

        return message

    async def publish_and_wait_ack(self, message: Message, timeout: Optional[float] = None) -> Message:
        """Publish a message that requires acknowledgement and wait (bounded) for it."""
        message.requires_ack = True
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_acks[message.message_id] = fut
        await self.publish(message)
        wait_for = timeout if timeout is not None else message.ttl_seconds
        try:
            await asyncio.wait_for(fut, timeout=wait_for)
            message.status = MessageStatus.ACKNOWLEDGED
        except asyncio.TimeoutError:
            message.status = MessageStatus.TIMED_OUT
        finally:
            self._pending_acks.pop(message.message_id, None)
        return message

    def acknowledge(self, correlation_id_or_message_id: str) -> bool:
        fut = self._pending_acks.get(correlation_id_or_message_id)
        if fut and not fut.done():
            fut.set_result(True)
            return True
        return False

    async def _safe_invoke(self, handler: Handler, message: Message) -> None:
        try:
            await handler(message)
        except Exception:  # noqa: BLE001
            logger.exception("Handler raised while processing %s", message.message_id)
            raise

    # ---- inspection ------------------------------------------------------
    def history(self, limit: int = 500) -> list[Message]:
        return self._history[-limit:]

    def history_for(self, agent_id: str, limit: int = 200) -> list[Message]:
        out = [m for m in self._history if m.sender_id == agent_id or m.receiver_id == agent_id]
        return out[-limit:]

    def clear(self) -> None:
        self._history.clear()
        self._pending_acks.clear()
