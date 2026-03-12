import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import REDIS_CHANNELS, NIFTY_LOT_SIZE, BANKNIFTY_LOT_SIZE
from agents.db_logger import log_trade_event, log_audit, upsert_trade

logger = logging.getLogger("niftymind.kite_executor")

IST = timezone(timedelta(hours=5, minutes=30))


class KiteExecutor:
    def __init__(self, redis_publisher, zerodha_config):
        self.publisher = redis_publisher
        self._api_key = zerodha_config.api_key
        self._api_secret = zerodha_config.api_secret
        self._access_token = zerodha_config.access_token
        self._kite = None
        self._positions: dict[str, dict] = {}
        self._order_map: dict[str, str] = {}
        self._daily_pnl: float = 0.0
        self._total_trades: int = 0
        self._winning_trades: int = 0

    def _init_kite(self):
        if self._kite is not None:
            return

        try:
            from kiteconnect import KiteConnect
            self._kite = KiteConnect(api_key=self._api_key)
            self._kite.set_access_token(self._access_token)
            logger.info("Kite Connect initialized")
        except ImportError:
            logger.error("kiteconnect package not installed. Install with: pip install kiteconnect")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Kite Connect: {e}")
            raise

    async def start(self, shutdown_event: asyncio.Event):
        logger.info("Kite Executor starting (LIVE mode)")

        self._init_kite()

        pubsub = await self.publisher.subscribe("trade_executions")

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

                    if REDIS_CHANNELS["trade_executions"] in channel:
                        await self._handle_execution_event(data)

                except json.JSONDecodeError:
                    pass
                except Exception as e:
                    logger.error(f"Kite executor error: {e}", exc_info=True)

        except asyncio.CancelledError:
            logger.info("Kite Executor cancelled")
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
            logger.info("Kite Executor stopped")

    async def _handle_execution_event(self, data: dict):
        event = data.get("event", "")

        if event == "RISK_APPROVED":
            await self._place_entry_order(data)
        elif event == "EXIT_ORDER":
            await self._place_exit_order(data)

    async def _place_entry_order(self, data: dict):
        trade_id = data.get("trade_id", f"LIVE-{uuid.uuid4().hex[:8]}")
        underlying = data.get("underlying", "NIFTY")
        direction = data.get("direction", "BULLISH")
        quantity = int(data.get("quantity", 0))
        trade_type = data.get("trade_type", "INTRADAY")

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        if quantity <= 0:
            quantity = lot_size

        if quantity % lot_size != 0:
            quantity = (quantity // lot_size) * lot_size
            if quantity <= 0:
                quantity = lot_size

        transaction_type = "BUY" if direction == "BULLISH" else "SELL"
        trading_symbol = self._resolve_trading_symbol(underlying, direction)
        product = "MIS" if trade_type in ("SCALP", "INTRADAY") else "NRML"

        try:
            order_id = await asyncio.to_thread(
                self._kite.place_order,
                variety="regular",
                exchange="NFO",
                tradingsymbol=trading_symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type="MARKET",
            )

            self._order_map[trade_id] = str(order_id)

            order_details = await asyncio.to_thread(
                self._kite.order_history, order_id=order_id
            )
            fill_price = 0
            for detail in reversed(order_details):
                if detail.get("status") == "COMPLETE":
                    fill_price = float(detail.get("average_price", 0))
                    break

            position = {
                "trade_id": trade_id,
                "order_id": str(order_id),
                "underlying": underlying,
                "direction": direction,
                "quantity": quantity,
                "entry_price": fill_price,
                "trading_symbol": trading_symbol,
                "product": product,
                "trade_type": trade_type,
                "entry_time": datetime.now(IST).isoformat(),
                "status": "OPEN",
            }
            self._positions[trade_id] = position

            upsert_trade(
                trade_id=trade_id,
                symbol=trading_symbol,
                underlying=underlying,
                direction=direction,
                quantity=quantity,
                trade_type=trade_type,
                consensus_score=float(data.get("confidence", 0)),
                entry_price=fill_price,
                status="FILLED",
            )

            log_trade_event(
                trade_id=trade_id,
                event="ENTRY",
                status="FILLED",
                price=fill_price,
                quantity=quantity,
                details={
                    "executor": "kite",
                    "order_id": str(order_id),
                    "trading_symbol": trading_symbol,
                    "product": product,
                },
            )

            log_audit(
                event_type="KITE_ENTRY",
                source="kite_executor",
                message=f"Kite order placed: {transaction_type} {trading_symbol} x{quantity} order_id={order_id}",
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
                "executor": "kite",
                "order_id": str(order_id),
                "timestamp": datetime.now(IST).isoformat(),
            })

            logger.info(f"Kite ENTRY: {trade_id} {transaction_type} {trading_symbol} x{quantity} order={order_id}")

        except Exception as e:
            logger.error(f"Kite order placement failed for {trade_id}: {e}", exc_info=True)

            log_audit(
                event_type="KITE_ORDER_FAILED",
                source="kite_executor",
                message=f"Order failed: {trade_id} {str(e)[:200]}",
                trade_id=trade_id,
            )

            await self.publisher.publish_trade_execution({
                "event": "ORDER_FAILED",
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "error": str(e)[:200],
                "timestamp": datetime.now(IST).isoformat(),
            })

    async def _place_exit_order(self, data: dict):
        trade_id = data.get("trade_id", "")
        exit_reason = data.get("exit_reason", "MANUAL")

        position = self._positions.get(trade_id)
        if not position:
            logger.warning(f"Exit for unknown position: {trade_id}")
            return

        underlying = position["underlying"]
        direction = position["direction"]
        quantity = position["quantity"]
        trading_symbol = position["trading_symbol"]
        product = position["product"]
        entry_price = position["entry_price"]

        transaction_type = "SELL" if direction == "BULLISH" else "BUY"

        try:
            order_id = await asyncio.to_thread(
                self._kite.place_order,
                variety="regular",
                exchange="NFO",
                tradingsymbol=trading_symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product,
                order_type="MARKET",
            )

            order_details = await asyncio.to_thread(
                self._kite.order_history, order_id=order_id
            )
            exit_price = 0
            for detail in reversed(order_details):
                if detail.get("status") == "COMPLETE":
                    exit_price = float(detail.get("average_price", 0))
                    break

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

            upsert_trade(
                trade_id=trade_id,
                symbol=trading_symbol,
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
                    "executor": "kite",
                    "exit_order_id": str(order_id),
                    "trading_symbol": trading_symbol,
                },
            )

            log_audit(
                event_type="KITE_EXIT",
                source="kite_executor",
                message=f"Kite exit: {trade_id} {exit_reason} PnL=₹{pnl:,.2f} order={order_id}",
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
                "executor": "kite",
                "exit_order_id": str(order_id),
                "timestamp": datetime.now(IST).isoformat(),
            })

            logger.info(f"Kite EXIT: {trade_id} {exit_reason} PnL=₹{pnl:,.2f}")

        except Exception as e:
            logger.error(f"Kite exit order failed for {trade_id}: {e}", exc_info=True)
            log_audit(
                event_type="KITE_EXIT_FAILED",
                source="kite_executor",
                message=f"Exit order failed: {trade_id} {str(e)[:200]}",
                trade_id=trade_id,
            )

    def _resolve_trading_symbol(self, underlying: str, direction: str) -> str:
        now = datetime.now(IST)
        today = now.date()
        days_until_thursday = (3 - today.weekday()) % 7
        if days_until_thursday == 0 and now.time() > datetime.strptime("15:30", "%H:%M").time():
            days_until_thursday = 7
        from datetime import timedelta as td
        expiry = today + td(days=days_until_thursday)

        year_suffix = expiry.strftime("%y")
        month_names = ["", "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                       "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

        if underlying == "BANKNIFTY":
            prefix = "BANKNIFTY"
            strike_base = 48000
        else:
            prefix = "NIFTY"
            strike_base = 22000

        option_type = "CE" if direction == "BULLISH" else "PE"
        expiry_str = f"{year_suffix}{month_names[expiry.month]}{expiry.day:02d}"

        return f"{prefix}{expiry_str}{strike_base}{option_type}"

    def get_open_positions(self) -> list[dict]:
        return list(self._positions.values())

    def get_stats(self) -> dict:
        win_rate = (self._winning_trades / self._total_trades * 100) if self._total_trades > 0 else 0
        return {
            "mode": "live",
            "daily_pnl": self._daily_pnl,
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "win_rate": round(win_rate, 1),
            "open_positions": len(self._positions),
        }
