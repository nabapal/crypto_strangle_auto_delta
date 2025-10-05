from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TradingConfiguration
from ..schemas.config import TradingConfigPayload


class ConfigService:
    """Service for managing trading configuration profiles."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_configurations(self) -> Sequence[TradingConfiguration]:
        result = await self.session.execute(select(TradingConfiguration))
        return result.scalars().all()

    async def get_active_configuration(self) -> TradingConfiguration | None:
        result = await self.session.execute(
            select(TradingConfiguration).where(TradingConfiguration.is_active.is_(True))
        )
        return result.scalars().first()

    async def create_configuration(self, payload: TradingConfigPayload) -> TradingConfiguration:
        config = TradingConfiguration(**payload.model_dump())
        self.session.add(config)
        await self.session.flush()
        return config

    async def update_configuration(self, config_id: int, payload: TradingConfigPayload) -> TradingConfiguration:
        await self.session.execute(
            update(TradingConfiguration)
            .where(TradingConfiguration.id == config_id)
            .values(**payload.model_dump())
        )
        await self.session.flush()
        config = await self.get_configuration(config_id)
        if config is None:
            raise ValueError("Configuration not found")
        return config

    async def activate_configuration(self, config_id: int) -> TradingConfiguration:
        await self.session.execute(
            update(TradingConfiguration).values(is_active=False)
        )
        await self.session.execute(
            update(TradingConfiguration)
            .where(TradingConfiguration.id == config_id)
            .values(is_active=True)
        )
        await self.session.flush()
        config = await self.get_configuration(config_id)
        if config is None:
            raise ValueError("Configuration not found")
        return config

    async def get_configuration(self, config_id: int) -> TradingConfiguration | None:
        result = await self.session.execute(
            select(TradingConfiguration).where(TradingConfiguration.id == config_id)
        )
        return result.scalars().first()

    async def delete_configuration(self, config_id: int) -> None:
        config = await self.session.get(TradingConfiguration, config_id)
        if not config:
            raise ValueError("Configuration not found")
        if bool(getattr(config, "is_active", False)):
            raise ValueError("Deactivate configuration before deleting")
        await self.session.delete(config)
        await self.session.flush()
