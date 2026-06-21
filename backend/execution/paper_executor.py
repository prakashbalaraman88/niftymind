"""
NiftyMind Paper Trading Executor
================================
Simulates trade execution with realistic fills, slippage, and P&L tracking.

CRITICAL: Complete rebuild with proper Black-Scholes options pricing and
realistic slippage model. Integrates with options_pricer.py and slippage_model.py.

Features:
- place_order, cancel_order, get_positions, get_pnl API
- Realistic fill prices with SlippageModel
- Virtual position tracking with proper mark-to-market
- Order lifecycle: PENDING -> FILLED -> EXITED
- Stop-loss and target simulation
- MIS (intraday) and NRML (overnight) product type support
- Partial exit support via TrailingStopManager
- Position recovery from database on startup
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, time
from enum import Enum
from typing import Any, Optional

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS, NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE
from agents.db_logger import log_trade_event, log_audit, upsert_trade
from execution.trailing_stop import TrailingStopManager, TradePosition
from performance.charges import net_pnl as compute_net_pnl

# CRITICAL FIX: Import proper pricing and slippage engines
from execution.options_pricer import (
    BlackScholesPricer,
    OptionsPnLCalculator,
    ImpliedVolatility,
    DEFAULT_RISK_FREE_RATE,
)
from execution.slippage_model import (
    SlippageModel,
    OrderSide,
    OrderType,
)

logger = logging.getLogger("niftymind.paper_executor")

IST = timezone(timedelta(hours=5, minutes=30))

EOD_SQUARE_OFF = time(15, 15)
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

# Default lot sizes
LOT_SIZES = {
    "NIFTY": getattr(sys.modules.get("config"), "NIFTY_LOT_SIZE", 25),
    "BANKNIFTY": getattr(sys.modules.get("config"), "BANKNIFTY_LOT_SIZE", 15),
}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OrderStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    EXITED = "EXITED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ProductType(Enum):
    MIS = "MIS"      # Intraday (auto square-off at EOD)
    NRML = "NRML"    # Normal/overnight
    CNC = "CNC"      # Cash and carry (equity)
    BO = "BO"        # Bracket order
    CO = "CO"        # Cover order


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class VirtualOrder:
    """Represents a virtual order in the paper trading system."""
    order_id: str
    trade_id: str
    symbol: str
    underlying: str
    direction: str
    quantity: int
    filled_quantity: int = 0
    pending_quantity: int = 0
    price: float = 0.0
    trigger_price: Optional[float] = None
    order_type: str = "MARKET"
    product_type: str = "MIS"
    status: OrderStatus = OrderStatus.PENDING
    entry_time: str = ""
    is_options: bool = False
    strike: Optional[float] = None
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    iv: Optional[float] = None
    sl_price: Optional[float] = None
    target_price: Optional[float] = None


@dataclass
class VirtualPosition:
    """Represents a virtual open position."""
    trade_id: str
    symbol: str
    underlying: str
    direction: str
    quantity: int
    original_quantity: int
    entry_price: float
    entry_index_price: float
    entry_time: str
    trade_type: str
    product_type: str
    status: OrderStatus = OrderStatus.OPEN
    is_options: bool = False
    strike: Optional[float] = None
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    iv: float = 0.18
    delta: float = 0.5
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    peak_pnl: float = 0.0
    trough_pnl: float = 0.0
    greeks: dict = field(default_factory=dict)
    sl_price: float = 0.0
    target_price: float = 0.0
    exit_pending: bool = False


# ---------------------------------------------------------------------------
# Paper Executor
# ---------------------------------------------------------------------------

class PaperExecutor:
    """Paper trading executor with realistic fill simulation.

    Integrates:
    - BlackScholesPricer: proper options pricing
    - SlippageModel: realistic fill price estimation
    - TrailingStopManager: trailing stop and partial exits
    """

    def __init__(self, redis_publisher):
        self.publisher = redis_publisher
        self._positions: dict[str, VirtualPosition] = {}
        self._orders: dict[str, VirtualOrder] = {}
        self._latest_prices: dict[str, float] = {}
        self._latest_iv: dict[str, float] = {}
        self._fills: list[dict] = []
        self._daily_pnl: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._trailing_mgr = TrailingStopManager(capital=100000)
        self._trade_positions: dict[str, TradePosition] = {}
        self._last_reset_date: str | None = None
        self._partial_pnl: dict[str, float] = {}
        self._option_premiums: dict[tuple, float] = {}
        self._trailing_update_running: bool = False

        # CRITICAL FIX: Realistic slippage model
        self._slippage_model = SlippageModel(enable_stochastic=True)
        self._pnl_calculator = OptionsPnLCalculator(risk_free_rate=DEFAULT_RISK_FREE_RATE)

    # ---- Daily reset -------------------------------------------------------

    def _reset_daily_if_needed(self):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._daily_pnl = 0.0
            self._last_reset_date = today
            logger.info(f"Paper executor daily reset: PnL zeroed for {today}")

    # ---- Position recovery -------------------------------------------------

    def _recover_open_positions(self):
        """Recover OPEN positions from DB on startup so trades survive restarts."""
        try:
            from agents.db_logger import _get_conn, replay_wal
            replay_wal()
            conn = _get_conn()
            if not conn:
                logger.warning("Cannot recover positions -- DB unavailable")
                return
            cur = conn.cursor()
            cur.execute(
                "SELECT trade_id, symbol, underlying, direction, quantity, entry_price, "
                "trade_type, consensus_score, entry_time FROM trades WHERE status = 'OPEN'"
            )
            rows = cur.fetchall()
            conn.close()
            for row in rows:
                trade_id, symbol, underlying, direction, qty, entry_price, trade_type, score, entry_time = row
                entry_px = float(entry_price) if entry_price else 0

                # Try to parse strike/option type from symbol
                strike, opt_type = self._parse_option_symbol(symbol)
                is_options = strike is not None

                self._positions[trade_id] = VirtualPosition(
                    trade_id=trade_id,
                    symbol=symbol,
                    underlying=underlying,
                    direction=direction,
                    quantity=qty,
                    original_quantity=qty,
                    entry_price=entry_px,
                    entry_index_price=0.0,
                    entry_time=str(entry_time) if entry_time else datetime.now(IST).isoformat(),
                    trade_type=trade_type or "INTRADAY",
                    product_type="MIS",
                    status=OrderStatus.OPEN,
                    is_options=is_options,
                    strike=strike,
                    option_type=opt_type,
                    iv=DEFAULT_RISK_FREE_RATE if is_options else 0.18,
                    delta=0.5,
                )
                logger.info(f"Recovered position: {trade_id} {direction} {underlying} x{qty} @ {entry_price}")
            if rows:
                logger.info(f"Recovered {len(rows)} open positions from DB")
        except Exception as e:
            logger.error(f"Position recovery failed: {e}")

    @staticmethod
    def _parse_option_symbol(symbol: str) -> tuple[Optional[float], Optional[str]]:
        """Parse strike and option type from symbol like 'NIFTY25JUN25000CE'."""
        try:
            symbol = symbol.upper().replace(" ", "")
            if "CE" in symbol:
                opt_type = "CE"
                num_part = symbol.split("CE")[0]
            elif "PE" in symbol:
                opt_type = "PE"
                num_part = symbol.split("PE")[0]
            else:
                return None, None

            # Extract numeric strike from end of num_part
            digits = ""
            for ch in reversed(num_part):
                if ch.isdigit():
                    digits = ch + digits
                else:
                    break
            if digits:
                return float(digits), opt_type
            return None, None
        except Exception:
            return None, None

    # ---- Lifecycle ---------------------------------------------------------

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Paper Executor starting (BS Pricing v2)")
        self._recover_open_positions()
        pubsub = await self.publisher.subscribe("trade_executions", "ticks", "options_chain")

        try:
            while not shutdown_event.is_set():
                try:
                    message = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue

                if message is None or message["type"] != "message":
                    continue

                try:
                    data = json.loads(message["data"])
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()

                    if REDIS_CHANNELS["ticks"] in channel:
                        await self._update_price(data)
                    elif REDIS_CHANNELS["options_chain"] in channel:
                        self._update_option_premiums(data)
                    elif REDIS_CHANNELS["trade_executions"] in channel:
                        await self._handle_execution_event(data)

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.error(f"Paper executor error: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Paper Executor cancelled")
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            logger.info("Paper Executor stopped")

    _SYMBOL_TO_UNDERLYING = {
        "NIFTY 50": "NIFTY",
        "NIFTY": "NIFTY",
        "NIFTY-FUT": "NIFTY",
        "BANKNIFTY": "BANKNIFTY",
        "BANKNIFTY-FUT": "BANKNIFTY",
    }

    @staticmethod
    def _is_long(direction: str) -> bool:
        return direction.upper() in ("BULLISH", "LONG", "BUY")

    # ---- Price updates -----------------------------------------------------

    def _update_option_premiums(self, data: dict):
        """Track live option premiums and IVs from options chain feed."""
        underlying = data.get("underlying", "")
        for opt in data.get("options", []):
            strike = opt.get("strike")
            option_type = opt.get("option_type")
            ltp = opt.get("ltp", 0)
            iv = opt.get("iv") or opt.get("implied_volatility")
            if underlying and strike and option_type and ltp and ltp > 0:
                self._option_premiums[(underlying, float(strike), option_type)] = float(ltp)
            if iv and iv > 0:
                self._latest_iv[f"{underlying}_{strike}_{option_type}"] = float(iv)

    async def _update_price(self, tick: dict):
        """Handle price tick updates and trigger trailing stop checks."""
        symbol = tick.get("symbol", "")
        price = tick.get("ltp") or tick.get("last_price") or tick.get("close")
        if symbol and price:
            p = float(price)
            self._latest_prices[symbol] = p
            underlying = tick.get("underlying") or self._SYMBOL_TO_UNDERLYING.get(symbol, "")
            if underlying:
                self._latest_prices[underlying] = p

        # Capture IV from tick if available
        iv = tick.get("iv") or tick.get("implied_volatility")
        if iv:
            self._latest_iv[symbol] = float(iv)
            underlying = tick.get("underlying")
            if underlying:
                self._latest_iv[underlying] = float(iv)

        # Single-flight trailing stop update
        if self._trade_positions and not self._trailing_update_running:
            self._trailing_update_running = True
            try:
                await self._run_trailing_stop_updates()
            finally:
                self._trailing_update_running = False

    # ========================================================================
    # CRITICAL FIX: Proper Black-Scholes Option Premium Estimation
    # ========================================================================

    def _estimate_option_premium(self, position: VirtualPosition | dict) -> float:
        """Current premium for an options position using Black-Scholes.

        CRITICAL FIX: Replaced naive `entry_premium + index_move * delta`
        with full Black-Scholes re-pricing.

        Hierarchy:
        1. Live options chain LTP for exact strike+type
        2. Black-Scholes calculation from spot, strike, TTE, IV
        3. Legacy delta-based fallback
        """
        # Handle both VirtualPosition and dict
        if isinstance(position, VirtualPosition):
            underlying = position.underlying
            entry_premium = position.entry_price
            strike = position.strike
            option_type = position.option_type
            entry_index = position.entry_index_price
            expiry = position.expiry
            iv = position.iv
        else:
            underlying = position["underlying"]
            entry_premium = position["entry_price"]
            strike = position.get("strike")
            option_type = position.get("option_type")
            entry_index = position.get("entry_index_price", 0)
            expiry = position.get("expiry")
            iv = position.get("iv")

        # Level 1: Live options chain premium
        if strike and option_type:
            live = self._option_premiums.get((underlying, float(strike), option_type))
            if live and live > 0:
                return live

        # Level 2: Black-Scholes pricing
        index_price = self._latest_prices.get(underlying, 0)
        if index_price > 0 and strike and option_type:
            # Resolve IV
            bs_iv = iv
            if bs_iv is None or bs_iv <= 0:
                bs_iv = self._latest_iv.get(f"{underlying}_{strike}_{option_type}")
            if bs_iv is None or bs_iv <= 0:
                bs_iv = self._latest_iv.get(underlying)
            if bs_iv is None or bs_iv <= 0:
                bs_iv = 0.18  # default

            # Calculate TTE
            tte = self._calculate_tte(expiry)
            if tte > 0:
                try:
                    result = BlackScholesPricer.price(
                        spot=index_price,
                        strike=float(strike),
                        time_to_expiry=tte,
                        volatility=float(bs_iv),
                        risk_free_rate=DEFAULT_RISK_FREE_RATE,
                        option_type=option_type,
                    )
                    return result.premium
                except (ValueError, OverflowError) as e:
                    logger.debug(f"BS pricing failed: {e}")

        # Level 3: Legacy fallback
        if index_price <= 0 or entry_index <= 0:
            return entry_premium

        index_move = index_price - entry_index
        if isinstance(position, VirtualPosition):
            is_long = self._is_long(position.direction)
        else:
            is_long = position["direction"].upper() in ("BULLISH", "LONG", "BUY")
        if not is_long:
            index_move = -index_move

        if isinstance(position, VirtualPosition):
            delta = position.delta or 0.5
        else:
            delta = float(position.get("delta", 0.5) or 0.5)
        return max(0.05, entry_premium + index_move * delta)

    def _calculate_tte(self, expiry: Optional[str]) -> float:
        """Calculate time to expiry in years."""
        if expiry:
            try:
                expiry_dt = datetime.fromisoformat(expiry)
                if expiry_dt.tzinfo is None:
                    expiry_dt = expiry_dt.replace(tzinfo=IST)
            except (ValueError, TypeError):
                expiry_dt = self._estimate_expiry(expiry)
        else:
            expiry_dt = self._estimate_expiry_from_now()

        now = datetime.now(IST)
        tte_seconds = (expiry_dt - now).total_seconds()
        return max(0.0, tte_seconds / (365.25 * 24 * 3600))

    @staticmethod
    def _estimate_expiry(expiry_str: str) -> datetime:
        try:
            date_part = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
            return date_part.replace(hour=15, minute=30, second=0, tzinfo=IST)
        except (ValueError, TypeError):
            return PaperExecutor._estimate_expiry_from_now()

    @staticmethod
    def _estimate_expiry_from_now() -> datetime:
        now = datetime.now(IST)
        days_until_thursday = (3 - now.weekday()) % 7
        if days_until_thursday == 0 and now.hour >= 15 and now.minute >= 30:
            days_until_thursday = 7
        expiry = now + timedelta(days=max(1, days_until_thursday))
        return expiry.replace(hour=15, minute=30, second=0, microsecond=0)

    def _current_value(self, position: VirtualPosition | dict) -> float | None:
        """Current position value: premium for options, spot for index."""
        if isinstance(position, VirtualPosition):
            is_options = position.is_options
        else:
            is_options = position.get("is_options", False)

        if is_options:
            return self._estimate_option_premium(position)
        if isinstance(position, VirtualPosition):
            return self._latest_prices.get(position.underlying)
        return self._latest_prices.get(position["underlying"])

    # ---- Greeks calculation -------------------------------------------------

    def _calculate_position_greeks(self, position: VirtualPosition) -> dict:
        """Calculate Greeks for a position using Black-Scholes."""
        if not position.is_options:
            is_long = self._is_long(position.direction)
            return {
                "delta": 1.0 if is_long else -1.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "rho": 0.0,
            }

        underlying_price = self._latest_prices.get(position.underlying)
        if not underlying_price or not position.strike or not position.option_type:
            return {"delta": position.delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        iv = position.iv or 0.18
        tte = self._calculate_tte(position.expiry)

        if tte <= 0:
            return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        try:
            result = BlackScholesPricer.price(
                spot=underlying_price,
                strike=float(position.strike),
                time_to_expiry=tte,
                volatility=float(iv),
                risk_free_rate=DEFAULT_RISK_FREE_RATE,
                option_type=position.option_type,
            )
            return result.greeks.to_dict()
        except (ValueError, OverflowError):
            return {"delta": position.delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    # ========================================================================
    # Public API: place_order, cancel_order, get_positions, get_pnl
    # ========================================================================

    def place_order(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        order_type: str = "MARKET",
        product_type: str = "MIS",
        price: float = 0.0,
        trigger_price: Optional[float] = None,
        underlying: str = "NIFTY",
        is_options: bool = False,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
        expiry: Optional[str] = None,
        iv: Optional[float] = None,
        sl_points: Optional[float] = None,
        target_points: Optional[float] = None,
        **kwargs,
    ) -> dict:
        """Place a virtual order and return order details.

        Parameters
        ----------
        symbol : str
            Trading symbol
        direction : str
            "BUY" or "SELL"
        quantity : int
            Order quantity
        order_type : str
            "MARKET", "LIMIT", "SL", "SL-M"
        product_type : str
            "MIS" (intraday) or "NRML" (overnight)
        price : float
            Limit price (for limit orders)
        trigger_price : float | None
            Trigger price for SL orders
        underlying, is_options, strike, option_type, expiry, iv :
            Option-specific parameters
        sl_points, target_points :
            Stop-loss and target in points

        Returns
        -------
        dict with order_id, status, fill_price, etc.
        """
        self._reset_daily_if_needed()
        order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
        trade_id = f"TRADE-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(IST)

        # Check market hours
        current_time = now.time()
        if not (MARKET_OPEN <= current_time <= MARKET_CLOSE):
            logger.warning(f"Order {order_id} rejected: outside market hours")
            return {
                "order_id": order_id,
                "trade_id": trade_id,
                "status": OrderStatus.REJECTED.value,
                "reject_reason": "MARKET_CLOSED",
            }

        # Get current market price
        market_price = self._latest_prices.get(symbol) or self._latest_prices.get(underlying, 0)
        if market_price <= 0 and price > 0:
            market_price = price
        if market_price <= 0:
            logger.warning(f"Order {order_id} rejected: no price for {symbol}/{underlying}")
            return {
                "order_id": order_id,
                "trade_id": trade_id,
                "status": OrderStatus.REJECTED.value,
                "reject_reason": "NO_PRICE",
            }

        # Determine fill price with slippage
        side_enum = OrderSide.BUY if direction.upper() in ("BUY", "BULLISH", "LONG") else OrderSide.SELL
        order_type_enum = self._parse_order_type(order_type)

        # CRITICAL FIX: Use SlippageModel for realistic fills
        slippage_estimate = self._slippage_model.estimate_slippage(
            market_price=market_price,
            quantity=quantity,
            side=side_enum,
            order_type=order_type_enum,
            underlying=underlying,
            spot=self._latest_prices.get(underlying, market_price),
            strike=strike,
            option_type=option_type,
            is_future=not is_options and "FUT" in symbol.upper(),
            is_index=not is_options and "FUT" not in symbol.upper() and not is_options,
            current_iv=iv or self._latest_iv.get(underlying),
            current_time=now,
        )
        fill_price = slippage_estimate.fill_price

        # For limit orders, ensure fill doesn't exceed limit
        if order_type_enum == OrderType.LIMIT and price > 0:
            if side_enum == OrderSide.BUY and fill_price > price:
                fill_price = price  # Can't pay more than limit
            elif side_enum == OrderSide.SELL and fill_price < price:
                fill_price = price  # Can't receive less than limit

        fill_price = round(fill_price, 2)

        # Create order record
        order = VirtualOrder(
            order_id=order_id,
            trade_id=trade_id,
            symbol=symbol,
            underlying=underlying,
            direction=direction,
            quantity=quantity,
            filled_quantity=quantity,
            pending_quantity=0,
            price=fill_price,
            trigger_price=trigger_price,
            order_type=order_type,
            product_type=product_type,
            status=OrderStatus.FILLED,
            entry_time=now.isoformat(),
            is_options=is_options,
            strike=strike,
            option_type=option_type,
            expiry=expiry,
            iv=iv,
        )
        self._orders[order_id] = order

        # For entry orders (BUY), create a position
        if direction.upper() in ("BUY", "BULLISH", "LONG"):
            self._create_position_from_order(
                order, fill_price, sl_points, target_points, **kwargs
            )

        logger.info(
            f"Paper order placed: {order_id} {direction} {symbol} x{quantity} "
            f"@ Rs.{fill_price:,.2f} ({order_type}/{product_type})"
        )

        return {
            "order_id": order_id,
            "trade_id": trade_id,
            "status": OrderStatus.FILLED.value,
            "symbol": symbol,
            "direction": direction,
            "quantity": quantity,
            "filled_quantity": quantity,
            "price": fill_price,
            "slippage": slippage_estimate.to_dict(),
            "timestamp": now.isoformat(),
        }

    def cancel_order(self, order_id: str) -> dict:
        """Cancel a pending order.

        Returns
        -------
        dict with cancellation status
        """
        order = self._orders.get(order_id)
        if not order:
            return {"order_id": order_id, "status": "NOT_FOUND"}

        if order.status not in (OrderStatus.PENDING, OrderStatus.OPEN):
            return {
                "order_id": order_id,
                "status": "ALREADY_FILLED",
                "filled_quantity": order.filled_quantity,
            }

        order.status = OrderStatus.CANCELLED
        logger.info(f"Paper order cancelled: {order_id}")
        return {
            "order_id": order_id,
            "status": OrderStatus.CANCELLED.value,
            "cancelled_quantity": order.pending_quantity,
        }

    def get_positions(self) -> list[dict]:
        """Get all open virtual positions with P&L and Greeks."""
        result = []
        for pos in self._positions.values():
            if pos.status not in (OrderStatus.OPEN, OrderStatus.PARTIAL):
                continue

            entry_price = pos.entry_price
            current_value = self._current_value(pos)
            if current_value is None:
                current_value = entry_price

            pos.current_price = round(current_value, 2)

            # CRITICAL FIX: Proper P&L calculation
            if pos.is_options or self._is_long(pos.direction):
                pos.unrealized_pnl = round((current_value - entry_price) * pos.quantity, 2)
            else:
                pos.unrealized_pnl = round((entry_price - current_value) * pos.quantity, 2)

            # Calculate and store Greeks
            pos.greeks = self._calculate_position_greeks(pos)
            pos.peak_pnl = max(pos.peak_pnl, pos.unrealized_pnl)
            pos.trough_pnl = min(pos.trough_pnl, pos.unrealized_pnl)

            result.append({
                "trade_id": pos.trade_id,
                "symbol": pos.symbol,
                "underlying": pos.underlying,
                "direction": pos.direction,
                "quantity": pos.quantity,
                "original_quantity": pos.original_quantity,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
                "realized_pnl": pos.realized_pnl,
                "peak_pnl": pos.peak_pnl,
                "trough_pnl": pos.trough_pnl,
                "entry_time": pos.entry_time,
                "trade_type": pos.trade_type,
                "product_type": pos.product_type,
                "is_options": pos.is_options,
                "strike": pos.strike,
                "option_type": pos.option_type,
                "expiry": pos.expiry,
                "iv": pos.iv,
                "greeks": pos.greeks,
                "sl_price": pos.sl_price,
                "target_price": pos.target_price,
            })
        return result

    def get_pnl(self) -> dict:
        """Get comprehensive P&L report."""
        positions = self.get_positions()
        total_unrealized = sum(p["unrealized_pnl"] for p in positions)
        total_realized = sum(p["realized_pnl"] for p in positions)

        win_rate = (self._winning_trades / self._total_trades * 100) if self._total_trades > 0 else 0

        # Aggregate Greeks
        agg_delta = sum(p["greeks"].get("delta", 0) * p["quantity"] for p in positions if p.get("greeks"))
        agg_gamma = sum(p["greeks"].get("gamma", 0) * p["quantity"] for p in positions if p.get("greeks"))
        agg_theta = sum(p["greeks"].get("theta", 0) * p["quantity"] for p in positions if p.get("greeks"))
        agg_vega = sum(p["greeks"].get("vega", 0) * p["quantity"] for p in positions if p.get("greeks"))

        return {
            "mode": "paper",
            "daily_pnl": round(self._daily_pnl, 2),
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(win_rate, 1),
            "open_positions": len(positions),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "total_realized_pnl": round(total_realized, 2),
            "aggregate_greeks": {
                "delta": round(agg_delta, 4),
                "gamma": round(agg_gamma, 6),
                "theta": round(agg_theta, 4),
                "vega": round(agg_vega, 4),
            },
            "positions": positions,
        }

    # ---- Helpers -----------------------------------------------------------

    @staticmethod
    def _parse_order_type(order_type_str: str) -> OrderType:
        ot = order_type_str.upper()
        if ot in ("MARKET", "MKT"):
            return OrderType.MARKET
        elif ot in ("LIMIT", "LMT"):
            return OrderType.LIMIT
        elif ot in ("SL", "STOP_LOSS", "SL-L"):
            return OrderType.STOP_LOSS
        elif ot in ("SL-M", "SLM"):
            return OrderType.SL_MARKET
        return OrderType.MARKET

    def _create_position_from_order(
        self,
        order: VirtualOrder,
        fill_price: float,
        sl_points: Optional[float] = None,
        target_points: Optional[float] = None,
        **kwargs,
    ):
        """Create a VirtualPosition from a filled entry order."""
        trade_type = kwargs.get("trade_type", "INTRADAY")
        direction = order.direction
        is_options = order.is_options

        # Calculate SL and target
        if sl_points is not None:
            if self._is_long(direction):
                sl_price = fill_price - sl_points
            else:
                sl_price = fill_price + sl_points
        else:
            sl_pct = 0.30 if is_options else 0.02
            sl_offset = fill_price * sl_pct
            sl_price = (fill_price - sl_offset) if self._is_long(direction) else (fill_price + sl_offset)

        if target_points is not None:
            if self._is_long(direction):
                target_price = fill_price + target_points
            else:
                target_price = fill_price - target_points
        else:
            tgt_pct = 0.50 if is_options else 0.04
            target_offset = fill_price * tgt_pct
            target_price = (fill_price + target_offset) if self._is_long(direction) else (fill_price - target_offset)

        # Resolve IV
        iv = order.iv
        if iv is None or iv <= 0:
            iv = self._latest_iv.get(order.underlying, 0.18)

        pos = VirtualPosition(
            trade_id=order.trade_id,
            symbol=order.symbol,
            underlying=order.underlying,
            direction=direction,
            quantity=order.quantity,
            original_quantity=order.quantity,
            entry_price=fill_price,
            entry_index_price=self._latest_prices.get(order.underlying, 0),
            entry_time=order.entry_time,
            trade_type=trade_type,
            product_type=order.product_type,
            status=OrderStatus.OPEN,
            is_options=is_options,
            strike=order.strike,
            option_type=order.option_type,
            expiry=order.expiry,
            iv=iv,
            delta=kwargs.get("delta", 0.5),
            sl_price=round(max(0.05, sl_price), 2),
            target_price=round(max(0.05, target_price), 2),
        )
        self._positions[order.trade_id] = pos

        # Create TradePosition for trailing stop
        atr = float(kwargs.get("atr", 0))
        premium_space_direction = "BULLISH" if is_options else direction
        if self._is_long(premium_space_direction):
            trade_sl = fill_price - (sl_points or (fill_price * 0.30 if is_options else fill_price * 0.02))
        else:
            trade_sl = fill_price + (sl_points or (fill_price * 0.30 if is_options else fill_price * 0.02))

        trade_pos = TradePosition(
            trade_id=order.trade_id,
            entry_price=fill_price,
            sl_price=round(max(0.05, trade_sl), 2),
            direction=premium_space_direction,
            quantity=order.quantity,
            strategy=trade_type,
            trail_atr=atr,
        )
        self._trade_positions[order.trade_id] = trade_pos

        # Persist to DB
        upsert_trade(
            trade_id=order.trade_id,
            symbol=order.symbol,
            underlying=order.underlying,
            direction=direction,
            quantity=order.quantity,
            trade_type=trade_type,
            consensus_score=float(kwargs.get("confidence", 0)),
            entry_price=fill_price,
            entry_time=order.entry_time,
            status="OPEN",
        )

        log_trade_event(
            trade_id=order.trade_id,
            event="ENTRY",
            status="OPEN",
            price=fill_price,
            quantity=order.quantity,
            details={
                "executor": "paper",
                "order_id": order.order_id,
                "slippage": kwargs.get("slippage_info", {}),
                "trade_type": trade_type,
                "is_options": is_options,
                "product_type": order.product_type,
            },
        )

    # ========================================================================
    # Event-based execution (from Redis trade_execution channel)
    # ========================================================================

    async def _handle_execution_event(self, data: dict):
        event = data.get("event", "")
        if event == "RISK_APPROVED":
            await self._execute_entry(data)
        elif event == "EXIT_ORDER":
            await self._execute_exit(data)

    async def _execute_entry(self, data: dict):
        """Execute a paper entry from a RISK_APPROVED signal."""
        self._reset_daily_if_needed()
        trade_id = data.get("trade_id", f"PAPER-{uuid.uuid4().hex[:8]}")
        underlying = data.get("underlying", "NIFTY")
        direction = data.get("direction", "BULLISH")
        quantity = int(data.get("quantity", 0))
        trade_type = data.get("trade_type", "INTRADAY")
        product_type = data.get("product_type", "MIS")

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        if quantity <= 0:
            quantity = int(data.get("supporting_data", {}).get("quantity", 0)) or lot_size

        # Resolve symbol
        supporting = data.get("supporting_data", {})
        selected_strike = supporting.get("selected_strike")
        symbol = data.get("symbol") or supporting.get("symbol") or f"{underlying} OPT"

        # Resolve fill price
        if selected_strike and selected_strike.get("ltp", 0) > 0:
            fill_price = float(selected_strike["ltp"])
        elif supporting.get("entry_premium", 0) > 0:
            fill_price = float(supporting["entry_premium"])
        else:
            fill_price = self._latest_prices.get(underlying, 0)
            if fill_price <= 0:
                logger.error(f"No price for {underlying} -- cannot execute {trade_id}")
                return

        is_options = selected_strike is not None or supporting.get("entry_premium", 0) > 0

        # CRITICAL FIX: Use SlippageModel instead of fixed 0.05% slippage
        side = OrderSide.BUY if self._is_long(direction) else OrderSide.SELL
        order_type_enum = OrderType.MARKET
        spot = self._latest_prices.get(underlying, fill_price)

        slippage_est = self._slippage_model.estimate_slippage(
            market_price=fill_price,
            quantity=quantity,
            side=side,
            order_type=order_type_enum,
            underlying=underlying,
            spot=spot,
            strike=selected_strike.get("strike") if selected_strike else None,
            option_type=selected_strike.get("option_type") if selected_strike else None,
            is_future=not is_options and "FUT" in symbol.upper(),
            is_index=not is_options,
            current_iv=self._latest_iv.get(underlying),
        )
        fill_price = slippage_est.fill_price
        fill_price = round(fill_price, 2)

        # Resolve strike and option type
        strike = (selected_strike or {}).get("strike")
        option_type = (selected_strike or {}).get("option_type")
        expiry = (selected_strike or {}).get("expiry") or supporting.get("expiry")
        iv = (selected_strike or {}).get("iv") or self._latest_iv.get(underlying, 0.18)

        # Create position
        pos = VirtualPosition(
            trade_id=trade_id,
            symbol=symbol,
            underlying=underlying,
            direction=direction,
            quantity=quantity,
            original_quantity=quantity,
            entry_price=fill_price,
            entry_index_price=spot,
            entry_time=datetime.now(IST).isoformat(),
            trade_type=trade_type,
            product_type=product_type,
            status=OrderStatus.OPEN,
            is_options=is_options,
            strike=strike,
            option_type=option_type,
            expiry=expiry,
            iv=iv if iv and iv > 0 else 0.18,
            delta=float((selected_strike or {}).get("delta", 0.5) or 0.5),
        )
        self._positions[trade_id] = pos

        # Create trailing stop position
        sl_points = float(supporting.get("sl_points", data.get("sl_points", 20)))
        atr = float(supporting.get("atr", data.get("atr", 0)))
        premium_space_direction = "BULLISH" if is_options else direction
        if self._is_long(premium_space_direction):
            sl_price = fill_price - sl_points
        else:
            sl_price = fill_price + sl_points
        trade_pos = TradePosition(
            trade_id=trade_id,
            entry_price=fill_price,
            sl_price=round(max(0.05, sl_price), 2),
            direction=premium_space_direction,
            quantity=quantity,
            strategy=trade_type,
            trail_atr=atr,
        )
        self._trade_positions[trade_id] = trade_pos

        # Persist
        upsert_trade(
            trade_id=trade_id,
            symbol=symbol,
            underlying=underlying,
            direction=direction,
            quantity=quantity,
            trade_type=trade_type,
            consensus_score=float(data.get("confidence", 0)),
            entry_price=fill_price,
            entry_time=datetime.now(IST).isoformat(),
            status="OPEN",
        )

        log_trade_event(
            trade_id=trade_id,
            event="ENTRY",
            status="OPEN",
            price=fill_price,
            quantity=quantity,
            details={
                "executor": "paper",
                "slippage": slippage_est.to_dict(),
                "trade_type": trade_type,
                "is_options": is_options,
                "product_type": product_type,
            },
        )
        log_audit(
            event_type="PAPER_ENTRY",
            source="paper_executor",
            message=f"Paper fill: {direction} {underlying} x{quantity} @ Rs.{fill_price:,.2f}",
            trade_id=trade_id,
        )

        await self.publisher.publish_trade_execution({
            "event": "ENTRY",
            "trade_id": trade_id,
            "underlying": underlying,
            "direction": direction,
            "quantity": quantity,
            "price": fill_price,
            "trade_type": trade_type,
            "executor": "paper",
            "is_options": is_options,
            "delta": pos.delta,
            "entry_index_price": pos.entry_index_price,
            "timestamp": datetime.now(IST).isoformat(),
        })

        logger.info(f"Paper ENTRY: {trade_id} {direction} {underlying} x{quantity} @ Rs.{fill_price:,.2f}")

    # ---- Exit pricing ------------------------------------------------------

    def _exit_price_and_gross(
        self,
        position: VirtualPosition | dict,
        exit_qty: int,
        raw_exit_price: float | None = None,
    ) -> tuple[float, float]:
        """Exit price with slippage and gross P&L.

        CRITICAL FIX: Uses SlippageModel for realistic exit fills.
        """
        if isinstance(position, VirtualPosition):
            entry_price = position.entry_price
            is_options = position.is_options
            direction = position.direction
            underlying = position.underlying
            strike = position.strike
            option_type = position.option_type
            qty_for_impact = exit_qty
        else:
            entry_price = position["entry_price"]
            is_options = position.get("is_options", False)
            direction = position["direction"]
            underlying = position.get("underlying", "NIFTY")
            strike = position.get("strike")
            option_type = position.get("option_type")
            qty_for_impact = exit_qty

        if raw_exit_price is None:
            if is_options and isinstance(position, VirtualPosition):
                raw_exit_price = self._estimate_option_premium(position)
            elif is_options:
                raw_exit_price = self._estimate_option_premium(position)
            else:
                raw_exit_price = self._latest_prices.get(underlying, entry_price)

        if raw_exit_price is None:
            raw_exit_price = entry_price

        # CRITICAL FIX: Realistic exit slippage
        exit_side = OrderSide.SELL if self._is_long(direction) else OrderSide.BUY
        slippage_est = self._slippage_model.estimate_slippage(
            market_price=raw_exit_price,
            quantity=qty_for_impact,
            side=exit_side,
            order_type=OrderType.MARKET,
            underlying=underlying,
            spot=self._latest_prices.get(underlying, raw_exit_price),
            strike=strike,
            option_type=option_type,
            is_future=not is_options,
            is_index=not is_options,
            current_iv=self._latest_iv.get(underlying),
        )
        exit_price = slippage_est.fill_price
        exit_price = round(max(0.05, exit_price), 2)

        # P&L calculation
        if is_options or self._is_long(direction):
            gross_pnl = (exit_price - entry_price) * exit_qty
        else:
            gross_pnl = (entry_price - exit_price) * exit_qty
        return exit_price, round(gross_pnl, 2)

    async def _execute_exit(self, data: dict):
        """Execute a paper exit from an EXIT_ORDER signal."""
        self._reset_daily_if_needed()
        trade_id = data.get("trade_id", "")
        exit_reason = data.get("exit_reason", "MANUAL")

        position = self._positions.get(trade_id)
        if not position:
            logger.warning(f"Exit requested for unknown position: {trade_id}")
            return

        underlying = position.underlying
        direction = position.direction
        quantity = position.quantity
        entry_price = position.entry_price
        is_options = position.is_options

        exit_price, gross_pnl = self._exit_price_and_gross(position, quantity)
        pnl, charges = compute_net_pnl(gross_pnl, entry_price, exit_price, quantity, is_options)

        prior_partial = self._partial_pnl.pop(trade_id, 0.0)
        total_trade_pnl = round(pnl + prior_partial, 2)

        trade_type = position.trade_type
        symbol = position.symbol

        self._daily_pnl += pnl
        self._total_trades += 1
        if total_trade_pnl > 0:
            self._winning_trades += 1

        del self._positions[trade_id]
        self._trade_positions.pop(trade_id, None)

        upsert_trade(
            trade_id=trade_id,
            symbol=symbol,
            underlying=underlying,
            direction=direction,
            quantity=position.original_quantity,
            trade_type=trade_type,
            consensus_score=0,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=total_trade_pnl,
            exit_reason=exit_reason,
            exit_time=datetime.now(IST).isoformat(),
            status="CLOSED",
        )

        log_trade_event(
            trade_id=trade_id,
            event=exit_reason,
            status="CLOSED",
            price=exit_price,
            quantity=quantity,
            pnl=pnl,
            details={
                "executor": "paper",
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_pnl": gross_pnl,
                "partial_pnl_realized": prior_partial,
                "total_trade_pnl": total_trade_pnl,
                "charges": charges["total"],
                "charges_breakdown": charges["breakdown"],
            },
        )
        log_audit(
            event_type="PAPER_EXIT",
            source="paper_executor",
            message=f"Paper exit: {trade_id} {exit_reason} PnL=Rs.{total_trade_pnl:,.2f}",
            trade_id=trade_id,
        )

        await self.publisher.publish_trade_execution({
            "event": exit_reason,
            "trade_id": trade_id,
            "underlying": underlying,
            "direction": direction,
            "quantity": quantity,
            "price": exit_price,
            "pnl": pnl,
            "executor": "paper",
            "timestamp": datetime.now(IST).isoformat(),
        })

        logger.info(f"Paper EXIT: {trade_id} {exit_reason} PnL=Rs.{total_trade_pnl:,.2f}")

        # Notify learning system
        try:
            await self.publisher.publish("trade_closed", {
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": total_trade_pnl,
                "exit_reason": exit_reason,
                "trade_type": trade_type,
                "market_regime": "NORMAL",
                "timestamp": datetime.now(IST).isoformat(),
            })
        except Exception as e:
            logger.warning(f"Failed to publish trade_closed: {e}")

    # ========================================================================
    # Trailing Stop Management
    # ========================================================================

    async def _run_trailing_stop_updates(self):
        """Run TrailingStopManager updates for all open positions."""
        for trade_id in list(self._trade_positions.keys()):
            trade_pos = self._trade_positions.get(trade_id)
            if trade_pos is None or trade_pos.remaining_quantity <= 0:
                continue

            position = self._positions.get(trade_id)
            if position is None:
                continue

            current_value = self._current_value(position)
            if current_value is None:
                continue

            current_atr = trade_pos.trail_atr if trade_pos.trail_atr > 0 else None
            actions = self._trailing_mgr.update(trade_pos, current_value, current_atr)

            time_action = self._trailing_mgr.check_time_exit(trade_pos)
            if time_action:
                actions.append(time_action)

            for action in actions:
                await self._process_trailing_action(action, position, current_value)

    async def _process_trailing_action(
        self, action: dict, position: VirtualPosition, current_value: float
    ):
        """Process a trailing stop action."""
        action_type = action.get("action", "")
        trade_id = action.get("trade_id", "")
        exit_qty = action.get("quantity", 0)
        reason = action.get("reason", action_type)

        if exit_qty <= 0:
            return

        if action_type == "PARTIAL_EXIT":
            exit_price, gross_pnl = self._exit_price_and_gross(
                position, exit_qty, raw_exit_price=current_value
            )
            pnl, charges = compute_net_pnl(
                gross_pnl, position.entry_price, exit_price, exit_qty, position.is_options
            )

            position.quantity -= exit_qty
            position.status = OrderStatus.PARTIAL if position.quantity > 0 else OrderStatus.EXITED
            self._daily_pnl += pnl
            self._partial_pnl[trade_id] = self._partial_pnl.get(trade_id, 0.0) + pnl

            target_idx = action.get("target_index", "?")
            log_trade_event(
                trade_id=trade_id,
                event=f"PARTIAL_EXIT_T{target_idx}",
                status="PARTIAL",
                price=exit_price,
                quantity=exit_qty,
                pnl=pnl,
                details={
                    "executor": "paper",
                    "reason": reason,
                    "remaining_qty": position.quantity,
                    "gross_pnl": gross_pnl,
                    "charges": charges["total"],
                    "charges_breakdown": charges["breakdown"],
                },
            )
            log_audit(
                event_type="PAPER_PARTIAL_EXIT",
                source="paper_executor",
                message=f"Paper partial exit: {trade_id} T{target_idx} qty={exit_qty} PnL=Rs.{pnl:,.2f}",
                trade_id=trade_id,
            )
            await self.publisher.publish_trade_execution({
                "event": f"PARTIAL_EXIT_T{target_idx}",
                "trade_id": trade_id,
                "underlying": position.underlying,
                "direction": position.direction,
                "quantity": exit_qty,
                "price": exit_price,
                "pnl": pnl,
                "executor": "paper",
                "reason": reason,
                "timestamp": datetime.now(IST).isoformat(),
            })
            logger.info(f"Paper PARTIAL EXIT: {trade_id} T{target_idx} qty={exit_qty} @ Rs.{exit_price:,.2f} PnL=Rs.{pnl:,.2f}")

            if position.quantity <= 0:
                await self._close_position_fully(trade_id, exit_price, reason)

        elif action_type in ("FULL_EXIT_SL", "FULL_EXIT_ILLIQUID", "TIME_EXIT", "EOD_EXIT"):
            await self._execute_exit({
                "trade_id": trade_id,
                "exit_reason": action_type,
            })

    async def _close_position_fully(self, trade_id: str, last_exit_price: float, reason: str):
        """Close a fully exited position."""
        position = self._positions.get(trade_id)
        if not position:
            return

        self._total_trades += 1
        trade_pnl = self._partial_pnl.pop(trade_id, 0.0)
        if trade_pnl > 0:
            self._winning_trades += 1

        del self._positions[trade_id]
        self._trade_positions.pop(trade_id, None)

        upsert_trade(
            trade_id=trade_id,
            symbol=position.symbol,
            underlying=position.underlying,
            direction=position.direction,
            quantity=position.original_quantity,
            trade_type=position.trade_type,
            consensus_score=0,
            entry_price=position.entry_price,
            exit_price=last_exit_price,
            pnl=round(trade_pnl, 2),
            exit_reason=reason,
            exit_time=datetime.now(IST).isoformat(),
            status="CLOSED",
        )

        await self.publisher.publish_trade_execution({
            "event": "EXIT",
            "trade_id": trade_id,
            "underlying": position.underlying,
            "direction": position.direction,
            "quantity": position.original_quantity,
            "price": last_exit_price,
            "pnl": round(trade_pnl, 2),
            "executor": "paper",
            "timestamp": datetime.now(IST).isoformat(),
        })

        try:
            await self.publisher.publish("trade_closed", {
                "trade_id": trade_id,
                "underlying": position.underlying,
                "direction": position.direction,
                "entry_price": position.entry_price,
                "exit_price": last_exit_price,
                "pnl": round(trade_pnl, 2),
                "exit_reason": reason,
                "trade_type": position.trade_type,
                "market_regime": "NORMAL",
                "timestamp": datetime.now(IST).isoformat(),
            })
        except Exception as e:
            logger.warning(f"Failed to publish trade_closed: {e}")

        logger.info(f"Paper position fully closed: {trade_id} PnL=Rs.{trade_pnl:,.2f}")

    # ========================================================================
    # Stop-Loss and Target Simulation
    # ========================================================================

    async def simulate_stop_loss_hit(self, trade_id: str) -> dict:
        """Simulate a stop-loss being hit for a position.

        Returns the exit details.
        """
        position = self._positions.get(trade_id)
        if not position:
            return {"error": "Position not found"}

        sl_price = position.sl_price
        if sl_price <= 0:
            return {"error": "No stop-loss set"}

        await self._execute_exit({
            "trade_id": trade_id,
            "exit_reason": "SL_HIT",
        })
        return {"trade_id": trade_id, "exit_reason": "SL_HIT", "trigger_price": sl_price}

    async def simulate_target_hit(self, trade_id: str) -> dict:
        """Simulate a target being hit for a position."""
        position = self._positions.get(trade_id)
        if not position:
            return {"error": "Position not found"}

        target_price = position.target_price
        if target_price <= 0:
            return {"error": "No target set"}

        await self._execute_exit({
            "trade_id": trade_id,
            "exit_reason": "TARGET_HIT",
        })
        return {"trade_id": trade_id, "exit_reason": "TARGET_HIT", "trigger_price": target_price}

    # ========================================================================
    # EOD Square-off
    # ========================================================================

    async def square_off_all_intraday(self) -> list[dict]:
        """Square off all MIS/intraday positions (called at EOD)."""
        results = []
        for trade_id, pos in list(self._positions.items()):
            if pos.product_type == "MIS" or pos.trade_type in ("SCALP", "INTRADAY"):
                await self._execute_exit({
                    "trade_id": trade_id,
                    "exit_reason": "EOD_CLOSE",
                })
                results.append({"trade_id": trade_id, "status": "SQUARED_OFF"})
        logger.info(f"EOD square-off: closed {len(results)} intraday positions")
        return results

    # ========================================================================
    # Backward-compatible API
    # ========================================================================

    def get_open_positions(self) -> list[dict]:
        """Backward-compatible: get open positions."""
        return self.get_positions()

    def get_stats(self) -> dict:
        """Backward-compatible: get stats."""
        pnl = self.get_pnl()
        return {
            "mode": "paper",
            "daily_pnl": pnl["daily_pnl"],
            "total_trades": pnl["total_trades"],
            "winning_trades": pnl["winning_trades"],
            "win_rate": pnl["win_rate"],
            "open_positions": pnl["open_positions"],
        }
