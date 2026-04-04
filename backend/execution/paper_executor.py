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

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Paper Executor starting")
        pubsub = await self.publisher.subscribe("trade_executions", "ticks")

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

    def _update_price(self, tick: dict):
        symbol = tick.get("symbol", "")
        price = tick.get("ltp") or tick.get("last_price") or tick.get("close")
        if symbol and price:
            self._latest_prices[symbol] = float(price)

        underlying = tick.get("underlying", "")
        if underlying:
            self._latest_prices[underlying] = float(price) if price else self._latest_prices.get(underlying, 0)

        # Run trailing stop updates for all open positions on every tick
        asyncio.ensure_future(self._run_trailing_stop_updates())

    async def _handle_execution_event(self, data: dict):
        event = data.get("event", "")

        if event == "RISK_APPROVED":
            await self._execute_entry(data)
        elif event == "EXIT_ORDER":
            await self._execute_exit(data)

    async def _execute_entry(self, data: dict):
        trade_id = data.get("trade_id", f"PAPER-{uuid.uuid4().hex[:8]}")
        underlying = data.get("underlying", "NIFTY")
        direction = data.get("direction", "BULLISH")
        quantity = int(data.get("quantity", 0))
        trade_type = data.get("trade_type", "INTRADAY")

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        if quantity <= 0:
            quantity = lot_size

        fill_price = self._latest_prices.get(underlying, 0)
        if fill_price <= 0:
            fill_price = 22000 if underlying == "NIFTY" else 48000

        slippage = fill_price * 0.0005
        if direction == "BULLISH":
            fill_price += slippage
        else:
            fill_price -= slippage

        fill_price = round(fill_price, 2)

        position = {
            "trade_id": trade_id,
            "underlying": underlying,
            "direction": direction,
            "quantity": quantity,
            "entry_price": fill_price,
            "trade_type": trade_type,
            "entry_time": datetime.now(IST).isoformat(),
            "status": "OPEN",
            "unrealized_pnl": 0.0,
        }
        self._positions[trade_id] = position

        # Create a TradePosition for trailing stop management
        sl_points = float(data.get("sl_points", data.get("supporting_data", {}).get("sl_points", 20)))
        atr = float(data.get("atr", data.get("supporting_data", {}).get("atr", 0)))
        if direction == "BULLISH":
            sl_price = fill_price - sl_points
        else:
            sl_price = fill_price + sl_points
        trade_pos = TradePosition(
            trade_id=trade_id,
            entry_price=fill_price,
            sl_price=round(sl_price, 2),
            direction=direction,
            quantity=quantity,
            strategy=trade_type,
            trail_atr=atr,
        )
        self._trade_positions[trade_id] = trade_pos

        symbol = data.get("symbol", f"{underlying} OPT")
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
            status="FILLED",
        )

        log_trade_event(
            trade_id=trade_id,
            event="ENTRY",
            status="FILLED",
            price=fill_price,
            quantity=quantity,
            details={
                "executor": "paper",
                "slippage_applied": round(slippage, 2),
                "trade_type": trade_type,
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
            "timestamp": datetime.now(IST).isoformat(),
        })

        logger.info(f"Paper ENTRY: {trade_id} {direction} {underlying} x{quantity} @ ₹{fill_price:,.2f}")

    async def _execute_exit(self, data: dict):
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

        exit_price = self._latest_prices.get(underlying, entry_price)

        slippage = exit_price * 0.0005
        if direction == "BULLISH":
            exit_price -= slippage
        else:
            exit_price += slippage

        exit_price = round(exit_price, 2)

        if direction == "BULLISH":
            pnl = (exit_price - entry_price) * quantity
        else:
            pnl = (entry_price - exit_price) * quantity
        pnl = round(pnl, 2)

        self._daily_pnl += pnl
        self._total_trades += 1
        if pnl > 0:
            self._winning_trades += 1

        del self._positions[trade_id]
        self._trade_positions.pop(trade_id, None)

        upsert_trade(
            trade_id=trade_id,
            symbol=f"{underlying} OPT",
            underlying=underlying,
            direction=direction,
            quantity=quantity,
            trade_type=position.get("trade_type", "INTRADAY"),
            consensus_score=0,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl=pnl,
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
                "slippage_applied": round(slippage, 2),
            },
        )

        log_audit(
            event_type="PAPER_EXIT",
            source="paper_executor",
            message=f"Paper exit: {trade_id} {exit_reason} PnL=₹{pnl:,.2f}",
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

        logger.info(f"Paper EXIT: {trade_id} {exit_reason} PnL=₹{pnl:,.2f}")

        # Notify learning system
        try:
            await self.publisher.publish("trade_closed", {
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "exit_reason": exit_reason,
                "trade_type": self._positions.get(trade_id, {}).get("trade_type", "INTRADAY"),
                "market_regime": "NORMAL",
                "timestamp": datetime.now(IST).isoformat(),
            })
        except Exception as e:
            logger.warning(f"Failed to publish trade_closed for learning: {e}")

    async def _run_trailing_stop_updates(self):
        """Run TrailingStopManager.update() for all open positions and process returned actions."""
        for trade_id in list(self._trade_positions.keys()):
            trade_pos = self._trade_positions.get(trade_id)
            if trade_pos is None or trade_pos.remaining_quantity <= 0:
                continue

            position = self._positions.get(trade_id)
            if position is None:
                continue

            underlying = position["underlying"]
            current_price = self._latest_prices.get(underlying)
            if current_price is None:
                continue

            current_atr = trade_pos.trail_atr if trade_pos.trail_atr > 0 else None
            actions = self._trailing_mgr.update(trade_pos, current_price, current_atr)

            # Also check time-based exits
            time_action = self._trailing_mgr.check_time_exit(trade_pos)
            if time_action:
                actions.append(time_action)

            for action in actions:
                await self._process_trailing_action(action, position, current_price)

    async def _process_trailing_action(self, action: dict, position: dict, current_price: float):
        """Process a trailing stop action (PARTIAL_EXIT, FULL_EXIT_SL, TIME_EXIT, etc.)."""
        action_type = action.get("action", "")
        trade_id = action.get("trade_id", "")
        exit_qty = action.get("quantity", 0)
        reason = action.get("reason", action_type)

        if exit_qty <= 0:
            return

        underlying = position["underlying"]
        direction = position["direction"]
        entry_price = position["entry_price"]

        # Simulate exit price with slippage
        exit_price = current_price
        slippage = exit_price * 0.0005
        if direction == "BULLISH":
            exit_price -= slippage
        else:
            exit_price += slippage
        exit_price = round(exit_price, 2)

        if direction == "BULLISH":
            pnl = (exit_price - entry_price) * exit_qty
        else:
            pnl = (entry_price - exit_price) * exit_qty
        pnl = round(pnl, 2)

        if action_type == "PARTIAL_EXIT":
            # Partial exit: reduce position quantity, log the partial fill
            position["quantity"] -= exit_qty
            self._daily_pnl += pnl

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
        if self._daily_pnl > 0:
            self._winning_trades += 1

        del self._positions[trade_id]
        self._trade_positions.pop(trade_id, None)

        upsert_trade(
            trade_id=trade_id,
            symbol=f"{position['underlying']} OPT",
            underlying=position["underlying"],
            direction=position["direction"],
            quantity=position.get("quantity", 0),
            trade_type=position.get("trade_type", "INTRADAY"),
            consensus_score=0,
            entry_price=position["entry_price"],
            exit_price=last_exit_price,
            pnl=0,  # PnL already accumulated via partial exits
            exit_reason=reason,
            exit_time=datetime.now(IST).isoformat(),
            status="CLOSED",
        )

        logger.info(f"Paper position fully closed via partial exits: {trade_id}")

    def get_open_positions(self) -> list[dict]:
        for pos in self._positions.values():
            underlying = pos["underlying"]
            current_price = self._latest_prices.get(underlying, pos["entry_price"])
            if pos["direction"] == "BULLISH":
                pos["unrealized_pnl"] = round((current_price - pos["entry_price"]) * pos["quantity"], 2)
            else:
                pos["unrealized_pnl"] = round((pos["entry_price"] - current_price) * pos["quantity"], 2)
            pos["current_price"] = current_price
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
