"""FastAPI entrypoint.

Wires the REST router and WebSocket stream to a single shared Runtime
instance. Run with:

    uvicorn app.main:app --reload --port 8000

from the backend/ directory.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.api.ws import router as ws_router
from app.core.runtime import get_runtime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_runtime()  # boots the default 8-bot roster + DB on startup
    yield
    # Graceful shutdown: stop every agent, the simulation loop, and drain
    # any in-flight background persistence/broadcast writes before the DB
    # engine and event loop go away.
    rt = await get_runtime()
    await rt.shutdown()


app = FastAPI(
    title="Multi-Agent Cognitive Robot System",
    description="Software-first multi-agent cognitive framework: perception, world modeling, "
                "planning, reasoning, critique, mission coordination, execution and memory bots "
                "cooperating over a real async message bus in a simulated environment.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local/dev demo; tighten for a real deployment
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(ws_router)


@app.get("/")
async def root():
    return {
        "name": "Multi-Agent Cognitive Robot System",
        "docs": "/docs",
        "websocket": "/ws",
        "health": "/api/health",
    }
