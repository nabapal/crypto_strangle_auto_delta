from typing import cast

import pytest

from app.schemas.config import StrikeSelectionMode, TradingConfigPayload
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


@pytest.mark.asyncio
async def test_max_loss_accepts_values_above_100(db_session):
    payload = TradingConfigPayload(
        name="HighLoss",
        underlying="BTC",
        delta_range_low=0.1,
        delta_range_high=0.2,
        trade_time_ist="09:30",
        exit_time_ist="15:20",
        expiry_date="07-10-2025",
        quantity=1,
        contract_size=0.001,
        max_loss_pct=150,
        max_profit_pct=0.8,
        trailing_sl_enabled=True,
        trailing_rules={"0.3": 0.1},
        strike_selection_mode=StrikeSelectionMode.PRICE,
        call_option_price_min=50,
        call_option_price_max=60,
        put_option_price_min=48,
        put_option_price_max=58,
    )
    service = ConfigService(db_session)
    config = await service.create_configuration(payload)

    max_loss_value = cast(float, config.max_loss_pct)
    max_profit_value = cast(float, config.max_profit_pct)
    call_min_value = cast(float, config.call_option_price_min)
    call_max_value = cast(float, config.call_option_price_max)
    put_min_value = cast(float, config.put_option_price_min)
    put_max_value = cast(float, config.put_option_price_max)
    mode_value = cast(StrikeSelectionMode, config.strike_selection_mode)

    assert max_loss_value == pytest.approx(150)
    # Max profit still normalizes decimals to percentage values
    assert max_profit_value == pytest.approx(80)
    assert mode_value == StrikeSelectionMode.PRICE
    assert call_min_value == pytest.approx(50)
    assert call_max_value == pytest.approx(60)
    assert put_min_value == pytest.approx(48)
    assert put_max_value == pytest.approx(58)


@pytest.mark.asyncio
async def test_price_mode_requires_price_ranges(db_session):
    with pytest.raises(ValueError):
        TradingConfigPayload(
            name="InvalidPriceConfig",
            underlying="BTC",
            delta_range_low=0.1,
            delta_range_high=0.2,
            trade_time_ist="09:30",
            exit_time_ist="15:20",
            quantity=1,
            contract_size=0.001,
            max_loss_pct=50,
            max_profit_pct=0.5,
            trailing_sl_enabled=True,
            trailing_rules={},
            strike_selection_mode=StrikeSelectionMode.PRICE,
        )
