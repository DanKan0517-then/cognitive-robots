"""WebSocket event stream.

Every connected client gets the same live feed: agent state changes, new
messages, world updates, task progress, decision summaries, simulation
ticks, approval requests and mission lifecycle events. Nothing here is
synthesized for the UI — it is exactly what Runtime.connections.broadcast
was given by real backend code elsewhere in the system.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.runtime import get_runtime

logger = logging.getLogger("ws")

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    rt = await get_runtime()
    queue = rt.connections.register()
    try:
        # Send an initial snapshot so a freshly-connected client doesn't
        # have to wait for the next event to render current state.
        await websocket.send_json({
            "type": "snapshot",
            "data": {
                "agents": rt.list_agent_statuses(),
                "world": rt.world.snapshot(),
                "summary": rt.dashboard_summary(),
                "approvals": rt.list_pending_approvals(),
            },
        })
        while True:
            envelope = await queue.get()
            await websocket.send_json(envelope)
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("WebSocket connection error")
    finally:
        rt.connections.unregister(queue)
