"""
Broker Manager with Failover Support
=====================================
Unified broker interface with automatic failover across multiple brokers.

Broker priority:
  1. Zerodha Kite (primary)
  2. Fyers        (fallback 1)
  3. Dhan         (fallback 2)

Features:
- Automatic health checks every 30 seconds
- Failover on order placement failure
- Unified position, order, and quote APIs
- Graceful degradation: if all brokers fail, enters safe mode
- Circuit breaker pattern to prevent cascading failures
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable

logger = logging.getLogger("niftymind.broker_manager")

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class BrokerStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"       # Working but with issues
    UNHEALTHY = "unhealthy"     # Failed health check
    CIRCUIT_OPEN = "circuit_open"  # Circuit breaker tripped
    NOT_CONFIGURED = "not_configured"


class BrokerName(Enum):
    ZERODHA = "zerodha"
    FYERS = "fyers"
    DHAN = "dhan"


@dataclass
class BrokerHealth:
    """Health status for a single broker."""
    broker: BrokerName
    status: BrokerStatus
    last_check: float = 0.0          # Unix timestamp
    last_success: float = 0.0        # Unix timestamp of last successful operation
    consecutive_failures: int = 0
    total_orders: int = 0
    failed_orders: int = 0
    latency_ms: float = 0.0
    error_message: str = ""

    @property
    def failure_rate(self) -> float:
        if self.total_orders == 0:
            return 0.0
        return self.failed_orders / self.total_orders

    @property
    def is_available(self) -> bool:
        return self.status in (BrokerStatus.HEALTHY, BrokerStatus.DEGRADED)


@dataclass
class BrokerConfig:
    """Configuration for a broker connection."""
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    access_token: str = ""
    client_id: str = ""
    pin: str = ""
    redirect_url: str = ""


@dataclass
class UnifiedPosition:
    """Normalized position across all brokers."""
    symbol: str
    exchange: str
    quantity: int
    direction: str          # LONG or SHORT
    avg_price: float
    product: str            # MIS, NRML, CNC
    m2m: float = 0.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    broker: BrokerName = BrokerName.ZERODHA
    broker_position_id: str = ""


@dataclass
class UnifiedOrderResult:
    """Normalized order result across all brokers."""
    success: bool
    order_id: str = ""
    status: str = ""            # PENDING, COMPLETE, REJECTED, etc.
    average_price: float = 0.0
    filled_quantity: int = 0
    broker: BrokerName = BrokerName.ZERODHA
    error_message: str = ""
    retry_attempts: int = 0


# ---------------------------------------------------------------------------
# Abstract broker adapter
# ---------------------------------------------------------------------------

class BaseBrokerAdapter(ABC):
    """Abstract base for all broker adapters."""

    def __init__(self, config: BrokerConfig):
        self.config = config
        self.name: BrokerName = BrokerName.ZERODHA
        self._client: Any = None
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the broker connection. Returns True on success."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Quick health check. Returns True if broker is responsive."""
        pass

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        transaction_type: str,      # BUY or SELL
        quantity: int,
        product: str,               # MIS, NRML
        order_type: str = "MARKET", # MARKET, LIMIT, SL, SL-M
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> UnifiedOrderResult:
        """Place an order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        pass

    @abstractmethod
    async def get_positions(self) -> List[UnifiedPosition]:
        """Get all open positions."""
        pass

    @abstractmethod
    async def get_orders(self) -> List[dict]:
        """Get all orders for the day."""
        pass

    @abstractmethod
    async def get_order_history(self, order_id: str) -> List[dict]:
        """Get order history/status."""
        pass

    @abstractmethod
    async def get_quote(self, symbol: str, exchange: str = "NFO") -> dict:
        """Get quote for a symbol."""
        pass

    @abstractmethod
    async def get_funds(self) -> dict:
        """Get available funds."""
        pass

    def is_ready(self) -> bool:
        return self._initialized and self._client is not None


# ---------------------------------------------------------------------------
# Zerodha Kite Adapter
# ---------------------------------------------------------------------------

class KiteAdapter(BaseBrokerAdapter):
    """Zerodha Kite Connect adapter."""

    def __init__(self, config: BrokerConfig):
        super().__init__(config)
        self.name = BrokerName.ZERODHA

    async def initialize(self) -> bool:
        try:
            from kiteconnect import KiteConnect
            self._client = KiteConnect(api_key=self.config.api_key)
            self._client.set_access_token(self.config.access_token)
            # Quick validation
            await asyncio.to_thread(self._client.margins)
            self._initialized = True
            logger.info("Kite adapter initialized successfully")
            return True
        except ImportError:
            logger.error("kiteconnect package not installed")
            return False
        except Exception as e:
            logger.error(f"Kite adapter initialization failed: {e}")
            return False

    async def health_check(self) -> bool:
        if not self.is_ready():
            return False
        try:
            await asyncio.to_thread(self._client.margins)
            return True
        except Exception as e:
            logger.warning(f"Kite health check failed: {e}")
            return False

    async def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> UnifiedOrderResult:
        if not self.is_ready():
            return UnifiedOrderResult(success=False, error_message="Kite not initialized")

        kite_order_type = self._map_order_type(order_type)
        kite_transaction = transaction_type.upper()

        try:
            params = {
                "variety": "regular",
                "exchange": "NFO",
                "tradingsymbol": symbol,
                "transaction_type": kite_transaction,
                "quantity": quantity,
                "product": product.upper(),
                "order_type": kite_order_type,
            }
            if order_type in ("LIMIT", "SL") and price > 0:
                params["price"] = price
            if order_type in ("SL", "SL-M") and trigger_price > 0:
                params["trigger_price"] = trigger_price

            order_id = await asyncio.to_thread(self._client.place_order, **params)
            return UnifiedOrderResult(
                success=True,
                order_id=str(order_id),
                status="PENDING",
                broker=BrokerName.ZERODHA,
            )
        except Exception as e:
            error_msg = str(e)[:200]
            logger.error(f"Kite order failed for {symbol}: {error_msg}")
            return UnifiedOrderResult(
                success=False,
                error_message=error_msg,
                broker=BrokerName.ZERODHA,
            )

    async def cancel_order(self, order_id: str) -> bool:
        if not self.is_ready():
            return False
        try:
            await asyncio.to_thread(self._client.cancel_order, variety="regular", order_id=order_id)
            return True
        except Exception as e:
            logger.error(f"Kite cancel order failed: {e}")
            return False

    async def get_positions(self) -> List[UnifiedPosition]:
        if not self.is_ready():
            return []
        try:
            positions = await asyncio.to_thread(self._client.positions)
            result = []
            day_positions = positions.get("day", [])
            for pos in day_positions:
                qty = int(pos.get("quantity", 0))
                if qty == 0:
                    continue
                result.append(UnifiedPosition(
                    symbol=pos.get("tradingsymbol", ""),
                    exchange=pos.get("exchange", "NFO"),
                    quantity=abs(qty),
                    direction="LONG" if qty > 0 else "SHORT",
                    avg_price=float(pos.get("average_price", 0)),
                    product=pos.get("product", ""),
                    m2m=float(pos.get("m2m", 0)),
                    realised_pnl=float(pos.get("realised", 0)),
                    unrealised_pnl=float(pos.get("unrealised", 0)),
                    broker=BrokerName.ZERODHA,
                    broker_position_id=pos.get("position_id", ""),
                ))
            return result
        except Exception as e:
            logger.error(f"Kite get positions failed: {e}")
            return []

    async def get_orders(self) -> List[dict]:
        if not self.is_ready():
            return []
        try:
            return await asyncio.to_thread(self._client.orders) or []
        except Exception as e:
            logger.error(f"Kite get orders failed: {e}")
            return []

    async def get_order_history(self, order_id: str) -> List[dict]:
        if not self.is_ready():
            return []
        try:
            return await asyncio.to_thread(self._client.order_history, order_id=order_id) or []
        except Exception as e:
            logger.error(f"Kite order history failed: {e}")
            return []

    async def get_quote(self, symbol: str, exchange: str = "NFO") -> dict:
        if not self.is_ready():
            return {}
        try:
            quote = await asyncio.to_thread(self._client.quote, [f"{exchange}:{symbol}"])
            return quote.get(f"{exchange}:{symbol}", {})
        except Exception as e:
            logger.error(f"Kite quote failed for {symbol}: {e}")
            return {}

    async def get_funds(self) -> dict:
        if not self.is_ready():
            return {}
        try:
            margins = await asyncio.to_thread(self._client.margins)
            equity = margins.get("equity", {})
            return {
                "available": float(equity.get("available", {}).get("cash", 0)),
                "used": float(equity.get("utilised", {}).get("debits", 0)),
                "net": float(equity.get("net", 0)),
            }
        except Exception as e:
            logger.error(f"Kite get funds failed: {e}")
            return {}

    @staticmethod
    def _map_order_type(order_type: str) -> str:
        mapping = {
            "MARKET": "MARKET",
            "LIMIT": "LIMIT",
            "SL": "SL",
            "SL-M": "SL-M",
        }
        return mapping.get(order_type.upper(), "MARKET")


# ---------------------------------------------------------------------------
# Fyers Adapter
# ---------------------------------------------------------------------------

class FyersAdapter(BaseBrokerAdapter):
    """Fyers API adapter."""

    def __init__(self, config: BrokerConfig):
        super().__init__(config)
        self.name = BrokerName.FYERS

    async def initialize(self) -> bool:
        try:
            from fyers_apiv3 import fyersModel
            self._client = fyersModel.FyersModel(
                client_id=self.config.client_id,
                token=self.config.access_token,
                is_async=False,
            )
            # Quick validation
            profile = self._client.get_profile()
            if profile.get("s") == "ok":
                self._initialized = True
                logger.info("Fyers adapter initialized successfully")
                return True
            else:
                logger.error(f"Fyers initialization failed: {profile}")
                return False
        except ImportError:
            logger.error("fyers_apiv3 package not installed")
            return False
        except Exception as e:
            logger.error(f"Fyers adapter initialization failed: {e}")
            return False

    async def health_check(self) -> bool:
        if not self.is_ready():
            return False
        try:
            profile = await asyncio.to_thread(self._client.get_profile)
            return profile.get("s") == "ok"
        except Exception as e:
            logger.warning(f"Fyers health check failed: {e}")
            return False

    async def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> UnifiedOrderResult:
        if not self.is_ready():
            return UnifiedOrderResult(success=False, error_message="Fyers not initialized")

        side = 1 if transaction_type.upper() == "BUY" else -1
        fyers_product = "INTRADAY" if product.upper() == "MIS" else "CNC"
        fyers_type = self._map_order_type(order_type)

        data = {
            "symbol": f"NFO:{symbol}",
            "qty": quantity,
            "type": fyers_type,
            "side": side,
            "product": fyers_product,
            "validity": "DAY",
        }
        if order_type in ("LIMIT", "SL") and price > 0:
            data["limitPrice"] = price
        if order_type in ("SL", "SL-M") and trigger_price > 0:
            data["stopPrice"] = trigger_price

        try:
            response = await asyncio.to_thread(self._client.place_order, data)
            if response.get("s") == "ok":
                return UnifiedOrderResult(
                    success=True,
                    order_id=str(response.get("id", "")),
                    status="PENDING",
                    broker=BrokerName.FYERS,
                )
            else:
                return UnifiedOrderResult(
                    success=False,
                    error_message=response.get("message", "Unknown Fyers error"),
                    broker=BrokerName.FYERS,
                )
        except Exception as e:
            error_msg = str(e)[:200]
            logger.error(f"Fyers order failed for {symbol}: {error_msg}")
            return UnifiedOrderResult(success=False, error_message=error_msg, broker=BrokerName.FYERS)

    async def cancel_order(self, order_id: str) -> bool:
        if not self.is_ready():
            return False
        try:
            response = await asyncio.to_thread(self._client.cancel_order, {"id": order_id})
            return response.get("s") == "ok"
        except Exception as e:
            logger.error(f"Fyers cancel order failed: {e}")
            return False

    async def get_positions(self) -> List[UnifiedPosition]:
        if not self.is_ready():
            return []
        try:
            response = await asyncio.to_thread(self._client.positions)
            if response.get("s") != "ok":
                return []
            result = []
            for pos in response.get("netPositions", []):
                qty = int(pos.get("qty", 0))
                if qty == 0:
                    continue
                result.append(UnifiedPosition(
                    symbol=pos.get("symbol", "").replace("NFO:", ""),
                    exchange="NFO",
                    quantity=abs(qty),
                    direction="LONG" if qty > 0 else "SHORT",
                    avg_price=float(pos.get("avgPrice", 0)),
                    product=pos.get("productType", ""),
                    realised_pnl=float(pos.get("pl_realized", 0)),
                    unrealised_pnl=float(pos.get("pl_unrealized", 0)),
                    broker=BrokerName.FYERS,
                ))
            return result
        except Exception as e:
            logger.error(f"Fyers get positions failed: {e}")
            return []

    async def get_orders(self) -> List[dict]:
        if not self.is_ready():
            return []
        try:
            response = await asyncio.to_thread(self._client.orderbook)
            if response.get("s") == "ok":
                return response.get("orderBook", [])
            return []
        except Exception as e:
            logger.error(f"Fyers get orders failed: {e}")
            return []

    async def get_order_history(self, order_id: str) -> List[dict]:
        if not self.is_ready():
            return []
        try:
            orders = await self.get_orders()
            for o in orders:
                if str(o.get("id", "")) == order_id:
                    return [o]
            return []
        except Exception as e:
            logger.error(f"Fyers order history failed: {e}")
            return []

    async def get_quote(self, symbol: str, exchange: str = "NFO") -> dict:
        if not self.is_ready():
            return {}
        try:
            response = await asyncio.to_thread(
                self._client.quotes, {"symbols": f"{exchange}:{symbol}"}
            )
            if response.get("s") == "ok":
                quotes = response.get("d", [])
                return quotes[0] if quotes else {}
            return {}
        except Exception as e:
            logger.error(f"Fyers quote failed for {symbol}: {e}")
            return {}

    async def get_funds(self) -> dict:
        if not self.is_ready():
            return {}
        try:
            response = await asyncio.to_thread(self._client.funds)
            if response.get("s") == "ok":
                fund_limit = response.get("fund_limit", [])
                for f in fund_limit:
                    if f.get("id") == 10:  # Equity segment
                        return {
                            "available": float(f.get("equityAmount", 0)),
                            "used": 0.0,
                            "net": float(f.get("equityAmount", 0)),
                        }
            return {}
        except Exception as e:
            logger.error(f"Fyers get funds failed: {e}")
            return {}

    @staticmethod
    def _map_order_type(order_type: str) -> int:
        mapping = {
            "MARKET": 2,
            "LIMIT": 1,
            "SL": 4,
            "SL-M": 3,
        }
        return mapping.get(order_type.upper(), 2)


# ---------------------------------------------------------------------------
# Dhan Adapter
# ---------------------------------------------------------------------------

class DhanAdapter(BaseBrokerAdapter):
    """Dhan HQ API adapter."""

    def __init__(self, config: BrokerConfig):
        super().__init__(config)
        self.name = BrokerName.DHAN

    async def initialize(self) -> bool:
        try:
            from dhanhq import dhanhq
            self._client = dhanhq(
                client_id=self.config.client_id,
                access_token=self.config.access_token,
            )
            # Quick validation — fetch funds
            await asyncio.to_thread(self._client.get_fund_limits)
            self._initialized = True
            logger.info("Dhan adapter initialized successfully")
            return True
        except ImportError:
            logger.error("dhanhq package not installed")
            return False
        except Exception as e:
            logger.error(f"Dhan adapter initialization failed: {e}")
            return False

    async def health_check(self) -> bool:
        if not self.is_ready():
            return False
        try:
            await asyncio.to_thread(self._client.get_fund_limits)
            return True
        except Exception as e:
            logger.warning(f"Dhan health check failed: {e}")
            return False

    async def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> UnifiedOrderResult:
        if not self.is_ready():
            return UnifiedOrderResult(success=False, error_message="Dhan not initialized")

        dhan_txn = dhanhq.BUY if transaction_type.upper() == "BUY" else dhanhq.SELL
        dhan_product = dhanhq.INTRA if product.upper() == "MIS" else dhanhq.MARGIN
        dhan_order_type = self._map_order_type(order_type)

        try:
            # Need security ID — this is a simplified version
            # In production, map symbol to Dhan security ID
            security_id = symbol  # Placeholder — should be mapped
            response = await asyncio.to_thread(
                self._client.place_order,
                tag="niftymind",
                transaction_type=dhan_txn,
                exchange_segment=dhanhq.FNO,
                product_type=dhan_product,
                order_type=dhan_order_type,
                validity="DAY",
                security_id=security_id,
                quantity=quantity,
                price=price if order_type in ("LIMIT", "SL") else 0,
                trigger_price=trigger_price if order_type in ("SL", "SL-M") else 0,
            )
            if response.get("status") == "success":
                return UnifiedOrderResult(
                    success=True,
                    order_id=str(response.get("data", {}).get("orderId", "")),
                    status="PENDING",
                    broker=BrokerName.DHAN,
                )
            else:
                return UnifiedOrderResult(
                    success=False,
                    error_message=response.get("remarks", "Unknown Dhan error"),
                    broker=BrokerName.DHAN,
                )
        except Exception as e:
            error_msg = str(e)[:200]
            logger.error(f"Dhan order failed for {symbol}: {error_msg}")
            return UnifiedOrderResult(success=False, error_message=error_msg, broker=BrokerName.DHAN)

    async def cancel_order(self, order_id: str) -> bool:
        if not self.is_ready():
            return False
        try:
            response = await asyncio.to_thread(self._client.cancel_order, order_id=order_id)
            return response.get("status") == "success"
        except Exception as e:
            logger.error(f"Dhan cancel order failed: {e}")
            return False

    async def get_positions(self) -> List[UnifiedPosition]:
        if not self.is_ready():
            return []
        try:
            response = await asyncio.to_thread(self._client.get_positions)
            if not isinstance(response, list):
                return []
            result = []
            for pos in response:
                qty = int(pos.get("netQty", 0))
                if qty == 0:
                    continue
                result.append(UnifiedPosition(
                    symbol=pos.get("tradingSymbol", ""),
                    exchange=pos.get("exchangeSegment", ""),
                    quantity=abs(qty),
                    direction="LONG" if qty > 0 else "SHORT",
                    avg_price=float(pos.get("avgPrice", 0)),
                    product=pos.get("productType", ""),
                    broker=BrokerName.DHAN,
                ))
            return result
        except Exception as e:
            logger.error(f"Dhan get positions failed: {e}")
            return []

    async def get_orders(self) -> List[dict]:
        if not self.is_ready():
            return []
        try:
            response = await asyncio.to_thread(self._client.get_order_list)
            if isinstance(response, list):
                return response
            if isinstance(response, dict) and response.get("status") == "success":
                return response.get("data", [])
            return []
        except Exception as e:
            logger.error(f"Dhan get orders failed: {e}")
            return []

    async def get_order_history(self, order_id: str) -> List[dict]:
        if not self.is_ready():
            return []
        try:
            response = await asyncio.to_thread(self._client.get_order_by_id, order_id=order_id)
            if isinstance(response, dict):
                return [response]
            return []
        except Exception as e:
            logger.error(f"Dhan order history failed: {e}")
            return []

    async def get_quote(self, symbol: str, exchange: str = "NFO") -> dict:
        if not self.is_ready():
            return {}
        try:
            # Dhan uses security IDs, not symbols directly
            response = await asyncio.to_thread(
                self._client.intraday_daily_minute_charts,
                security_id=symbol,
                exchange_segment=exchange,
                instrument_type="OPTIDX",
            )
            return response if isinstance(response, dict) else {}
        except Exception as e:
            logger.error(f"Dhan quote failed for {symbol}: {e}")
            return {}

    async def get_funds(self) -> dict:
        if not self.is_ready():
            return {}
        try:
            response = await asyncio.to_thread(self._client.get_fund_limits)
            if isinstance(response, dict) and response.get("status") == "success":
                data = response.get("data", {})
                return {
                    "available": float(data.get("availableBalance", 0)),
                    "used": float(data.get("utilizedAmount", 0)),
                    "net": float(data.get("netBalance", 0)),
                }
            return {}
        except Exception as e:
            logger.error(f"Dhan get funds failed: {e}")
            return {}

    @staticmethod
    def _map_order_type(order_type: str):
        try:
            from dhanhq import dhanhq
            mapping = {
                "MARKET": dhanhq.MARKET,
                "LIMIT": dhanhq.LIMIT,
                "SL": dhanhq.SL,
                "SL-M": dhanhq.SL_MARKET,
            }
            return mapping.get(order_type.upper(), dhanhq.MARKET)
        except ImportError:
            return 0  # MARKET fallback


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Circuit breaker to prevent cascading failures."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 2,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = "CLOSED"       # CLOSED, OPEN, HALF_OPEN
        self._failures = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_closed(self) -> bool:
        return self._state == "CLOSED"

    @property
    def is_open(self) -> bool:
        return self._state == "OPEN"

    def record_success(self):
        if self._state == "HALF_OPEN":
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._state = "CLOSED"
                self._failures = 0
                self._half_open_calls = 0
                logger.info("Circuit breaker CLOSED — broker recovered")
        elif self._state == "CLOSED":
            self._failures = max(0, self._failures - 1)

    def record_failure(self):
        self._failures += 1
        self._last_failure_time = time.time()

        if self._state == "HALF_OPEN":
            self._state = "OPEN"
            logger.warning(f"Circuit breaker OPENED again — broker failed in half-open state")
        elif self._failures >= self.failure_threshold:
            self._state = "OPEN"
            logger.warning(f"Circuit breaker OPENED after {self._failures} consecutive failures")

    def can_execute(self) -> bool:
        if self._state == "CLOSED":
            return True
        if self._state == "OPEN":
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "HALF_OPEN"
                self._half_open_calls = 0
                logger.info("Circuit breaker HALF_OPEN — attempting recovery")
                return True
            return False
        if self._state == "HALF_OPEN":
            return self._half_open_calls < self.half_open_max_calls
        return False


# ---------------------------------------------------------------------------
# Broker Manager
# ---------------------------------------------------------------------------

class BrokerManager:
    """Manages multiple brokers with automatic failover.

    Usage:
        manager = BrokerManager(zerodha_config=cfg1, fyers_config=cfg2)
        await manager.initialize()

        # Place order (auto-failover)
        result = await manager.place_order(symbol="NIFTY...", transaction_type="BUY", ...)

        # Get positions (from active broker)
        positions = await manager.get_positions()
    """

    def __init__(
        self,
        zerodha_config: Optional[BrokerConfig] = None,
        fyers_config: Optional[BrokerConfig] = None,
        dhan_config: Optional[BrokerConfig] = None,
        health_check_interval: float = 30.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
        order_retry_attempts: int = 3,
        order_retry_delay: float = 2.0,
    ):
        self._adapters: Dict[BrokerName, BaseBrokerAdapter] = {}
        self._health: Dict[BrokerName, BrokerHealth] = {}
        self._circuit_breakers: Dict[BrokerName, CircuitBreaker] = {}
        self._active_broker: BrokerName = BrokerName.ZERODHA
        self._health_check_interval = health_check_interval
        self._order_retry_attempts = order_retry_attempts
        self._order_retry_delay = order_retry_delay
        self._health_check_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # Initialize adapters
        if zerodha_config and zerodha_config.enabled:
            self._adapters[BrokerName.ZERODHA] = KiteAdapter(zerodha_config)
            self._health[BrokerName.ZERODHA] = BrokerHealth(broker=BrokerName.ZERODHA, status=BrokerStatus.NOT_CONFIGURED)
            self._circuit_breakers[BrokerName.ZERODHA] = CircuitBreaker(
                failure_threshold=circuit_failure_threshold,
                recovery_timeout=circuit_recovery_timeout,
            )

        if fyers_config and fyers_config.enabled:
            self._adapters[BrokerName.FYERS] = FyersAdapter(fyers_config)
            self._health[BrokerName.FYERS] = BrokerHealth(broker=BrokerName.FYERS, status=BrokerStatus.NOT_CONFIGURED)
            self._circuit_breakers[BrokerName.FYERS] = CircuitBreaker(
                failure_threshold=circuit_failure_threshold,
                recovery_timeout=circuit_recovery_timeout,
            )

        if dhan_config and dhan_config.enabled:
            self._adapters[BrokerName.DHAN] = DhanAdapter(dhan_config)
            self._health[BrokerName.DHAN] = BrokerHealth(broker=BrokerName.DHAN, status=BrokerStatus.NOT_CONFIGURED)
            self._circuit_breakers[BrokerName.DHAN] = CircuitBreaker(
                failure_threshold=circuit_failure_threshold,
                recovery_timeout=circuit_recovery_timeout,
            )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Initialize all configured broker adapters."""
        logger.info("Broker Manager: initializing adapters...")
        initialized = []

        for broker_name in [BrokerName.ZERODHA, BrokerName.FYERS, BrokerName.DHAN]:
            adapter = self._adapters.get(broker_name)
            if adapter is None:
                continue
            try:
                success = await adapter.initialize()
                if success:
                    self._health[broker_name].status = BrokerStatus.HEALTHY
                    self._health[broker_name].last_success = time.time()
                    initialized.append(broker_name.value)
                    logger.info(f"Broker {broker_name.value} initialized")
                else:
                    self._health[broker_name].status = BrokerStatus.UNHEALTHY
                    logger.warning(f"Broker {broker_name.value} initialization failed")
            except Exception as e:
                self._health[broker_name].status = BrokerStatus.UNHEALTHY
                self._health[broker_name].error_message = str(e)[:200]
                logger.error(f"Broker {broker_name.value} init exception: {e}")

        if not initialized:
            logger.critical("NO BROKERS AVAILABLE — trading disabled")
            return False

        # Select best broker as active
        self._select_best_broker()
        logger.info(f"Broker Manager: active broker = {self._active_broker.value}")

        # Start health check loop
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        return True

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Broker Manager: shutting down...")
        self._shutdown_event.set()
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        logger.info("Broker Manager: shutdown complete")

    # ------------------------------------------------------------------
    # Unified broker API
    # ------------------------------------------------------------------

    async def place_order(
        self,
        symbol: str,
        transaction_type: str,
        quantity: int,
        product: str,
        order_type: str = "MARKET",
        price: float = 0.0,
        trigger_price: float = 0.0,
        force_broker: Optional[BrokerName] = None,
    ) -> UnifiedOrderResult:
        """Place an order with automatic failover across brokers."""
        brokers_to_try = self._get_broker_priority_list(force_broker)
        last_error = "No brokers available"

        for broker_name in brokers_to_try:
            adapter = self._adapters.get(broker_name)
            cb = self._circuit_breakers.get(broker_name)

            if adapter is None or not adapter.is_ready():
                continue
            if cb and not cb.can_execute():
                logger.warning(f"Circuit breaker open for {broker_name.value}, skipping")
                continue

            for attempt in range(self._order_retry_attempts):
                health = self._health[broker_name]
                health.total_orders += 1

                start = time.time()
                try:
                    result = await adapter.place_order(
                        symbol=symbol,
                        transaction_type=transaction_type,
                        quantity=quantity,
                        product=product,
                        order_type=order_type,
                        price=price,
                        trigger_price=trigger_price,
                    )
                    latency = (time.time() - start) * 1000
                    health.latency_ms = latency
                    result.retry_attempts = attempt

                    if result.success:
                        health.last_success = time.time()
                        health.consecutive_failures = 0
                        if cb:
                            cb.record_success()
                        if broker_name != self._active_broker:
                            logger.info(f"Order placed via fallback broker {broker_name.value}")
                        return result
                    else:
                        health.consecutive_failures += 1
                        health.failed_orders += 1
                        last_error = result.error_message
                        logger.warning(f"Order attempt {attempt+1} failed on {broker_name.value}: {last_error}")

                except Exception as e:
                    latency = (time.time() - start) * 1000
                    health.latency_ms = latency
                    health.consecutive_failures += 1
                    health.failed_orders += 1
                    last_error = str(e)[:200]
                    logger.error(f"Order exception on {broker_name.value} attempt {attempt+1}: {e}")

                if attempt < self._order_retry_attempts - 1:
                    await asyncio.sleep(self._order_retry_delay * (attempt + 1))

            # All retries exhausted for this broker
            if cb:
                cb.record_failure()

        # All brokers failed
        logger.critical(f"ORDER FAILED on all brokers: {symbol} {transaction_type} x{quantity} — {last_error}")
        return UnifiedOrderResult(
            success=False,
            error_message=f"All brokers failed. Last error: {last_error}",
            broker=self._active_broker,
            retry_attempts=self._order_retry_attempts * len(brokers_to_try),
        )

    async def cancel_order(self, order_id: str, broker: Optional[BrokerName] = None) -> bool:
        """Cancel an order. Uses the specified broker or the active one."""
        target = broker or self._active_broker
        adapter = self._adapters.get(target)
        if adapter and adapter.is_ready():
            return await adapter.cancel_order(order_id)

        # Try all brokers
        for broker_name in self._get_broker_priority_list():
            adapter = self._adapters.get(broker_name)
            if adapter and adapter.is_ready():
                return await adapter.cancel_order(order_id)
        return False

    async def get_positions(self) -> List[UnifiedPosition]:
        """Get positions from the active broker."""
        adapter = self._adapters.get(self._active_broker)
        if adapter and adapter.is_ready():
            try:
                return await adapter.get_positions()
            except Exception as e:
                logger.error(f"Failed to get positions from {self._active_broker.value}: {e}")

        # Try fallback brokers
        for broker_name in self._get_broker_priority_list():
            if broker_name == self._active_broker:
                continue
            adapter = self._adapters.get(broker_name)
            if adapter and adapter.is_ready():
                try:
                    return await adapter.get_positions()
                except Exception as e:
                    logger.error(f"Failed to get positions from {broker_name.value}: {e}")

        return []

    async def get_all_positions_across_brokers(self) -> Dict[BrokerName, List[UnifiedPosition]]:
        """Get positions from ALL configured brokers (for reconciliation)."""
        result = {}
        for broker_name, adapter in self._adapters.items():
            if adapter and adapter.is_ready():
                try:
                    positions = await adapter.get_positions()
                    result[broker_name] = positions
                except Exception as e:
                    logger.error(f"Failed to get positions from {broker_name.value}: {e}")
                    result[broker_name] = []
        return result

    async def get_orders(self) -> List[dict]:
        """Get orders from the active broker."""
        adapter = self._adapters.get(self._active_broker)
        if adapter and adapter.is_ready():
            try:
                return await adapter.get_orders()
            except Exception as e:
                logger.error(f"Failed to get orders: {e}")
        return []

    async def get_order_history(self, order_id: str) -> List[dict]:
        """Get order history. Tries all brokers."""
        for broker_name in self._get_broker_priority_list():
            adapter = self._adapters.get(broker_name)
            if adapter and adapter.is_ready():
                try:
                    history = await adapter.get_order_history(order_id)
                    if history:
                        return history
                except Exception:
                    continue
        return []

    async def get_quote(self, symbol: str, exchange: str = "NFO") -> dict:
        """Get quote from the active broker."""
        adapter = self._adapters.get(self._active_broker)
        if adapter and adapter.is_ready():
            try:
                return await adapter.get_quote(symbol, exchange)
            except Exception as e:
                logger.error(f"Failed to get quote for {symbol}: {e}")
        return {}

    async def get_funds(self) -> dict:
        """Get funds from the active broker."""
        adapter = self._adapters.get(self._active_broker)
        if adapter and adapter.is_ready():
            try:
                return await adapter.get_funds()
            except Exception as e:
                logger.error(f"Failed to get funds: {e}")
        return {}

    # ------------------------------------------------------------------
    # Broker management
    # ------------------------------------------------------------------

    def get_active_broker(self) -> BrokerName:
        return self._active_broker

    def get_health_status(self) -> Dict[str, dict]:
        """Get health status for all brokers."""
        return {
            name.value: {
                "status": h.status.value,
                "is_available": h.is_available,
                "consecutive_failures": h.consecutive_failures,
                "failure_rate": round(h.failure_rate, 3),
                "latency_ms": round(h.latency_ms, 1),
                "last_success": h.last_success,
                "error_message": h.error_message,
                "circuit_state": self._circuit_breakers[name].state if name in self._circuit_breakers else "N/A",
            }
            for name, h in self._health.items()
        }

    def is_healthy(self) -> bool:
        """Check if at least one broker is healthy."""
        return any(h.is_available for h in self._health.values())

    def force_broker_switch(self, broker: BrokerName) -> bool:
        """Manually switch to a specific broker."""
        if broker in self._adapters and self._adapters[broker].is_ready():
            old = self._active_broker
            self._active_broker = broker
            logger.info(f"Manual broker switch: {old.value} -> {broker.value}")
            return True
        logger.warning(f"Cannot switch to {broker.value}: not available")
        return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_broker_priority_list(self, force_broker: Optional[BrokerName] = None) -> List[BrokerName]:
        """Get ordered list of brokers to try."""
        if force_broker and force_broker in self._adapters:
            return [force_broker]

        priority = [BrokerName.ZERODHA, BrokerName.FYERS, BrokerName.DHAN]
        # Move active broker to front
        if self._active_broker in priority:
            priority.remove(self._active_broker)
            priority.insert(0, self._active_broker)

        # Filter to only configured adapters
        return [b for b in priority if b in self._adapters]

    def _select_best_broker(self):
        """Select the best available broker as active."""
        for broker_name in [BrokerName.ZERODHA, BrokerName.FYERS, BrokerName.DHAN]:
            adapter = self._adapters.get(broker_name)
            health = self._health.get(broker_name)
            if adapter and adapter.is_ready() and health and health.is_available:
                old = self._active_broker
                self._active_broker = broker_name
                if old != broker_name:
                    logger.info(f"Active broker switched: {old.value} -> {broker_name.value}")
                return

        logger.critical("No healthy broker available!")

    async def _health_check_loop(self):
        """Background health check loop."""
        logger.info("Health check loop started")
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self._health_check_interval,
                )
                break  # Shutdown requested
            except asyncio.TimeoutError:
                pass

            await self._run_health_checks()

    async def _run_health_checks(self):
        """Run health checks on all configured brokers."""
        for broker_name, adapter in self._adapters.items():
            health = self._health[broker_name]

            if not adapter.is_ready():
                # Try to reinitialize
                try:
                    success = await adapter.initialize()
                    health.status = BrokerStatus.HEALTHY if success else BrokerStatus.UNHEALTHY
                    if success:
                        health.last_success = time.time()
                except Exception as e:
                    health.status = BrokerStatus.UNHEALTHY
                    health.error_message = str(e)[:200]
                continue

            start = time.time()
            try:
                is_healthy = await adapter.health_check()
                latency = (time.time() - start) * 1000
                health.latency_ms = latency
                health.last_check = time.time()

                if is_healthy:
                    health.status = BrokerStatus.HEALTHY if health.consecutive_failures == 0 else BrokerStatus.DEGRADED
                    if health.consecutive_failures > 0:
                        health.consecutive_failures = max(0, health.consecutive_failures - 1)
                else:
                    health.consecutive_failures += 1
                    if health.consecutive_failures >= 3:
                        health.status = BrokerStatus.UNHEALTHY

            except Exception as e:
                health.latency_ms = (time.time() - start) * 1000
                health.consecutive_failures += 1
                health.last_check = time.time()
                health.error_message = str(e)[:200]
                if health.consecutive_failures >= 3:
                    health.status = BrokerStatus.UNHEALTHY

        # If active broker became unhealthy, switch
        active_health = self._health.get(self._active_broker)
        if active_health and not active_health.is_available:
            old = self._active_broker
            self._select_best_broker()
            if self._active_broker != old:
                logger.warning(
                    f"Failover: {old.value} unhealthy, switched to {self._active_broker.value}"
                )

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self):
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.shutdown()
