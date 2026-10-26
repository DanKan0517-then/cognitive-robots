"""Simulation engine: the software environment bots perceive and act in.

No physical hardware is involved or required. Entities (bots, objects,
zones, resources, hazards) live in the WorldModel; this engine is what
actually changes their state when the Executor Bot carries out an
authorized action, and what verifies whether that change really happened.

A background tick loop advances simulated time and can fire scripted
events (from the active scenario) or be driven manually via `inject_event`
and `step`.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from typing import Any, Callable, Coroutine, Optional

from app.core.schemas import MessageType, WorldEntity, WorldEvent, new_id, utcnow
from app.core.world_model import WorldModel

logger = logging.getLogger("simulation")


def _rng_for(*parts: str) -> random.Random:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return random.Random(int(h[:8], 16))


class SimulationEngine:
    def __init__(self, world: WorldModel):
        self.world = world
        self.running = False
        self.paused = False
        self.speed = 1.0  # ticks per second (nominal)
        self._tick_task: Optional[asyncio.Task] = None
        self._scripted_events: list[dict[str, Any]] = []
        self._fired_event_indices: set[int] = set()
        self._emit_event: Optional[Callable[[WorldEvent], Coroutine[Any, Any, None]]] = None
        self._on_tick: Optional[Callable[[int], Coroutine[Any, Any, None]]] = None

    def configure(self, scripted_events: list[dict[str, Any]],
                  emit_event: Callable[[WorldEvent], Coroutine[Any, Any, None]],
                  on_tick: Callable[[int], Coroutine[Any, Any, None]]) -> None:
        self._scripted_events = scripted_events
        self._fired_event_indices = set()
        self._emit_event = emit_event
        self._on_tick = on_tick

    # ------------------------------------------------------------------
    # control
    # ------------------------------------------------------------------
    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.paused = False
        self._tick_task = asyncio.create_task(self._loop(), name="simulation-loop")

    async def pause(self) -> None:
        self.paused = True

    async def resume(self) -> None:
        self.paused = False

    async def stop(self) -> None:
        self.running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass

    def set_speed(self, speed: float) -> None:
        self.speed = max(0.1, min(10.0, speed))

    async def step(self) -> int:
        """Advance exactly one tick, regardless of pause state (manual stepping)."""
        return await self._do_tick()

    async def _loop(self) -> None:
        try:
            while self.running:
                if not self.paused:
                    await self._do_tick()
                await asyncio.sleep(max(0.1, 1.0 / self.speed))
        except asyncio.CancelledError:
            raise

    async def _do_tick(self) -> int:
        t = await self.world.tick()
        for idx, evt in enumerate(self._scripted_events):
            if idx in self._fired_event_indices:
                continue
            if evt.get("at_tick") == t:
                self._fired_event_indices.add(idx)
                await self._fire_scripted_event(evt)
        if self._on_tick:
            await self._on_tick(t)
        return t

    async def _fire_scripted_event(self, evt: dict[str, Any]) -> None:
        world_event = WorldEvent(kind=evt.get("kind", "scripted"), description=evt.get("description", ""),
                                  payload=evt, source="scenario_script")
        await self.world.record_event(world_event)
        if evt.get("apply"):
            self._apply_world_patch(evt["apply"])
        if self._emit_event:
            await self._emit_event(world_event)

    def _apply_world_patch(self, patch: dict[str, Any]) -> None:
        """Scripted events can directly mutate an entity's attributes, e.g.
        marking a corridor blocked, or spawning a new object, synchronously
        (the WorldModelBot still receives a STATE_UPDATE afterward)."""
        entity_id = patch.get("entity_id")
        if not entity_id:
            return
        existing = self.world.entities.get(entity_id)
        attrs = dict(existing.attributes) if existing else {}
        attrs.update(patch.get("attributes", {}))
        entity = WorldEntity(
            entity_id=entity_id,
            kind=patch.get("kind", existing.kind if existing else "object"),
            label=patch.get("label", existing.label if existing else entity_id),
            x=patch.get("x", existing.x if existing else 0.0),
            y=patch.get("y", existing.y if existing else 0.0),
            zone_id=patch.get("zone_id", existing.zone_id if existing else None),
            attributes=attrs,
        )
        self.world.entities[entity_id] = entity

    async def inject_event(self, kind: str, description: str, entity_id: Optional[str] = None,
                            payload: Optional[dict[str, Any]] = None) -> WorldEvent:
        world_event = WorldEvent(kind=kind, description=description,
                                  payload={"entity_id": entity_id, **(payload or {})}, source="manual")
        await self.world.record_event(world_event)
        if self._emit_event:
            await self._emit_event(world_event)
        return world_event

    # ------------------------------------------------------------------
    # action execution + verification (used by ExecutorBot)
    # ------------------------------------------------------------------
    async def execute_action(self, *, bot_entity_id: Optional[str], action: str,
                              target_entity_id: Optional[str]) -> dict[str, Any]:
        bot = self.world.get_entity(bot_entity_id) if bot_entity_id else None
        target = self.world.get_entity(target_entity_id) if target_entity_id else None
        rng = _rng_for(action, bot_entity_id or "", target_entity_id or "", str(self.world.sim_time))

        if bot is None and action not in {"log_and_ignore", "monitor_remotely", "escalate_immediately",
                                           "queue_for_resource", "request_additional_resource"}:
            return {"success": False, "error": "no_bot_available", "detail": "No bot entity to assign"}

        async def move_bot_toward(tx: float, ty: float, label_suffix: str) -> dict[str, Any]:
            if bot is None:
                return {"success": False, "error": "no_bot"}
            # Re-read the target live rather than trusting the snapshot taken
            # at the top of execute_action: an action like reroute_around_obstacle
            # clears `blocked` on the shared WorldModel via _apply_world_patch
            # just before calling this, and that update must be visible here.
            live_target = self.world.get_entity(target_entity_id) if target_entity_id else None
            if live_target is not None and live_target.attributes.get("blocked"):
                return {"success": False, "error": "route_blocked",
                        "detail": f"Target zone/entity {target_entity_id} is currently blocked"}
            new_entity = WorldEntity(
                entity_id=bot.entity_id, kind=bot.kind, label=bot.label,
                x=tx, y=ty, zone_id=target.zone_id if target else bot.zone_id,
                attributes={**bot.attributes, "status": label_suffix, "attempts":
                            bot.attributes.get("attempts", 0) + 1},
            )
            await self.world.upsert_entity(new_entity, conflict_check=False)
            return {"success": True, "detail": f"Bot {bot.entity_id} moved to ({tx:.1f},{ty:.1f})"}

        if action in {"dispatch_bot_to_location", "dispatch_bot_to_investigate", "continue_patrol"}:
            tx, ty = (target.x, target.y) if target else (bot.x, bot.y)
            return await move_bot_toward(tx, ty, "investigating" if "investigate" in action else "patrolling")

        if action in {"reroute_around_obstacle", "request_alternate_path", "retry_with_alternate_route"}:
            if target is not None:
                self._apply_world_patch({"entity_id": target.entity_id, "attributes": {"blocked": False}})
            tx, ty = (target.x + 1, target.y + 1) if target else (bot.x + 1, bot.y)
            return await move_bot_toward(tx, ty, "rerouted")

        if action == "wait_for_clearance":
            cleared = rng.random() > 0.4
            if cleared and target is not None:
                self._apply_world_patch({"entity_id": target.entity_id, "attributes": {"blocked": False}})
            return {"success": cleared, "error": None if cleared else "still_blocked",
                     "detail": "Route cleared while waiting" if cleared else "Route still blocked"}

        if action == "monitor_remotely":
            return {"success": True, "detail": f"Monitoring {target_entity_id} remotely"}

        if action == "escalate_immediately":
            await self.inject_event("alert_raised", f"Escalation raised for {target_entity_id}", target_entity_id)
            return {"success": True, "detail": "Alert raised to operator"}

        if action in {"allocate_resource", "request_additional_resource"}:
            if target is None:
                return {"success": False, "error": "no_resource", "detail": "Resource entity not found"}
            available = int(target.attributes.get("available", 0))
            if action == "request_additional_resource":
                self._apply_world_patch({"entity_id": target.entity_id,
                                          "attributes": {"available": available + 1}})
                return {"success": True, "detail": "Additional resource unit brought online"}
            if available <= 0:
                return {"success": False, "error": "resource_exhausted", "detail": "No units available"}
            self._apply_world_patch({"entity_id": target.entity_id, "attributes": {"available": available - 1}})
            if bot is not None:
                await move_bot_toward(target.x, target.y, "holding_resource")
            return {"success": True, "detail": f"Allocated 1 unit of {target_entity_id}"}

        if action == "queue_for_resource":
            return {"success": True, "detail": "Queued for resource availability"}

        if action in {"log_and_ignore", "reassign_to_other_agent"}:
            return {"success": True, "detail": f"Action '{action}' completed (no-op by design)"}

        if action == "abandon_task":
            return {"success": False, "error": "abandoned", "detail": "Task abandoned by policy"}

        return {"success": False, "error": "unknown_action", "detail": f"No handler for '{action}'"}

    async def verify_action(self, *, bot_entity_id: Optional[str], action: str,
                             target_entity_id: Optional[str], expected: dict[str, Any]) -> dict[str, Any]:
        if not expected.get("success"):
            return {"verified": False, "detail": "Execution reported failure; nothing to verify"}

        bot = self.world.get_entity(bot_entity_id) if bot_entity_id else None
        target = self.world.get_entity(target_entity_id) if target_entity_id else None

        if action in {"dispatch_bot_to_location", "dispatch_bot_to_investigate", "continue_patrol",
                      "reroute_around_obstacle", "request_alternate_path", "retry_with_alternate_route"}:
            if bot is None:
                return {"verified": False, "detail": "Bot no longer exists"}
            if target is not None:
                close = abs(bot.x - target.x) <= 1.5 and abs(bot.y - target.y) <= 1.5
                return {"verified": close, "detail": f"Bot at ({bot.x:.1f},{bot.y:.1f}), "
                                                       f"target at ({target.x:.1f},{target.y:.1f})"}
            return {"verified": True, "detail": "No specific target to verify against"}

        if action in {"allocate_resource"}:
            if target is None:
                return {"verified": False, "detail": "Resource entity missing"}
            return {"verified": True, "detail": f"Resource available now {target.attributes.get('available')}"}

        if action == "escalate_immediately":
            recent = [e for e in self.world.events[-10:] if e.kind == "alert_raised"]
            return {"verified": bool(recent), "detail": "Alert event present" if recent else "No alert event found"}

        return {"verified": True, "detail": "Action type has no post-condition to verify; accepted as-is"}

    def pick_patrol_bots(self) -> list[WorldEntity]:
        return self.world.entities_by_kind("bot")
