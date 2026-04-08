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
class FyersConfig:
    app_id: str = field(default_factory=lambda: os.getenv("FYERS_APP_ID", ""))
    secret_key: str = field(default_factory=lambda: os.getenv("FYERS_SECRET_KEY", ""))
    access_token: str = field(default_factory=lambda: os.getenv("FYERS_ACCESS_TOKEN", ""))
    reconnect: bool = field(default_factory=lambda: _env_bool("FYERS_RECONNECT", True))


@dataclass(frozen=True)
class DhanConfig:
    client_id: str = field(default_factory=lambda: os.getenv("DHAN_CLIENT_ID", ""))
    access_token: str = field(default_factory=lambda: os.getenv("DHAN_ACCESS_TOKEN", ""))
    nifty_security_id: str = field(default_factory=lambda: os.getenv("DHAN_NIFTY_SECURITY_ID", "13"))
    banknifty_security_id: str = field(default_factory=lambda: os.getenv("DHAN_BANKNIFTY_SECURITY_ID", "25"))


@dataclass(frozen=True)
class TrueDataConfig:
    username: str = field(default_factory=lambda: os.getenv("TRUEDATA_USERNAME", ""))
    password: str = field(default_factory=lambda: os.getenv("TRUEDATA_PASSWORD", ""))
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
class LLMConfig:
    api_key: str = field(default_factory=lambda: _require_env("GEMINI_API_KEY"))
    model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    )


@dataclass(frozen=True)
class DatabaseConfig:
    url: str = field(default_factory=lambda: _require_env("DATABASE_URL"))


@dataclass(frozen=True)
class RedisConfig:
    url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379")
    )


CAPITAL_TIERS = [
    {"min": 0, "max": 100_000, "max_risk_pct": 2.0, "max_positions": 2, "daily_loss_pct": 5.0, "weekly_loss_pct": 10.0},
    {"min": 100_001, "max": 500_000, "max_risk_pct": 2.0, "max_positions": 3, "daily_loss_pct": 4.0, "weekly_loss_pct": 8.0},
    {"min": 500_001, "max": 1_000_000, "max_risk_pct": 1.5, "max_positions": 4, "daily_loss_pct": 3.0, "weekly_loss_pct": 6.0},
    {"min": 1_000_001, "max": 2_500_000, "max_risk_pct": 1.0, "max_positions": 5, "daily_loss_pct": 2.5, "weekly_loss_pct": 5.0},
]


def get_tier_for_capital(capital: float) -> dict:
    for tier in CAPITAL_TIERS:
        if tier["min"] <= capital <= tier["max"]:
            return tier
    return CAPITAL_TIERS[-1]


@dataclass(frozen=True)
class RiskConfig:
    max_daily_loss: float = field(
        default_factory=lambda: _env_float("MAX_DAILY_LOSS", 5000.0)
    )
    max_trade_risk_pct: float = field(
        default_factory=lambda: _env_float("MAX_TRADE_RISK_PCT", 2.0)
    )
    max_open_positions: int = field(
        default_factory=lambda: _env_int("MAX_OPEN_POSITIONS", 2)
    )
    vix_halt_threshold: float = field(
        default_factory=lambda: _env_float("VIX_HALT_THRESHOLD", 25.0)
    )
    capital: float = field(
        default_factory=lambda: _env_float("TRADING_CAPITAL", 100000.0)
    )
    weekly_loss_pct: float = field(
        default_factory=lambda: _env_float("WEEKLY_LOSS_PCT", 10.0)
    )


@dataclass(frozen=True)
class LearningConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("LEARNING_ENABLED", True))
    min_trades_for_model: int = field(default_factory=lambda: _env_int("MIN_TRADES_FOR_MODEL", 50))
    paper_warmup_days: int = field(default_factory=lambda: _env_int("PAPER_WARMUP_DAYS", 5))
    model_confidence_veto_threshold: float = field(
        default_factory=lambda: _env_float("MODEL_VETO_THRESHOLD", 0.35)
    )
    accuracy_rolling_days: int = field(default_factory=lambda: _env_int("ACCURACY_ROLLING_DAYS", 30))
    min_signals_for_weight_adjust: int = field(
        default_factory=lambda: _env_int("MIN_SIGNALS_FOR_WEIGHT", 10)
    )
    retrain_hour: int = field(default_factory=lambda: _env_int("RETRAIN_HOUR", 16))


VALID_TRADING_MODES = {"paper", "live"}
VALID_INSTRUMENTS = {"NIFTY", "BANKNIFTY"}


def _validated_trading_mode() -> str:
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode not in VALID_TRADING_MODES:
        raise EnvironmentError(
            f"TRADING_MODE must be one of {VALID_TRADING_MODES}, got '{mode}'"
        )
    return mode


def _validated_instruments() -> list[str]:
    raw = os.getenv("TRADING_INSTRUMENTS", "NIFTY,BANKNIFTY").upper().split(",")
    instruments = [i.strip() for i in raw if i.strip()]
    invalid = set(instruments) - VALID_INSTRUMENTS
    if invalid:
        raise EnvironmentError(
            f"TRADING_INSTRUMENTS contains invalid values: {invalid}. Allowed: {VALID_INSTRUMENTS}"
        )
    if not instruments:
        raise EnvironmentError("TRADING_INSTRUMENTS must contain at least one instrument")
    return instruments


@dataclass(frozen=True)
class TradingConfig:
    mode: Literal["paper", "live"] = field(
        default_factory=_validated_trading_mode  # type: ignore
    )
    instruments: list[str] = field(
        default_factory=_validated_instruments
    )
    consensus_threshold: float = field(
        default_factory=lambda: _env_float("CONSENSUS_THRESHOLD", 0.65)
    )
    live_pin: str = field(
        default_factory=lambda: os.getenv("LIVE_TRADING_PIN", "")
    )


NIFTY_LOT_SIZE = 25
BANKNIFTY_LOT_SIZE = 15


@dataclass(frozen=True)
class AppConfig:
    truedata: TrueDataConfig = field(default_factory=TrueDataConfig)
    zerodha: ZerodhaConfig = field(default_factory=ZerodhaConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    learning: LearningConfig = field(default_factory=LearningConfig)
    fyers: FyersConfig = field(default_factory=FyersConfig)
    dhan: DhanConfig = field(default_factory=DhanConfig)


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
    "fii_dii": "niftymind:fii_dii",
    "market_breadth": "niftymind:market_breadth",
    "news": "niftymind:news",
    "economic_calendar": "niftymind:economic_calendar",
    "global_macro": "niftymind:global_macro",
    "trade_closed": "niftymind:trade_closed",
    "learning_update": "niftymind:learning_update",
    "depth": "niftymind:depth",
    "order_book": "niftymind:order_book",
}
