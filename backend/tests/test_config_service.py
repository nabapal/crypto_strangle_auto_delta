from typing import cast

import pytest

from app.schemas.config import TradingConfigPayload
from app.services.config_service import ConfigService


@pytest.mark.asyncio
async def test_create_and_activate_configuration(db_session):
    payload = TradingConfigPayload(
        name="Default",
        underlying="BTC",
        delta_range_low=0.1,
        delta_range_high=0.15,
        trade_time_ist="09:30",
        exit_time_ist="15:20",
        expiry_date="06-10-2025",
        quantity=1,
        contract_size=0.001,
        max_loss_pct=0.5,
        max_profit_pct=0.5,
        trailing_sl_enabled=True,
        trailing_rules={"0.2": 0.0},
    )
    service = ConfigService(db_session)
    config = await service.create_configuration(payload)
    assert config.id is not None

    config_id = cast(int, config.id)
    activated = await service.activate_configuration(config_id)
    assert activated.is_active is True
