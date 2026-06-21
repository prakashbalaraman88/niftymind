"""
NiftyMind Position Tracker
==========================
Tracks open positions, monitors for exit conditions (SL / Target / EOD),
and publishes exit orders when conditions are met.

CRITICAL FIX (2025-06-21):
- Replaced naive `entry_price + index_move * delta` P&L calculation
- Now uses proper Black-Scholes options pricing from options_pricer.py
- Greeks (delta, gamma, theta, vega, rho) are properly calculated and tracked
- Premium-based P&L with time decay is correctly computed

Uses: options_pricer.BlackScholesPricer, options_pricer.OptionsPnLCalculator
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta, time
from typing import Optional

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS
from agents.db_logger import log_trade_event, log_audit

# CRITICAL FIX: Import proper Black-Scholes pricing engine
from execution.options_pricer import (
    BlackScholesPricer,
    OptionsPnLCalculator,
    Greeks,
    DEFAULT_RISK_FREE_RATE,
)

logger = logging.getLogger("niftymind.position_tracker")

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_CLOSE = time(15, 30)
EOD_SQUARE_OFF = time(15, 15)

# Default IV estimate for Nifty options (will be overridden by live data)
DEFAULT_IV: float = 0.18


class PositionTracker:
    """Tracks open positions with proper Black-Scholes mark-to-market."""

    def __init__(self, redis_publisher, executor):
        self.publisher = redis_publisher
        self.executor = executor
        self._positions: dict[str, dict] = {}
        self._latest_prices: dict[str, float] = {}
        self._latest_iv: dict[str, float] = {}  # symbol -> implied vol
        self._check_interval: float = 2.0
        self._broker_managed_exits: set[str] = set()
        self._pnl_calculator = OptionsPnLCalculator(
            risk_free_rate=DEFAULT_RISK_FREE_RATE
        )

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Position Tracker starting (Black-Scholes P&L v2)")
        pubsub = await self.publisher.subscribe("trade_executions", "ticks", "options_chain")

        monitor_task = asyncio.create_task(self._monitor_loop(shutdown_event))

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
                        self._update_price(data)
                    elif REDIS_CHANNELS["options_chain"] in channel:
                        self._update_option_chain(data)
                    elif REDIS_CHANNELS["trade_executions"] in channel:
                        self._handle_trade_event(data)

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.error(f"Position tracker error: {e}", exc_info=True)

        except asyncio.CancelledError:
            pass
        finally:
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            await pubsub.unsubscribe()
            await pubsub.aclose()
            logger.info("Position Tracker stopped")

    def _update_price(self, tick: dict):
        """Update latest price for a symbol."""
        symbol = tick.get("symbol", "")
        price = tick.get("ltp") or tick.get("last_price") or tick.get("close")
        if symbol and price:
            self._latest_prices[symbol] = float(price)

        underlying = tick.get("underlying", "")
        if underlying and price:
            self._latest_prices[underlying] = float(price)

        # Also capture IV if provided in tick
        iv = tick.get("iv") or tick.get("implied_volatility")
        if iv and symbol:
            self._latest_iv[symbol] = float(iv)

    def _update_option_chain(self, data: dict):
        """Update option chain data including live premiums and IVs."""
        underlying = data.get("underlying", "")
        for opt in data.get("options", []):
            strike = opt.get("strike")
            option_type = opt.get("option_type")
            ltp = opt.get("ltp", 0)
            iv = opt.get("iv") or opt.get("implied_volatility")

            key = f"{underlying}_{strike}_{option_type}"
            if ltp and ltp > 0:
                self._latest_prices[key] = float(ltp)
            if iv and iv > 0:
                self._latest_iv[key] = float(iv)

    def _handle_trade_event(self, data: dict):
        """Handle ENTRY / EXIT events for position tracking."""
        event = data.get("event", "")
        trade_id = data.get("trade_id", "")

        if event == "ENTRY":
            self._handle_entry(data)
        elif event in (
            "EXIT", "SL_HIT", "TARGET_HIT", "EOD_CLOSE", "MANUAL", "BRACKET_EXIT",
            "FULL_EXIT_SL", "FULL_EXIT_ILLIQUID", "TIME_EXIT", "EOD_EXIT",
            "MANUAL_CLOSE", "MANUAL_TEST",
        ) or event.startswith("PARTIAL_EXIT"):
            if trade_id in self._positions:
                del self._positions[trade_id]
            self._broker_managed_exits.discard(trade_id)

    def _handle_entry(self, data: dict):
        """Record a new position for tracking."""
        trade_id = data.get("trade_id", "")
        sl_price = data.get("sl_price")
        target_price = data.get("target_price")
        entry_price = float(data.get("price", 0))
        direction = data.get("direction", "BULLISH")
        executor = data.get("executor", "paper")
        variety = data.get("variety", "regular")

        broker_manages_sl_target = (executor == "kite" and variety == "bo")
        is_long = direction.upper() in ("BULLISH", "LONG", "BUY")
        is_options = bool(data.get("is_options", entry_price < 1000))

        # SL / Target defaults
        if not sl_price:
            sl_pct = 0.30 if is_options else 0.02
            sl_offset = entry_price * sl_pct
            sl_price = (entry_price - sl_offset) if is_long else (entry_price + sl_offset)

        if not target_price:
            tgt_pct = 0.50 if is_options else 0.04
            target_offset = entry_price * tgt_pct
            target_price = (entry_price + target_offset) if is_long else (entry_price - target_offset)

        if broker_manages_sl_target:
            self._broker_managed_exits.add(trade_id)

        # Store position with all metadata needed for BS pricing
        self._positions[trade_id] = {
            "trade_id": trade_id,
            "symbol": data.get("symbol", ""),
            "underlying": data.get("underlying", "NIFTY"),
            "direction": direction,
            "quantity": int(data.get("quantity", 0)),
            "entry_price": entry_price,
            "sl_price": round(float(sl_price), 2),
            "target_price": round(float(target_price), 2),
            "trade_type": data.get("trade_type", "INTRADAY"),
            "entry_time": data.get("timestamp", datetime.now(IST).isoformat()),
            "executor": executor,
            "status": "OPEN",
            "peak_pnl": 0.0,
            "trough_pnl": 0.0,
            "is_options": is_options,
            "entry_index_price": float(data.get("entry_index_price", 0) or 0),
            # CRITICAL FIX: Store full option metadata for proper BS pricing
            "strike": data.get("strike"),
            "option_type": data.get("option_type"),
            "expiry": data.get("expiry"),
            "iv": data.get("iv"),
            # Legacy delta for backward compatibility (replaced by BS Greeks)
            "delta": float(data.get("delta", 0.5) or 0.5),
        }

        logger.info(
            f"Tracking position: {trade_id} "
            f"SL={sl_price:.2f} Target={target_price:.2f} "
            f"options={is_options} broker_managed={broker_manages_sl_target}"
        )

    # ========================================================================
    # CRITICAL FIX: Proper Black-Scholes P&L Calculation
    # ========================================================================

    def _position_value(self, pos: dict) -> float | None:
        """Current position value using proper Black-Scholes pricing.

        CRITICAL FIX: Replaced naive `entry_price + index_move * delta`
        with full Black-Scholes re-pricing.

        For options: calculates current premium via BS(spot, strike, TTE, IV, r, type)
        For index/futures: uses live underlying price directly
        """
        underlying = pos["underlying"]
        underlying_price = self._latest_prices.get(underlying)

        # Non-options: direct underlying price
        if not pos.get("is_options", False):
            return underlying_price

        # Options: proper Black-Scholes pricing
        strike = pos.get("strike")
        option_type = pos.get("option_type")
        entry_index = pos.get("entry_index_price", 0)

        if underlying_price is None or not strike or not option_type:
            # Fallback to legacy delta-based estimate if metadata missing
            logger.debug(f"BS pricing unavailable for {pos['trade_id']}, using legacy fallback")
            return self._legacy_position_value(pos)

        # Calculate time to expiry
        expiry_str = pos.get("expiry")
        if expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=IST)
            except (ValueError, TypeError):
                expiry = self._estimate_expiry(expiry_str)
        else:
            expiry = self._estimate_expiry_from_entry(pos.get("entry_time", ""))

        now = datetime.now(IST)
        tte_seconds = (expiry - now).total_seconds()
        time_to_expiry = max(0.0, tte_seconds / (365.25 * 24 * 3600))

        if time_to_expiry <= 0:
            # Expired option: intrinsic value only
            is_call = option_type.upper() in ("CE", "CALL")
            if is_call:
                return max(0.0, underlying_price - strike)
            else:
                return max(0.0, strike - underlying_price)

        # Get IV: use stored IV, or latest from option chain, or default
        iv = pos.get("iv")
        if iv is None:
            iv = self._latest_iv.get(f"{underlying}_{strike}_{option_type}")
        if iv is None:
            iv = self._latest_iv.get(underlying)
        if iv is None:
            iv = DEFAULT_IV

        try:
            result = BlackScholesPricer.price(
                spot=underlying_price,
                strike=float(strike),
                time_to_expiry=time_to_expiry,
                volatility=float(iv),
                risk_free_rate=DEFAULT_RISK_FREE_RATE,
                option_type=option_type,
            )
            return result.premium
        except (ValueError, OverflowError) as e:
            logger.warning(f"BS pricing failed for {pos['trade_id']}: {e}, using legacy")
            return self._legacy_position_value(pos)

    def _calculate_greeks(self, pos: dict) -> dict:
        """Calculate Greeks for an option position using Black-Scholes.

        Returns dict with delta, gamma, theta, vega, rho.
        """
        if not pos.get("is_options", False):
            # Index/futures: delta = 1.0 (directional), other Greeks = 0
            is_long = pos["direction"].upper() in ("BULLISH", "LONG", "BUY")
            return {
                "delta": 1.0 if is_long else -1.0,
                "gamma": 0.0,
                "theta": 0.0,
                "vega": 0.0,
                "rho": 0.0,
            }

        underlying = pos["underlying"]
        underlying_price = self._latest_prices.get(underlying)
        strike = pos.get("strike")
        option_type = pos.get("option_type")

        if underlying_price is None or not strike or not option_type:
            return {"delta": pos.get("delta", 0.5), "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        # Calculate TTE
        expiry = self._get_expiry_datetime(pos)
        now = datetime.now(IST)
        tte_seconds = (expiry - now).total_seconds()
        time_to_expiry = max(0.0, tte_seconds / (365.25 * 24 * 3600))

        if time_to_expiry <= 0:
            return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

        iv = self._resolve_iv(pos, underlying, strike, option_type)

        try:
            result = BlackScholesPricer.price(
                spot=underlying_price,
                strike=float(strike),
                time_to_expiry=time_to_expiry,
                volatility=float(iv),
                risk_free_rate=DEFAULT_RISK_FREE_RATE,
                option_type=option_type,
            )
            return result.greeks.to_dict()
        except (ValueError, OverflowError):
            return {"delta": pos.get("delta", 0.5), "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    def _resolve_iv(self, pos: dict, underlying: str, strike: float, option_type: str) -> float:
        """Resolve the best available IV for a position."""
        iv = pos.get("iv")
        if iv is not None and iv > 0:
            return float(iv)
        iv = self._latest_iv.get(f"{underlying}_{strike}_{option_type}")
        if iv is not None and iv > 0:
            return float(iv)
        iv = self._latest_iv.get(underlying)
        if iv is not None and iv > 0:
            return float(iv)
        return DEFAULT_IV

    def _get_expiry_datetime(self, pos: dict) -> datetime:
        """Get expiry datetime for a position."""
        expiry_str = pos.get("expiry")
        if expiry_str:
            try:
                expiry = datetime.fromisoformat(expiry_str)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=IST)
                return expiry
            except (ValueError, TypeError):
                return self._estimate_expiry(expiry_str)
        return self._estimate_expiry_from_entry(pos.get("entry_time", ""))

    @staticmethod
    def _estimate_expiry(expiry_str: str) -> datetime:
        """Estimate expiry datetime from expiry string (YYYY-MM-DD format)."""
        try:
            # Try parsing as date
            date_part = datetime.strptime(expiry_str[:10], "%Y-%m-%d")
            # Nifty options expire at 15:30 IST on expiry day
            return date_part.replace(hour=15, minute=30, second=0, tzinfo=IST)
        except (ValueError, TypeError):
            # Default: next Thursday (weekly expiry)
            return PositionTracker._next_weekly_expiry()

    @staticmethod
    def _estimate_expiry_from_entry(entry_time_str: str) -> datetime:
        """Estimate expiry from entry time (assume weekly expiry)."""
        try:
            entry_time = datetime.fromisoformat(entry_time_str)
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=IST)
        except (ValueError, TypeError):
            entry_time = datetime.now(IST)

        # Find next Thursday (weekly expiry)
        days_until_thursday = (3 - entry_time.weekday()) % 7
        if days_until_thursday == 0:
            days_until_thursday = 7  # If today is Thursday, next Thursday
        expiry = entry_time + timedelta(days=days_until_thursday)
        return expiry.replace(hour=15, minute=30, second=0, microsecond=0)

    @staticmethod
    def _next_weekly_expiry() -> datetime:
        """Get the next weekly expiry (Thursday 15:30 IST)."""
        now = datetime.now(IST)
        days_until_thursday = (3 - now.weekday()) % 7
        if days_until_thursday == 0 and now.hour >= 15 and now.minute >= 30:
            days_until_thursday = 7
        expiry = now + timedelta(days=days_until_thursday)
        return expiry.replace(hour=15, minute=30, second=0, microsecond=0)

    # ---- Legacy fallback (for backward compatibility) --------------------

    def _legacy_position_value(self, pos: dict) -> float | None:
        """Legacy delta-based estimate (fallback only)."""
        underlying = pos["underlying"]
        underlying_price = self._latest_prices.get(underlying)
        entry_index = pos.get("entry_index_price", 0)

        if underlying_price is None or entry_index <= 0:
            return None

        index_move = underlying_price - entry_index
        if pos["direction"].upper() not in ("BULLISH", "LONG", "BUY"):
            index_move = -index_move
        delta = pos.get("delta", 0.5) or 0.5
        return max(0.05, pos["entry_price"] + index_move * delta)

    # ---- P&L calculation --------------------------------------------------

    def _unrealized(self, pos: dict, current_value: float) -> float:
        """Unrealized P&L using proper premium-based calculation.

        CRITICAL FIX: Options P&L is always (current_premium - entry_premium) * qty
        for long premium positions. Both CE and PE are long premium.
        """
        is_long = pos["direction"].upper() in ("BULLISH", "LONG", "BUY")
        if pos.get("is_options", False) or is_long:
            return (current_value - pos["entry_price"]) * pos["quantity"]
        return (pos["entry_price"] - current_value) * pos["quantity"]

    # ========================================================================
    # Monitor & Exit Logic
    # ========================================================================

    async def _monitor_loop(self, shutdown_event: asyncio.Event):
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(self._check_interval)
                await self._check_exit_conditions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor loop error: {e}", exc_info=True)

    async def _check_exit_conditions(self):
        now = datetime.now(IST)
        current_time = now.time()
        positions_to_exit = []

        for trade_id, pos in list(self._positions.items()):
            current_price = self._position_value(pos)
            direction = pos["direction"]
            entry_price = pos["entry_price"]
            sl_price = pos["sl_price"]
            target_price = pos["target_price"]
            trade_type = pos["trade_type"]
            is_broker_managed = trade_id in self._broker_managed_exits

            # EOD square-off for intraday positions
            if trade_type in ("SCALP", "INTRADAY") and current_time >= EOD_SQUARE_OFF:
                fallback_price = current_price if current_price is not None else entry_price
                unrealized = self._unrealized(pos, fallback_price)
                positions_to_exit.append((trade_id, "EOD_CLOSE", fallback_price, unrealized))
                continue

            if current_price is None:
                continue

            is_long = direction.upper() in ("BULLISH", "LONG", "BUY")
            is_options_pos = pos.get("is_options", False)

            unrealized = self._unrealized(pos, current_price)

            pos["peak_pnl"] = max(pos["peak_pnl"], unrealized)
            pos["trough_pnl"] = min(pos["trough_pnl"], unrealized)

            if is_broker_managed:
                continue

            # For options: SL/target is managed by trailing stop in paper_executor
            if is_options_pos:
                continue

            # Index/futures: check SL and target directly
            exit_reason = None
            if is_long:
                if current_price <= sl_price:
                    exit_reason = "SL_HIT"
                elif current_price >= target_price:
                    exit_reason = "TARGET_HIT"
            else:
                if current_price >= sl_price:
                    exit_reason = "SL_HIT"
                elif current_price <= target_price:
                    exit_reason = "TARGET_HIT"

            if exit_reason:
                positions_to_exit.append((trade_id, exit_reason, current_price, unrealized))

        for trade_id, exit_reason, price, pnl in positions_to_exit:
            await self._trigger_exit(trade_id, exit_reason, price, pnl)

    async def _trigger_exit(self, trade_id: str, exit_reason: str, current_price: float, pnl: float):
        pos = self._positions.get(trade_id)
        if not pos:
            return

        if pos.get("exit_pending"):
            return

        pos["exit_pending"] = True

        logger.info(
            f"Exit triggered: {trade_id} reason={exit_reason} "
            f"price=Rs.{current_price:,.2f} PnL=Rs.{pnl:,.2f}"
        )

        log_trade_event(
            trade_id=trade_id,
            event=f"EXIT_TRIGGER_{exit_reason}",
            status="EXITING",
            price=current_price,
            quantity=pos["quantity"],
            pnl=round(pnl, 2),
            details={
                "exit_reason": exit_reason,
                "entry_price": pos["entry_price"],
                "sl_price": pos["sl_price"],
                "target_price": pos["target_price"],
                "peak_pnl": pos["peak_pnl"],
                "trough_pnl": pos["trough_pnl"],
            },
        )

        await self.publisher.publish_trade_execution({
            "event": "EXIT_ORDER",
            "trade_id": trade_id,
            "exit_reason": exit_reason,
            "underlying": pos["underlying"],
            "direction": pos["direction"],
            "quantity": pos["quantity"],
            "trigger_price": current_price,
            "timestamp": datetime.now(IST).isoformat(),
        })

    # ========================================================================
    # Public API
    # ========================================================================

    def get_tracked_positions(self) -> list[dict]:
        """Get all tracked positions with current mark-to-market P&L and Greeks."""
        result = []
        for pos in self._positions.values():
            current_price = self._position_value(pos)
            if current_price is None:
                current_price = pos["entry_price"]

            unrealized = round(self._unrealized(pos, current_price), 2)

            # Calculate proper Greeks
            greeks = self._calculate_greeks(pos)

            # Build enriched position data
            enriched = {
                **pos,
                "current_price": round(current_price, 2),
                "unrealized_pnl": unrealized,
                "greeks": greeks,
                "pricing_method": "black_scholes" if pos.get("strike") and pos.get("option_type") else "legacy_fallback",
            }
            result.append(enriched)
        return result

    def get_position(self, trade_id: str) -> Optional[dict]:
        """Get a single position by trade_id with current P&L and Greeks."""
        pos = self._positions.get(trade_id)
        if not pos:
            return None

        current_price = self._position_value(pos)
        if current_price is None:
            current_price = pos["entry_price"]

        unrealized = round(self._unrealized(pos, current_price), 2)
        greeks = self._calculate_greeks(pos)

        return {
            **pos,
            "current_price": round(current_price, 2),
            "unrealized_pnl": unrealized,
            "greeks": greeks,
        }

    def get_summary(self) -> dict:
        """Get summary of all tracked positions."""
        positions = self.get_tracked_positions()
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)

        # Aggregate Greeks for options positions
        total_delta = 0.0
        total_gamma = 0.0
        total_theta = 0.0
        total_vega = 0.0
        options_count = 0

        for p in positions:
            greeks = p.get("greeks", {})
            if greeks:
                total_delta += greeks.get("delta", 0) * p.get("quantity", 0)
                total_gamma += greeks.get("gamma", 0) * p.get("quantity", 0)
                total_theta += greeks.get("theta", 0) * p.get("quantity", 0)
                total_vega += greeks.get("vega", 0) * p.get("quantity", 0)
                if p.get("is_options"):
                    options_count += 1

        return {
            "tracked_positions": len(positions),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "aggregate_greeks": {
                "delta": round(total_delta, 4),
                "gamma": round(total_gamma, 6),
                "theta": round(total_theta, 4),
                "vega": round(total_vega, 4),
            },
            "options_tracked": options_count,
            "positions": positions,
        }
