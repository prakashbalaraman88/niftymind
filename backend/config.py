import os
from dataclasses import dataclass, field
from typing import Literal
from dotenv import load_dotenv

load_dotenv()


def _require_env(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Required environment variable '{key}' is not set")
    return value


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    return float(raw) if raw else default


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    return int(raw) if raw else default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key, "").lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


@dataclass(frozen=True)
class TrueDataConfig:
    username: str = field(default_factory=lambda: _require_env("TRUEDATA_USERNAME"))
    password: str = field(default_factory=lambda: _require_env("TRUEDATA_PASSWORD"))
    ws_url: str = field(
        default_factory=lambda: os.getenv(
            "TRUEDATA_WS_URL", "wss://push.truedata.in"
        )
    )
    reconnect_delay: float = field(
        default_factory=lambda: _env_float("TRUEDATA_RECONNECT_DELAY", 5.0)
    )
    max_reconnect_attempts: int = field(
        default_factory=lambda: _env_int("TRUEDATA_MAX_RECONNECT_ATTEMPTS", 10)
    )


@dataclass(frozen=True)
class ZerodhaConfig:
    api_key: str = field(default_factory=lambda: _require_env("ZERODHA_API_KEY"))
    api_secret: str = field(default_factory=lambda: _require_env("ZERODHA_API_SECRET"))
    access_token: str = field(
        default_factory=lambda: os.getenv("ZERODHA_ACCESS_TOKEN", "")
    )


@dataclass(frozen=True)
class AnthropicConfig:
    api_key: str = field(default_factory=lambda: _require_env("ANTHROPIC_API_KEY"))
    model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    )
    max_tokens: int = field(
        default_factory=lambda: _env_int("ANTHROPIC_MAX_TOKENS", 4096)
    )


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = field(default_factory=lambda: _require_env("DATABASE_URL"))


@dataclass(frozen=True)
class RedisConfig:
    url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379")
    )


@dataclass(frozen=True)
class RiskConfig:
    max_daily_loss: float = field(
        default_factory=lambda: _env_float("MAX_DAILY_LOSS", 50000.0)
    )
    max_trade_risk_pct: float = field(
        default_factory=lambda: _env_float("MAX_TRADE_RISK_PCT", 2.0)
    )
    max_open_positions: int = field(
        default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 5)
    )
    vix_halt_threshold: float = field(
        default_factory=lambda: _env_float("VIX_HALT_THRESHOLD", 25.0)
    )
    capital: float = field(
        default_factory=lambda: _env_float("TRADING_CAPITAL", 500000.0)
    )


@dataclass(frozen=True)
class TradingConfig:
    mode: Literal["paper", "live"] = field(
        default_factory=lambda: os.getenv("TRADING_MODE", "paper").lower()  # type: ignore
    )
    instruments: list[str] = field(
        default_factory=lambda: os.getenv("TRADING_INSTRUMENTS", "NIFTY,BANKNIFTY")
        .upper()
        .split(",")
    )
    consensus_threshold: float = field(
        default_factory=lambda: _env_float("CONSENSUS_THRESHOLD", 0.65)
    )
    live_pin: str = field(
        default_factory=lambda: os.getenv("LIVE_TRADING_PIN", "")
    )


NIFTY_LOT_SIZE = 50
BANKNIFTY_LOT_SIZE = 15


@dataclass(frozen=True)
class AppConfig:
    truedata: TrueDataConfig = field(default_factory=TrueDataConfig)
    zerodha: ZerodhaConfig = field(default_factory=ZerodhaConfig)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)


REDIS_CHANNELS = {
    "ticks": "niftymind:ticks",
    "options_chain": "niftymind:options_chain",
    "ohlc_1m": "niftymind:ohlc:1m",
    "ohlc_5m": "niftymind:ohlc:5m",
    "ohlc_15m": "niftymind:ohlc:15m",
    "signals": "niftymind:signals",
    "trade_proposals": "niftymind:trade_proposals",
    "trade_executions": "niftymind:trade_executions",
    "agent_status": "niftymind:agent_status",
}
