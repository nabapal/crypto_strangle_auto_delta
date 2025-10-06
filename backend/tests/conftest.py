import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, AsyncConnection

# Configure an isolated SQLite database for tests before importing the shared engine
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB_PATH = DATA_DIR / "delta_trader_test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{TEST_DB_PATH}")

from app.core.database import Base, async_session, engine


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True, scope="session")
async def prepare_database():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    async with engine.begin() as connection:
        conn = cast(AsyncConnection, connection)
        await conn.run_sync(Base.metadata.create_all)

    yield

    async with engine.begin() as connection:
        conn = cast(AsyncConnection, connection)
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest_asyncio.fixture()
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
        await session.rollback()
