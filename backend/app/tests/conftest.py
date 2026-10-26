"""Test configuration.

Sets an isolated SQLite file for the test run *before* any other test
module imports app.core.persistence (which reads the env var at import
time to build its engine), so tests never touch the developer's real
cognitive_robots.db.
"""
from __future__ import annotations

import os
import pathlib

_TEST_DB = pathlib.Path(__file__).parent / "test_cognitive_robots.db"
for _suffix in ("", "-wal", "-shm"):  # WAL mode leaves sidecar files
    _stale = pathlib.Path(str(_TEST_DB) + _suffix)
    if _stale.exists():
        _stale.unlink()
os.environ["COGROBOT_DB_PATH"] = str(_TEST_DB)
os.environ.pop("ANTHROPIC_API_KEY", None)  # force the deterministic fallback path

import asyncio  # noqa: E402
from typing import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.core import persistence  # noqa: E402
from app.core.message_bus import MessageBus  # noqa: E402
from app.core.runtime import Runtime  # noqa: E402
from app.core.world_model import WorldModel  # noqa: E402


@pytest_asyncio.fixture
async def fresh_runtime() -> AsyncIterator[Runtime]:
    """A brand-new Runtime with its own DB rows, independent of the
    process-wide singleton used by the FastAPI app. Used by integration
    tests that drive agents directly without going through HTTP.
    """
    rt = Runtime()
    await rt.init()
    try:
        yield rt
    finally:
        await rt.shutdown()


@pytest_asyncio.fixture
async def clean_db():
    await persistence.init_db()
    await persistence.reset_all()
    yield
