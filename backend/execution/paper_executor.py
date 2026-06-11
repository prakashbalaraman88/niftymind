import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS, NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE
from agents.db_logger import log_trade_event, log_audit, upsert_trade
from execution.trailing_stop import TrailingStopManager, TradePosition
from performance.charges import net_pnl as compute_net_pnl

logger = logging.getLogger("niftymind.paper_executor")

IST = timezone(timedelta(hours=5, minutes=30))


class PaperExecutor:
    def __init__(self, redis_publisher):
        self.publisher = redis_publisher
        self._positions: dict[str, dict] = {}
        self._latest_prices: dict[str, float] = {}
        self._fills: list[dict] = []
        self._daily_pnl: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0
        self._trailing_mgr = TrailingStopManager(capital=100000)
        self._trade_positions: dict[str, TradePosition] = {}  # trade_id -> TradePosition
        self._last_reset_date: str | None = None
        self._partial_pnl: dict[str, float] = {}
        # Live option premiums from the options chain feed: (underlying, strike, type) -> ltp
        self._option_premiums: dict[tuple, float] = {}
        self._trailing_update_running: bool = False

    def _reset_daily_if_needed(self):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if self._last_reset_date != today:
            self._daily_pnl = 0.0
            self._last_reset_date = today
            logger.info(f"Paper executor daily reset: PnL zeroed for {today}")

    def _recover_open_positions(self):
        """Recover OPEN positions from DB on startup so trades survive restarts."""
        try:
            from agents.db_logger import _get_conn, replay_wal
            # First replay any WAL entries from previous crash
            replay_wal()
            conn = _get_conn()
            if not conn:
                logger.warning("Cannot recover positions — DB unavailable")
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
                self._positions[trade_id] = {
                    "trade_id": trade_id,
                    "symbol": symbol,
                    "underlying": underlying,
                    "direction": direction,
                    "quantity": qty,
                    "original_quantity": qty,
                    "entry_price": entry_px,
                    "trade_type": trade_type or "INTRADAY",
                    "entry_time": str(entry_time) if entry_time else datetime.now(IST).isoformat(),
                    "status": "OPEN",
                    # Premiums are well under index levels; recovered rows lack strike metadata
                    "is_options": entry_px > 0 and entry_px < 2000,
                    "delta": 0.5,
                }
                logger.info(f"Recovered position: {trade_id} {direction} {underlying} x{qty} @ {entry_price}")
            if rows:
                logger.info(f"Recovered {len(rows)} open positions from DB")
        except Exception as e:
            logger.error(f"Position recovery failed: {e}")

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Paper Executor starting")
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
        "NIFTY 50": "NIFTY", "NIFTY": "NIFTY", "NIFTY-FUT": "NIFTY",
        "BANKNIFTY": "BANKNIFTY", "BANKNIFTY-FUT": "BANKNIFTY",
    }

    @staticmethod
    def _is_long(direction: str) -> bool:
        return direction.upper() in ("BULLISH", "LONG", "BUY")

    def _update_option_premiums(self, data: dict):
        """Track live option premiums from the options chain feed for realistic fills."""
        underlying = data.get("underlying", "")
        for opt in data.get("options", []):
            strike = opt.get("strike")
            option_type = opt.get("option_type")
            ltp = opt.get("ltp", 0)
            if underlying and strike and option_type and ltp and ltp > 0:
                self._option_premiums[(underlying, float(strike), option_type)] = float(ltp)

    def _estimate_option_premium(self, position: dict) -> float:
        """Current premium for an options position.

        Prefers the live options chain LTP for the traded strike; falls back to a
        delta-based estimate from the index move since entry. All long-premium:
        a BEARISH trade holds a PE whose premium rises as the index falls.
        """
        underlying = position["underlying"]
        entry_premium = position["entry_price"]

        strike = position.get("strike")
        option_type = position.get("option_type")
        if strike and option_type:
            live = self._option_premiums.get((underlying, float(strike), option_type))
            if live and live > 0:
                return live

        index_price = self._latest_prices.get(underlying, 0)
        entry_index = position.get("entry_index_price", 0)
        if index_price <= 0 or entry_index <= 0:
            return entry_premium

        index_move = index_price - entry_index
        if not self._is_long(position["direction"]):
            index_move = -index_move  # PE gains when index falls
        delta = float(position.get("delta", 0.5)) or 0.5
        return max(0.05, entry_premium + index_move * delta)

    def _current_value(self, position: dict) -> float | None:
        """Price in the position's own scale: premium for options, index otherwise."""
        if position.get("is_options"):
            return self._estimate_option_premium(position)
        return self._latest_prices.get(position["underlying"])

    async def _update_price(self, tick: dict):
        symbol = tick.get("symbol", "")
        price = tick.get("ltp") or tick.get("last_price") or tick.get("close")
        if symbol and price:
            p = float(price)
            self._latest_prices[symbol] = p
            # Map symbol to underlying so open position P&L works
            underlying = tick.get("underlying") or self._SYMBOL_TO_UNDERLYING.get(symbol, "")
            if underlying:
                self._latest_prices[underlying] = p

        # Single-flight: skip if an update pass is already in progress (ticks
        # arrive far faster than the trailing logic needs to run).
        if self._trade_positions and not self._trailing_update_running:
            self._trailing_update_running = True
            try:
                await self._run_trailing_stop_updates()
            finally:
                self._trailing_update_running = False

    async def _handle_execution_event(self, data: dict):
        event = data.get("event", "")

        if event == "RISK_APPROVED":
            await self._execute_entry(data)
        elif event == "EXIT_ORDER":
            await self._execute_exit(data)

    async def _execute_entry(self, data: dict):
        self._reset_daily_if_needed()
        trade_id = data.get("trade_id", f"PAPER-{uuid.uuid4().hex[:8]}")
        underlying = data.get("underlying", "NIFTY")
        direction = data.get("direction", "BULLISH")
        quantity = int(data.get("quantity", 0))
        trade_type = data.get("trade_type", "INTRADAY")

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        if quantity <= 0:
            quantity = int(data.get("supporting_data", {}).get("quantity", 0)) or lot_size

        # Resolve symbol FIRST (before using it in position dict)
        supporting = data.get("supporting_data", {})
        selected_strike = supporting.get("selected_strike")
        symbol = data.get("symbol") or supporting.get("symbol") or f"{underlying} OPT"

        # Use options premium if strike was selected, otherwise use index price
        if selected_strike and selected_strike.get("ltp", 0) > 0:
            fill_price = float(selected_strike["ltp"])
            logger.info(f"Using options premium ₹{fill_price} for {trade_id} ({symbol})")
        elif supporting.get("entry_premium", 0) > 0:
            fill_price = float(supporting["entry_premium"])
            logger.info(f"Using entry_premium ₹{fill_price} for {trade_id} ({symbol})")
        else:
            fill_price = self._latest_prices.get(underlying, 0)
            if fill_price <= 0:
                logger.error(f"No price available for {underlying} — cannot execute {trade_id}")
                return

        is_options = selected_strike is not None or supporting.get("entry_premium", 0) > 0

        # Entry slippage: options entries are always premium BUYS (CE for bullish,
        # PE for bearish), so slippage always raises the fill. Index/futures
        # positions pay slippage in the trade direction.
        slippage = fill_price * 0.0005
        if is_options or self._is_long(direction):
            fill_price += slippage
        else:
            fill_price -= slippage

        fill_price = round(fill_price, 2)

        position = {
            "trade_id": trade_id,
            "symbol": symbol,
            "underlying": underlying,
            "direction": direction,
            "quantity": quantity,
            "original_quantity": quantity,
            "entry_price": fill_price,
            "entry_index_price": self._latest_prices.get(underlying, 0),
            "trade_type": trade_type,
            "entry_time": datetime.now(IST).isoformat(),
            "status": "OPEN",
            "unrealized_pnl": 0.0,
            "is_options": is_options,
            "strike": (selected_strike or {}).get("strike"),
            "option_type": (selected_strike or {}).get("option_type"),
            "delta": float((selected_strike or {}).get("delta", 0.5) or 0.5),
        }
        self._positions[trade_id] = position

        # Create a TradePosition for trailing stop management.
        # Options positions are managed in PREMIUM space, where every position is
        # long (we buy CE or PE) — premium rising is always in our favour. So the
        # TradePosition direction is BULLISH for options regardless of trade
        # direction; index-scale positions keep their real direction.
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
                "slippage_applied": round(slippage, 2),
                "trade_type": trade_type,
                "is_options": is_options,
            },
        )

        log_audit(
            event_type="PAPER_ENTRY",
            source="paper_executor",
            message=f"Paper fill: {direction} {underlying} x{quantity} @ ₹{fill_price:,.2f}",
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
            "delta": position["delta"],
            "entry_index_price": position["entry_index_price"],
            "timestamp": datetime.now(IST).isoformat(),
        })

        logger.info(f"Paper ENTRY: {trade_id} {direction} {underlying} x{quantity} @ ₹{fill_price:,.2f}")

    def _exit_price_and_gross(self, position: dict, exit_qty: int,
                              raw_exit_price: float | None = None) -> tuple[float, float]:
        """Exit price (with slippage) and gross P&L in the position's own scale.

        Options: we SELL premium on exit (slippage reduces proceeds) and P&L is
        always (exit - entry) since both CE and PE positions are long premium.
        Index/futures: direction-based.
        """
        entry_price = position["entry_price"]
        is_options = position.get("is_options", False)
        direction = position["direction"]

        if raw_exit_price is None:
            if is_options:
                raw_exit_price = self._estimate_option_premium(position)
            else:
                raw_exit_price = self._latest_prices.get(position["underlying"], entry_price)

        slippage = raw_exit_price * 0.0005
        if is_options or self._is_long(direction):
            exit_price = raw_exit_price - slippage  # selling: receive a touch less
        else:
            exit_price = raw_exit_price + slippage  # covering a short: pay a touch more
        exit_price = round(max(0.05, exit_price), 2)

        if is_options or self._is_long(direction):
            gross_pnl = (exit_price - entry_price) * exit_qty
        else:
            gross_pnl = (entry_price - exit_price) * exit_qty
        return exit_price, round(gross_pnl, 2)

    async def _execute_exit(self, data: dict):
        self._reset_daily_if_needed()
        trade_id = data.get("trade_id", "")
        exit_reason = data.get("exit_reason", "MANUAL")

        position = self._positions.get(trade_id)
        if not position:
            logger.warning(f"Exit requested for unknown position: {trade_id}")
            return

        underlying = position["underlying"]
        direction = position["direction"]
        quantity = position["quantity"]
        entry_price = position["entry_price"]
        is_options = position.get("is_options", False)

        exit_price, gross_pnl = self._exit_price_and_gross(position, quantity)

        pnl, charges = compute_net_pnl(gross_pnl, entry_price, exit_price, quantity, is_options)

        # Fold in any P&L already realized through partial exits
        prior_partial = self._partial_pnl.pop(trade_id, 0.0)
        total_trade_pnl = round(pnl + prior_partial, 2)

        trade_type = position.get("trade_type", "INTRADAY")
        symbol = position.get("symbol", f"{underlying} OPT")

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
            quantity=position.get("original_quantity", quantity),
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
            message=f"Paper exit: {trade_id} {exit_reason} PnL=₹{total_trade_pnl:,.2f}",
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

        logger.info(f"Paper EXIT: {trade_id} {exit_reason} PnL=₹{total_trade_pnl:,.2f}")

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
            logger.warning(f"Failed to publish trade_closed for learning: {e}")

    async def _run_trailing_stop_updates(self):
        """Run TrailingStopManager.update() for all open positions and process returned actions.

        For options positions the comparison price is the (live or estimated)
        PREMIUM, matching the premium-scale entry/SL/targets in TradePosition.
        """
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

            # Also check time-based exits
            time_action = self._trailing_mgr.check_time_exit(trade_pos)
            if time_action:
                actions.append(time_action)

            for action in actions:
                await self._process_trailing_action(action, position, current_value)

    async def _process_trailing_action(self, action: dict, position: dict, current_value: float):
        """Process a trailing stop action (PARTIAL_EXIT, FULL_EXIT_SL, TIME_EXIT, etc.).

        current_value is in the position's own scale (premium for options).
        """
        action_type = action.get("action", "")
        trade_id = action.get("trade_id", "")
        exit_qty = action.get("quantity", 0)
        reason = action.get("reason", action_type)

        if exit_qty <= 0:
            return

        if action_type == "PARTIAL_EXIT":
            underlying = position["underlying"]
            direction = position["direction"]
            entry_price = position["entry_price"]
            is_options = position.get("is_options", False)

            exit_price, gross_pnl = self._exit_price_and_gross(
                position, exit_qty, raw_exit_price=current_value
            )
            pnl, charges = compute_net_pnl(gross_pnl, entry_price, exit_price, exit_qty, is_options)

            # Partial exit: reduce position quantity, log the partial fill
            position["quantity"] -= exit_qty
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
                    "remaining_qty": position["quantity"],
                    "gross_pnl": gross_pnl,
                    "charges": charges["total"],
                    "charges_breakdown": charges["breakdown"],
                },
            )
            log_audit(
                event_type="PAPER_PARTIAL_EXIT",
                source="paper_executor",
                message=f"Paper partial exit: {trade_id} T{target_idx} qty={exit_qty} PnL=₹{pnl:,.2f}",
                trade_id=trade_id,
            )
            await self.publisher.publish_trade_execution({
                "event": f"PARTIAL_EXIT_T{target_idx}",
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "quantity": exit_qty,
                "price": exit_price,
                "pnl": pnl,
                "executor": "paper",
                "reason": reason,
                "timestamp": datetime.now(IST).isoformat(),
            })
            logger.info(f"Paper PARTIAL EXIT: {trade_id} T{target_idx} qty={exit_qty} @ ₹{exit_price:,.2f} PnL=₹{pnl:,.2f}")

            # If no quantity remaining, fully close the position
            if position["quantity"] <= 0:
                await self._close_position_fully(trade_id, exit_price, reason)

        elif action_type in ("FULL_EXIT_SL", "FULL_EXIT_ILLIQUID", "TIME_EXIT", "EOD_EXIT"):
            # Full exit: close the entire remaining position
            await self._execute_exit({
                "trade_id": trade_id,
                "exit_reason": action_type,
            })

    async def _close_position_fully(self, trade_id: str, last_exit_price: float, reason: str):
        """Remove a position that has been fully exited via partial exits."""
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
            symbol=position.get("symbol", f"{position['underlying']} OPT"),
            underlying=position["underlying"],
            direction=position["direction"],
            quantity=position.get("original_quantity", position.get("quantity", 0)),
            trade_type=position.get("trade_type", "INTRADAY"),
            consensus_score=0,
            entry_price=position["entry_price"],
            exit_price=last_exit_price,
            pnl=round(trade_pnl, 2),
            exit_reason=reason,
            exit_time=datetime.now(IST).isoformat(),
            status="CLOSED",
        )

        await self.publisher.publish_trade_execution({
            "event": "EXIT",
            "trade_id": trade_id,
            "underlying": position["underlying"],
            "direction": position["direction"],
            "quantity": position.get("original_quantity", 0),
            "price": last_exit_price,
            "pnl": round(trade_pnl, 2),
            "executor": "paper",
            "timestamp": datetime.now(IST).isoformat(),
        })

        # Notify learning system for fully-scaled-out trades too
        try:
            await self.publisher.publish("trade_closed", {
                "trade_id": trade_id,
                "underlying": position["underlying"],
                "direction": position["direction"],
                "entry_price": position["entry_price"],
                "exit_price": last_exit_price,
                "pnl": round(trade_pnl, 2),
                "exit_reason": reason,
                "trade_type": position.get("trade_type", "INTRADAY"),
                "market_regime": "NORMAL",
                "timestamp": datetime.now(IST).isoformat(),
            })
        except Exception as e:
            logger.warning(f"Failed to publish trade_closed for learning: {e}")

        logger.info(f"Paper position fully closed via partial exits: {trade_id} PnL=₹{trade_pnl:,.2f}")

    def get_open_positions(self) -> list[dict]:
        for pos in self._positions.values():
            entry_price = pos["entry_price"]
            current_value = self._current_value(pos)
            if current_value is None:
                current_value = entry_price

            pos["current_price"] = round(current_value, 2)
            if pos.get("is_options", False) or self._is_long(pos["direction"]):
                pos["unrealized_pnl"] = round((current_value - entry_price) * pos["quantity"], 2)
            else:
                pos["unrealized_pnl"] = round((entry_price - current_value) * pos["quantity"], 2)
        return list(self._positions.values())

    def get_stats(self) -> dict:
        win_rate = (self._winning_trades / self._total_trades * 100) if self._total_trades > 0 else 0
        return {
            "mode": "paper",
            "daily_pnl": self._daily_pnl,
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(win_rate, 1),
            "open_positions": len(self._positions),
        }
