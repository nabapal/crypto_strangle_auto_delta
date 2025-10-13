import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import cast

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, AsyncConnection

# Configure an isolated SQLite database for tests before importing the shared engine
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEST_DB_PATH = DATA_DIR / "delta_trader_test.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{TEST_DB_PATH}")

from app.core.database import Base, async_session, engine
from app.core.security import create_access_token, get_password_hash
from app.models import User


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
        # Tests commit transactions to persist data for API calls, so ensure each test
        # starts from a clean database snapshot to avoid cross-test contamination.
        for table in reversed(Base.metadata.sorted_tables):
            await session.execute(text(f"DELETE FROM {table.name}"))
        await session.commit()

        try:
            yield session
        finally:
            await session.rollback()


@pytest_asyncio.fixture()
async def test_user(db_session: AsyncSession) -> User:
    result = await db_session.execute(select(User).where(User.email == "tester@example.com"))
    user = result.scalars().first()
    if not user:
        user = User(
            email="tester@example.com",
            hashed_password=get_password_hash("secret-test"),
            is_active=True,
            is_superuser=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
    else:
        await db_session.refresh(user)
    return user


@pytest.fixture()
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(str(test_user.id))
    return {"Authorization": f"Bearer {token}"}
