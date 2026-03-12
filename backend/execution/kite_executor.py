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

ORDER_POLL_INTERVAL = 3.0
ORDER_POLL_TIMEOUT = 60.0


class KiteExecutor:
    def __init__(self, redis_publisher, zerodha_config):
        self.publisher = redis_publisher
        self._api_key = zerodha_config.api_key
        self._api_secret = zerodha_config.api_secret
        self._access_token = zerodha_config.access_token
        self._kite = None
        self._positions: dict[str, dict] = {}
        self._order_map: dict[str, str] = {}
        self._bracket_orders: dict[str, dict] = {}
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

        order_poll_task = asyncio.create_task(self._order_state_poller(shutdown_event))

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
            order_poll_task.cancel()
            try:
                await order_poll_task
            except asyncio.CancelledError:
                pass
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
        sl_points = float(data.get("sl_points", data.get("supporting_data", {}).get("sl_points", 20)))
        target_points = float(data.get("target_points", data.get("supporting_data", {}).get("target_points", 40)))

        lot_size = BANKNIFTY_LOT_SIZE if underlying == "BANKNIFTY" else NIFTY_LOT_SIZE
        if quantity <= 0:
            quantity = lot_size

        if quantity % lot_size != 0:
            quantity = max(lot_size, (quantity // lot_size) * lot_size)

        transaction_type = "BUY" if direction == "BULLISH" else "SELL"
        trading_symbol = self._resolve_trading_symbol(underlying, direction)
        product = "MIS" if trade_type in ("SCALP", "INTRADAY") else "NRML"

        use_bracket = trade_type in ("SCALP", "INTRADAY") and sl_points > 0 and target_points > 0

        try:
            sl_order_id = None
            target_order_id = None

            if use_bracket:
                order_id = await self._place_bracket_order(
                    trading_symbol=trading_symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    sl_points=sl_points,
                    target_points=target_points,
                )
                variety = "bo"
                fill_price = await self._poll_until_filled(order_id, variety)
            else:
                order_id, sl_order_id, target_order_id = await self._place_regular_order_with_sl(
                    trading_symbol=trading_symbol,
                    transaction_type=transaction_type,
                    quantity=quantity,
                    product=product,
                    sl_points=sl_points,
                    target_points=target_points,
                    direction=direction,
                )
                variety = "regular"
                fill_price = await self._poll_until_filled(order_id, variety)

            self._order_map[trade_id] = str(order_id)

            if direction == "BULLISH":
                sl_price = round(fill_price - sl_points, 2)
                target_price = round(fill_price + target_points, 2)
            else:
                sl_price = round(fill_price + sl_points, 2)
                target_price = round(fill_price - target_points, 2)

            position = {
                "trade_id": trade_id,
                "order_id": str(order_id),
                "underlying": underlying,
                "direction": direction,
                "quantity": quantity,
                "entry_price": fill_price,
                "sl_price": sl_price,
                "target_price": target_price,
                "trading_symbol": trading_symbol,
                "product": product,
                "trade_type": trade_type,
                "variety": variety,
                "sl_order_id": sl_order_id,
                "target_order_id": target_order_id,
                "entry_time": datetime.now(IST).isoformat(),
                "status": "OPEN",
            }
            self._positions[trade_id] = position

            if use_bracket:
                self._bracket_orders[trade_id] = {
                    "parent_order_id": str(order_id),
                    "sl_child_id": None,
                    "target_child_id": None,
                    "status": "ACTIVE",
                }
            elif sl_order_id or target_order_id:
                self._bracket_orders[trade_id] = {
                    "parent_order_id": str(order_id),
                    "sl_child_id": sl_order_id,
                    "target_child_id": target_order_id,
                    "status": "ACTIVE",
                    "variety": "regular_with_exits",
                }

            upsert_trade(
                trade_id=trade_id,
                symbol=trading_symbol,
                underlying=underlying,
                direction=direction,
                quantity=quantity,
                trade_type=trade_type,
                consensus_score=float(data.get("confidence", 0)),
                entry_price=fill_price,
                sl_price=sl_price,
                target_price=target_price,
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
                    "executor": "kite",
                    "variety": variety,
                    "order_id": str(order_id),
                    "trading_symbol": trading_symbol,
                    "product": product,
                    "sl_price": sl_price,
                    "target_price": target_price,
                    "sl_points": sl_points,
                    "target_points": target_points,
                },
            )

            log_audit(
                event_type="KITE_ENTRY",
                source="kite_executor",
                message=f"Kite {variety} order: {transaction_type} {trading_symbol} x{quantity} SL={sl_price} TGT={target_price} order={order_id}",
                trade_id=trade_id,
            )

            await self.publisher.publish_trade_execution({
                "event": "ENTRY",
                "trade_id": trade_id,
                "underlying": underlying,
                "direction": direction,
                "quantity": quantity,
                "price": fill_price,
                "sl_price": sl_price,
                "target_price": target_price,
                "trade_type": trade_type,
                "executor": "kite",
                "variety": variety,
                "order_id": str(order_id),
                "timestamp": datetime.now(IST).isoformat(),
            })

            logger.info(
                f"Kite ENTRY ({variety}): {trade_id} {transaction_type} {trading_symbol} "
                f"x{quantity} @ ₹{fill_price:,.2f} SL=₹{sl_price:,.2f} TGT=₹{target_price:,.2f}"
            )

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

    async def _place_bracket_order(self, trading_symbol: str, transaction_type: str,
                                    quantity: int, sl_points: float,
                                    target_points: float) -> str:
        order_id = await asyncio.to_thread(
            self._kite.place_order,
            variety="bo",
            exchange="NFO",
            tradingsymbol=trading_symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product="MIS",
            order_type="MARKET",
            stoploss=round(sl_points, 1),
            squareoff=round(target_points, 1),
        )
        logger.info(f"Bracket order placed: {trading_symbol} SL={sl_points} TGT={target_points} order={order_id}")
        return str(order_id)

    async def _place_regular_order_with_sl(self, trading_symbol: str, transaction_type: str,
                                            quantity: int, product: str,
                                            sl_points: float, target_points: float,
                                            direction: str) -> tuple[str, str | None, str | None]:
        entry_order_id = await asyncio.to_thread(
            self._kite.place_order,
            variety="regular",
            exchange="NFO",
            tradingsymbol=trading_symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            product=product,
            order_type="MARKET",
        )

        fill_price = await self._poll_until_filled(entry_order_id, "regular")
        exit_type = "SELL" if transaction_type == "BUY" else "BUY"
        sl_order_id = None
        target_order_id = None

        if fill_price > 0 and sl_points > 0:
            if direction == "BULLISH":
                sl_trigger = round(fill_price - sl_points, 1)
                sl_limit = round(sl_trigger - 1.0, 1)
            else:
                sl_trigger = round(fill_price + sl_points, 1)
                sl_limit = round(sl_trigger + 1.0, 1)

            try:
                sl_order_id = str(await asyncio.to_thread(
                    self._kite.place_order,
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=trading_symbol,
                    transaction_type=exit_type,
                    quantity=quantity,
                    product=product,
                    order_type="SL",
                    trigger_price=sl_trigger,
                    price=sl_limit,
                ))
                logger.info(f"SL order placed: trigger={sl_trigger} limit={sl_limit} order={sl_order_id}")
            except Exception as e:
                logger.error(f"SL order placement failed: {e}")

        if fill_price > 0 and target_points > 0:
            if direction == "BULLISH":
                target_limit = round(fill_price + target_points, 1)
            else:
                target_limit = round(fill_price - target_points, 1)

            try:
                target_order_id = str(await asyncio.to_thread(
                    self._kite.place_order,
                    variety="regular",
                    exchange="NFO",
                    tradingsymbol=trading_symbol,
                    transaction_type=exit_type,
                    quantity=quantity,
                    product=product,
                    order_type="LIMIT",
                    price=target_limit,
                ))
                logger.info(f"Target order placed: limit={target_limit} order={target_order_id}")
            except Exception as e:
                logger.error(f"Target order placement failed: {e}")

        return str(entry_order_id), sl_order_id, target_order_id

    async def _poll_until_filled(self, order_id: str, variety: str) -> float:
        elapsed = 0.0
        while elapsed < ORDER_POLL_TIMEOUT:
            try:
                order_history = await asyncio.to_thread(
                    self._kite.order_history, order_id=order_id
                )
                for detail in reversed(order_history):
                    status = detail.get("status", "")
                    if status == "COMPLETE":
                        return float(detail.get("average_price", 0))
                    elif status in ("REJECTED", "CANCELLED"):
                        raise RuntimeError(f"Order {order_id} {status}: {detail.get('status_message', '')}")
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"Order poll error for {order_id}: {e}")

            await asyncio.sleep(ORDER_POLL_INTERVAL)
            elapsed += ORDER_POLL_INTERVAL

        logger.warning(f"Order {order_id} not filled within {ORDER_POLL_TIMEOUT}s timeout")
        return 0

    async def _order_state_poller(self, shutdown_event: asyncio.Event):
        while not shutdown_event.is_set():
            try:
                await asyncio.sleep(5.0)
                await self._check_bracket_exits()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Order state poller error: {e}", exc_info=True)

    async def _check_bracket_exits(self):
        if not self._bracket_orders:
            return

        try:
            orders = await asyncio.to_thread(self._kite.orders)
        except Exception as e:
            logger.error(f"Failed to fetch orders: {e}")
            return

        for trade_id, bo in list(self._bracket_orders.items()):
            if bo["status"] != "ACTIVE":
                continue

            position = self._positions.get(trade_id)
            if not position:
                continue

            is_regular_with_exits = bo.get("variety") == "regular_with_exits"

            if is_regular_with_exits:
                await self._check_regular_exit_orders(trade_id, bo, position, orders)
            else:
                await self._check_bracket_child_orders(trade_id, bo, position, orders)

    async def _check_bracket_child_orders(self, trade_id: str, bo: dict,
                                           position: dict, orders: list):
        parent_id = bo["parent_order_id"]

        for order in orders:
            if str(order.get("parent_order_id", "")) != parent_id:
                continue
            if order.get("status") != "COMPLETE":
                continue

            child_txn = order.get("transaction_type", "")
            parent_txn = "BUY" if position["direction"] == "BULLISH" else "SELL"

            if child_txn != parent_txn:
                exit_price = float(order.get("average_price", 0))
                entry_price = position["entry_price"]
                quantity = position["quantity"]

                if position["direction"] == "BULLISH":
                    pnl = (exit_price - entry_price) * quantity
                else:
                    pnl = (entry_price - exit_price) * quantity
                pnl = round(pnl, 2)

                if position["direction"] == "BULLISH":
                    if exit_price <= position.get("sl_price", 0):
                        exit_reason = "SL_HIT"
                    elif exit_price >= position.get("target_price", float("inf")):
                        exit_reason = "TARGET_HIT"
                    else:
                        exit_reason = "BRACKET_EXIT"
                else:
                    if exit_price >= position.get("sl_price", float("inf")):
                        exit_reason = "SL_HIT"
                    elif exit_price <= position.get("target_price", 0):
                        exit_reason = "TARGET_HIT"
                    else:
                        exit_reason = "BRACKET_EXIT"

                await self._finalize_exit(trade_id, exit_price, pnl, exit_reason, str(order.get("order_id", "")))
                bo["status"] = "COMPLETED"
                break

    async def _check_regular_exit_orders(self, trade_id: str, bo: dict,
                                          position: dict, orders: list):
        sl_child = bo.get("sl_child_id")
        target_child = bo.get("target_child_id")
        exit_order_ids = {sl_child, target_child} - {None}

        for order in orders:
            oid = str(order.get("order_id", ""))
            if oid not in exit_order_ids:
                continue
            if order.get("status") != "COMPLETE":
                continue

            exit_price = float(order.get("average_price", 0))
            entry_price = position["entry_price"]
            quantity = position["quantity"]

            if position["direction"] == "BULLISH":
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity
            pnl = round(pnl, 2)

            exit_reason = "SL_HIT" if oid == sl_child else "TARGET_HIT"

            other_id = target_child if oid == sl_child else sl_child
            if other_id:
                try:
                    await asyncio.to_thread(
                        self._kite.cancel_order,
                        variety="regular",
                        order_id=other_id,
                    )
                    logger.info(f"Cancelled counterpart order {other_id} after {exit_reason}")
                except Exception as e:
                    logger.warning(f"Failed to cancel counterpart order {other_id}: {e}")

            await self._finalize_exit(trade_id, exit_price, pnl, exit_reason, oid)
            bo["status"] = "COMPLETED"
            break

    async def _finalize_exit(self, trade_id: str, exit_price: float, pnl: float,
                              exit_reason: str, exit_order_id: str):
        position = self._positions.get(trade_id)
        if not position:
            return

        underlying = position["underlying"]
        direction = position["direction"]
        quantity = position["quantity"]
        trading_symbol = position["trading_symbol"]
        entry_price = position["entry_price"]

        self._daily_pnl += pnl
        self._total_trades += 1
        if pnl > 0:
            self._winning_trades += 1

        del self._positions[trade_id]
        self._bracket_orders.pop(trade_id, None)

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
                "exit_order_id": exit_order_id,
                "trading_symbol": trading_symbol,
                "entry_price": entry_price,
            },
        )

        log_audit(
            event_type=f"KITE_{exit_reason}",
            source="kite_executor",
            message=f"Kite exit: {trade_id} {exit_reason} PnL=₹{pnl:,.2f} exit_order={exit_order_id}",
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
            "exit_order_id": exit_order_id,
            "timestamp": datetime.now(IST).isoformat(),
        })

        logger.info(f"Kite EXIT ({exit_reason}): {trade_id} PnL=₹{pnl:,.2f}")

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
        variety = position.get("variety", "regular")

        if variety == "bo" and trade_id in self._bracket_orders:
            try:
                parent_id = self._bracket_orders[trade_id]["parent_order_id"]
                await asyncio.to_thread(
                    self._kite.cancel_order,
                    variety="bo",
                    order_id=parent_id,
                    parent_order_id=parent_id,
                )
                logger.info(f"Cancelled bracket order {parent_id} for exit")
            except Exception as e:
                logger.warning(f"Bracket cancel failed, placing manual exit: {e}")

        elif trade_id in self._bracket_orders:
            bo = self._bracket_orders[trade_id]
            for child_key in ("sl_child_id", "target_child_id"):
                child_id = bo.get(child_key)
                if child_id:
                    try:
                        await asyncio.to_thread(
                            self._kite.cancel_order,
                            variety="regular",
                            order_id=child_id,
                        )
                        logger.info(f"Cancelled {child_key} order {child_id} for manual exit")
                    except Exception as e:
                        logger.warning(f"Failed to cancel {child_key} {child_id}: {e}")

        transaction_type = "SELL" if direction == "BULLISH" else "BUY"

        try:
            order_id = await asyncio.to_thread(
                self._kite.place_order,
                variety="regular",
                exchange="NFO",
                tradingsymbol=trading_symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                product=product if variety != "bo" else "MIS",
                order_type="MARKET",
            )

            exit_price = await self._poll_until_filled(order_id, "regular")

            if direction == "BULLISH":
                pnl = (exit_price - entry_price) * quantity
            else:
                pnl = (entry_price - exit_price) * quantity
            pnl = round(pnl, 2)

            await self._finalize_exit(trade_id, exit_price, pnl, exit_reason, str(order_id))

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
            "active_brackets": len([b for b in self._bracket_orders.values() if b["status"] == "ACTIVE"]),
        }
