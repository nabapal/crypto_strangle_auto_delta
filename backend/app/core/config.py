from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration driven by environment variables."""

    app_name: str = "Delta Strangle Control Plane"
    api_prefix: str = "/api"
    allowed_origins: List[str] = ["*"]
    debug_http_logging: bool = False
    log_level: str = "INFO"
    engine_debug_sample_rate: int = 5
    tick_log_sample_rate: int = 50
    log_ingest_api_key: str | None = None
    log_ingest_max_batch: int = 100

    # Trading runtime
    default_underlying: str = "BTC"
    default_delta_low: float = 0.10
    default_delta_high: float = 0.15
    default_trade_time_ist: str = "09:30"
    default_exit_time_ist: str = "15:20"
    default_expiry_buffer_hours: int = 24
    default_contract_size: float = 0.001

    # Live order execution strategy
    delta_order_retry_attempts: int = 4
    delta_order_retry_delay_seconds: float = 2.0
    delta_partial_fill_threshold: float = 0.10
    delta_order_timeout_seconds: float = 30.0

    # Trailing stop defaults
    trailing_sl_enabled: bool = True

    # Database connection string (SQLAlchemy format)
    database_url: str = "sqlite+aiosqlite:///./delta_trader.db"

    # Delta Exchange credentials (pull from env in production)
    delta_api_key: str | None = None
    delta_api_secret: str | None = None
    delta_base_url: str = "https://api.india.delta.exchange"
    delta_testnet_url: str = "https://testnet-api.delta.exchange"
    delta_debug_verbose: bool = False
    delta_debug_max_body_bytes: int = 2048
    delta_live_trading: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings."""

    return Settings()
