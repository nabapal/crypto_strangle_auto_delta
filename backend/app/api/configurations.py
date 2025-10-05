from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import TradingConfiguration
from ..schemas.config import ConfigurationListResponse, TradingConfigPayload, TradingConfigResponse
from ..services.config_service import ConfigService
from .deps import get_db_session

router = APIRouter(prefix="/configs", tags=["configuration"])


def _normalize_percent(value: float | None) -> float:
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if 0 < numeric <= 1:
        return numeric * 100
    return numeric


def _serialize_config(config: TradingConfiguration) -> TradingConfigResponse:
    payload = {
        "id": config.id,
        "name": config.name,
        "underlying": config.underlying,
        "delta_range_low": config.delta_range_low,
        "delta_range_high": config.delta_range_high,
        "trade_time_ist": config.trade_time_ist,
        "exit_time_ist": config.exit_time_ist,
        "expiry_date": config.expiry_date,
        "quantity": config.quantity,
        "contract_size": config.contract_size,
    "max_loss_pct": _normalize_percent(cast(float | None, config.max_loss_pct)),
    "max_profit_pct": _normalize_percent(cast(float | None, config.max_profit_pct)),
        "trailing_sl_enabled": config.trailing_sl_enabled,
        "trailing_rules": config.trailing_rules or {},
        "is_active": config.is_active,
        "created_at": config.created_at,
        "updated_at": config.updated_at,
    }
    return TradingConfigResponse(**payload)


@router.get("/", response_model=ConfigurationListResponse)
async def list_configurations(session: AsyncSession = Depends(get_db_session)):
    service = ConfigService(session)
    configs = await service.list_configurations()
    return ConfigurationListResponse(
        items=[_serialize_config(config) for config in configs],
        total=len(configs),
    )


@router.post("/", response_model=TradingConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_configuration(
    payload: TradingConfigPayload, session: AsyncSession = Depends(get_db_session)
):
    service = ConfigService(session)
    config = await service.create_configuration(payload)
    await session.commit()
    return _serialize_config(config)


@router.put("/{config_id}", response_model=TradingConfigResponse)
async def update_configuration(
    config_id: int,
    payload: TradingConfigPayload,
    session: AsyncSession = Depends(get_db_session),
):
    service = ConfigService(session)
    existing = await service.get_configuration(config_id)
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")
    config = await service.update_configuration(config_id, payload)
    await session.commit()
    return _serialize_config(config)


@router.post("/{config_id}/activate", response_model=TradingConfigResponse)
async def activate_configuration(config_id: int, session: AsyncSession = Depends(get_db_session)):
    service = ConfigService(session)
    config = await service.get_configuration(config_id)
    if not config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Configuration not found")
    activated = await service.activate_configuration(config_id)
    await session.commit()
    return _serialize_config(activated)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_configuration(config_id: int, session: AsyncSession = Depends(get_db_session)):
    service = ConfigService(session)
    try:
        await service.delete_configuration(config_id)
    except ValueError as exc:  # noqa: PERF203
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
