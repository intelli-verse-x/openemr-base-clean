import os

import pytest_asyncio

os.environ.setdefault("COPILOT_DB_HOST", "127.0.0.1")
os.environ.setdefault("COPILOT_DB_PORT", "8320")
os.environ.setdefault("COPILOT_LLM_PROVIDER", "mock")

from app import db  # noqa: E402


# Function-scoped so the aiomysql pool is created on the same event loop the test
# runs on (pytest-asyncio uses a fresh loop per test by default).
@pytest_asyncio.fixture(autouse=True)
async def _pool():
    await db.close_pool()
    await db.init_pool()
    yield
    await db.close_pool()
