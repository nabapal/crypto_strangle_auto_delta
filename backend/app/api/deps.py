from __future__ import annotations

from fastapi import Depends

from ..core.database import get_session


async def get_db_session(session=Depends(get_session)):
    return session
