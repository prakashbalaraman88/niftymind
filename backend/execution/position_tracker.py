import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta, time

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS
from agents.db_logger import log_trade_event, log_audit

logger = logging.getLogger("niftymind.position_tracker")

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_CLOSE = time(15, 30)
EOD_SQUARE_OFF = time(15, 15)


class PositionTracker:
    def __init__(self, redis_publisher, executor):
        self.publisher = redis_publisher
        self.executor = executor
        self._positions: dict[str, dict] = {}
        self._latest_prices: dict[str, float] = {}
        self._check_interval: float = 2.0

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Position Tracker starting")
        pubsub = await self.publisher.subscribe("trade_executions", "ticks")

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
        symbol = tick.get("symbol", "")
        price = tick.get("ltp") or tick.get("last_price") or tick.get("close")
        if symbol and price:
            self._latest_prices[symbol] = float(price)

        underlying = tick.get("underlying", "")
        if underlying and price:
            self._latest_prices[underlying] = float(price)

    def _handle_trade_event(self, data: dict):
        event = data.get("event", "")
        trade_id = data.get("trade_id", "")

        if event == "ENTRY":
            sl_price = data.get("sl_price")
            target_price = data.get("target_price")
            entry_price = float(data.get("price", 0))
            direction = data.get("direction", "BULLISH")

            if not sl_price:
                sl_offset = entry_price * 0.02
                sl_price = (entry_price - sl_offset) if direction == "BULLISH" else (entry_price + sl_offset)

            if not target_price:
                target_offset = entry_price * 0.04
                target_price = (entry_price + target_offset) if direction == "BULLISH" else (entry_price - target_offset)

            self._positions[trade_id] = {
                "trade_id": trade_id,
                "underlying": data.get("underlying", "NIFTY"),
                "direction": direction,
                "quantity": int(data.get("quantity", 0)),
                "entry_price": entry_price,
                "sl_price": round(float(sl_price), 2),
                "target_price": round(float(target_price), 2),
                "trade_type": data.get("trade_type", "INTRADAY"),
                "entry_time": data.get("timestamp", datetime.now(IST).isoformat()),
                "status": "OPEN",
                "peak_pnl": 0.0,
                "trough_pnl": 0.0,
            }
            logger.info(f"Tracking position: {trade_id} SL={sl_price:.2f} Target={target_price:.2f}")

        elif event in ("EXIT", "SL_HIT", "TARGET_HIT", "EOD_CLOSE", "MANUAL"):
            if trade_id in self._positions:
                del self._positions[trade_id]

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
            underlying = pos["underlying"]
            current_price = self._latest_prices.get(underlying)
            direction = pos["direction"]
            entry_price = pos["entry_price"]
            sl_price = pos["sl_price"]
            target_price = pos["target_price"]
            trade_type = pos["trade_type"]

            if trade_type in ("SCALP", "INTRADAY") and current_time >= EOD_SQUARE_OFF:
                fallback_price = current_price if current_price is not None else entry_price
                unrealized = 0.0
                if direction == "BULLISH":
                    unrealized = (fallback_price - entry_price) * pos["quantity"]
                else:
                    unrealized = (entry_price - fallback_price) * pos["quantity"]
                positions_to_exit.append((trade_id, "EOD_CLOSE", fallback_price, unrealized))
                continue

            if current_price is None:
                continue

            if direction == "BULLISH":
                unrealized = (current_price - entry_price) * pos["quantity"]
            else:
                unrealized = (entry_price - current_price) * pos["quantity"]

            pos["peak_pnl"] = max(pos["peak_pnl"], unrealized)
            pos["trough_pnl"] = min(pos["trough_pnl"], unrealized)

            exit_reason = None

            if direction == "BULLISH":
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

        logger.info(
            f"Exit triggered: {trade_id} reason={exit_reason} "
            f"price=₹{current_price:,.2f} PnL=₹{pnl:,.2f}"
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

        del self._positions[trade_id]

    def get_tracked_positions(self) -> list[dict]:
        result = []
        for pos in self._positions.values():
            underlying = pos["underlying"]
            current_price = self._latest_prices.get(underlying, pos["entry_price"])
            if pos["direction"] == "BULLISH":
                unrealized = round((current_price - pos["entry_price"]) * pos["quantity"], 2)
            else:
                unrealized = round((pos["entry_price"] - current_price) * pos["quantity"], 2)

            result.append({
                **pos,
                "current_price": current_price,
                "unrealized_pnl": unrealized,
            })
        return result

    def get_summary(self) -> dict:
        positions = self.get_tracked_positions()
        total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
        return {
            "tracked_positions": len(positions),
            "total_unrealized_pnl": round(total_unrealized, 2),
            "positions": positions,
        }
