"""
Position Reconciliation Engine
==============================
Compares internal position state with broker-reported positions on startup,
detects mismatches, handles orphaned positions from crashes, and maintains
a full reconciliation audit trail.

Flow:
1. On startup: fetch positions from broker + internal state
2. Compare: symbol, quantity, direction, average price
3. Detect mismatches: orphaned broker positions, missing internal positions
4. Resolve: update internal state, notify, log
5. Store: reconciliation history for audit
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Awaitable

logger = logging.getLogger("niftymind.position_reconciler")

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class MismatchType(Enum):
    ORPHANED_BROKER_POSITION = "orphaned_broker_position"      # Broker has it, we don't
    MISSING_BROKER_POSITION = "missing_broker_position"        # We have it, broker doesn't
    QUANTITY_MISMATCH = "quantity_mismatch"                    # Different quantities
    DIRECTION_MISMATCH = "direction_mismatch"                  # Different directions
    PRICE_MISMATCH = "price_mismatch"                          # Different avg prices
    PARTIAL_FILL_RECOVERY = "partial_fill_recovery"            # Partial fill detected
    STALE_POSITION = "stale_position"                          # Position too old


@dataclass
class BrokerPosition:
    """Normalized broker position — works across all broker APIs."""
    symbol: str
    exchange: str
    quantity: int
    direction: str                  # "LONG" or "SHORT"
    avg_price: float
    product: str                    # MIS, NRML, CNC
    m2m: float = 0.0
    realised_pnl: float = 0.0
    unrealised_pnl: float = 0.0
    broker_id: str = ""            # Broker-specific position ID
    broker_raw: dict = field(default_factory=dict)

    @property
    def net_quantity(self) -> int:
        """Net quantity (positive for long, negative for short)."""
        return self.quantity if self.direction == "LONG" else -self.quantity


@dataclass
class InternalPosition:
    """Internal tracking position."""
    trade_id: str
    symbol: str
    exchange: str
    quantity: int
    direction: str                  # "BULLISH" -> LONG, "BEARISH" -> LONG (we buy options)
    entry_price: float
    product: str
    status: str                     # OPEN, CLOSING, etc.
    entry_time: str
    sl_price: float = 0.0
    target_price: float = 0.0
    order_id: str = ""
    sl_order_id: Optional[str] = None
    target_order_id: Optional[str] = None


@dataclass
class MismatchReport:
    """A single detected mismatch."""
    mismatch_type: MismatchType
    severity: str                   # CRITICAL, WARNING, INFO
    symbol: str
    description: str
    broker_position: Optional[BrokerPosition] = None
    internal_position: Optional[InternalPosition] = None
    suggested_action: str = ""


@dataclass
class ReconciliationResult:
    """Full reconciliation result."""
    timestamp: str
    broker_name: str
    total_broker_positions: int
    total_internal_positions: int
    matched_positions: int
    mismatches: List[MismatchReport] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    is_healthy: bool = True

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "broker_name": self.broker_name,
            "total_broker_positions": self.total_broker_positions,
            "total_internal_positions": self.total_internal_positions,
            "matched_positions": self.matched_positions,
            "mismatch_count": len(self.mismatches),
            "mismatches": [
                {
                    "type": m.mismatch_type.value,
                    "severity": m.severity,
                    "symbol": m.symbol,
                    "description": m.description,
                    "suggested_action": m.suggested_action,
                }
                for m in self.mismatches
            ],
            "actions_taken": self.actions_taken,
            "warnings": self.warnings,
            "errors": self.errors,
            "is_healthy": self.is_healthy and len(self.mismatches) == 0,
        }


@dataclass
class ReconciliationHistoryEntry:
    """Stored in reconciliation history."""
    timestamp: str
    result: ReconciliationResult
    resolved: bool = False


# ---------------------------------------------------------------------------
# Main reconciler
# ---------------------------------------------------------------------------

class PositionReconciler:
    """Reconcile internal positions with broker positions."""

    def __init__(
        self,
        internal_positions_store: Dict[str, dict],
        broker_positions_fetcher: Optional[Callable[[], Awaitable[List[BrokerPosition]]]] = None,
        notification_callback: Optional[Callable[[str, dict], Awaitable[None]]] = None,
        db_logger: Any = None,
        max_position_age_hours: float = 24.0,
        price_tolerance_pct: float = 2.0,  # 2% tolerance for price mismatches
    ):
        """
        Args:
            internal_positions_store: Reference to the internal positions dict (mutated in-place).
            broker_positions_fetcher: Async callable that returns list of BrokerPosition from broker.
            notification_callback: Async callable for sending notifications.
            db_logger: Database logger object for audit trail.
            max_position_age_hours: Positions older than this are flagged as stale.
            price_tolerance_pct: Allowed % difference between internal and broker avg price.
        """
        self._internal = internal_positions_store
        self._fetch_broker_positions = broker_positions_fetcher
        self._notify = notification_callback
        self._db_logger = db_logger
        self._max_position_age_hours = max_position_age_hours
        self._price_tolerance_pct = price_tolerance_pct
        self._history: List[ReconciliationHistoryEntry] = []
        self._last_reconciliation: Optional[ReconciliationResult] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reconcile(self, broker_name: str = "primary") -> ReconciliationResult:
        """Run full reconciliation: fetch broker positions, compare, resolve.

        This is the main entry point — call on startup and periodically.
        """
        timestamp = datetime.now(IST).isoformat()
        logger.info(f"Starting position reconciliation with {broker_name}")

        result = ReconciliationResult(
            timestamp=timestamp,
            broker_name=broker_name,
            total_broker_positions=0,
            total_internal_positions=len(self._internal),
            matched_positions=0,
        )

        # 1. Fetch broker positions
        broker_positions: List[BrokerPosition] = []
        try:
            if self._fetch_broker_positions:
                broker_positions = await self._fetch_broker_positions()
                result.total_broker_positions = len(broker_positions)
                logger.info(f"Fetched {len(broker_positions)} positions from {broker_name}")
            else:
                result.warnings.append("No broker position fetcher configured — skipping broker fetch")
                logger.warning("No broker position fetcher configured")
        except Exception as e:
            result.errors.append(f"Failed to fetch broker positions: {str(e)}")
            logger.error(f"Failed to fetch broker positions: {e}", exc_info=True)
            result.is_healthy = False
            self._store_history(result)
            self._last_reconciliation = result
            return result

        # 2. Build lookup maps by symbol
        broker_by_symbol: Dict[str, BrokerPosition] = {p.symbol: p for p in broker_positions}
        internal_by_symbol: Dict[str, InternalPosition] = {}
        for trade_id, pos_dict in list(self._internal.items()):
            try:
                internal_pos = self._dict_to_internal(trade_id, pos_dict)
                internal_by_symbol[internal_pos.symbol] = internal_pos
            except Exception as e:
                result.warnings.append(f"Failed to parse internal position {trade_id}: {e}")
                logger.warning(f"Failed to parse internal position {trade_id}: {e}")

        # 3. Find all unique symbols
        all_symbols = set(broker_by_symbol.keys()) | set(internal_by_symbol.keys())

        # 4. Compare each symbol
        for symbol in all_symbols:
            broker_pos = broker_by_symbol.get(symbol)
            internal_pos = internal_by_symbol.get(symbol)

            if broker_pos and internal_pos:
                # Both have it — deep compare
                await self._compare_matched(result, broker_pos, internal_pos)
            elif broker_pos and not internal_pos:
                # Orphaned broker position
                self._detect_orphaned_broker(result, broker_pos)
            elif internal_pos and not broker_pos:
                # Missing broker position
                self._detect_missing_broker(result, internal_pos)

        # 5. Check for stale internal positions
        self._check_stale_positions(result)

        # 6. Auto-resolve actionable mismatches
        await self._auto_resolve(result)

        # 7. Store and notify
        self._store_history(result)
        self._last_reconciliation = result

        if result.mismatches:
            logger.warning(
                f"Reconciliation complete: {result.matched_positions} matched, "
                f"{len(result.mismatches)} mismatches detected"
            )
            for m in result.mismatches:
                logger.warning(f"  [{m.severity}] {m.mismatch_type.value}: {m.symbol} — {m.description}")
        else:
            logger.info(f"Reconciliation complete: all {result.matched_positions} positions matched")

        if self._notify:
            try:
                await self._notify(
                    "POSITION_RECONCILIATION",
                    result.to_dict(),
                )
            except Exception as e:
                logger.error(f"Failed to send reconciliation notification: {e}")

        self._log_to_db(result)
        return result

    async def reconcile_before_new_trade(self, symbol: str,
                                          proposed_quantity: int,
                                          direction: str) -> dict:
        """Quick check before placing a new trade.

        Returns dict with:
            - can_trade: bool
            - reason: str (if cannot trade)
            - current_exposure: dict of existing positions for same underlying
        """
        underlying = self._extract_underlying(symbol)
        exposure = {"total_quantity": 0, "positions": [], "max_allowed": 4}

        for trade_id, pos in self._internal.items():
            pos_underlying = self._extract_underlying(pos.get("trading_symbol", pos.get("symbol", "")))
            if pos_underlying == underlying and pos.get("status") == "OPEN":
                exposure["total_quantity"] += pos.get("quantity", 0)
                exposure["positions"].append({
                    "trade_id": trade_id,
                    "symbol": pos.get("trading_symbol", ""),
                    "quantity": pos.get("quantity", 0),
                    "entry_price": pos.get("entry_price", 0),
                })

        # Check if we're at max exposure
        if len(exposure["positions"]) >= exposure["max_allowed"]:
            return {
                "can_trade": False,
                "reason": f"Max exposure reached for {underlying}: {len(exposure['positions'])}/{exposure['max_allowed']} positions",
                "current_exposure": exposure,
            }

        # Check for direction conflict (same underlying, opposite direction)
        for pos in exposure["positions"]:
            pos_direction = pos.get("direction", "")
            if pos_direction and pos_direction != direction:
                return {
                    "can_trade": False,
                    "reason": f"Direction conflict: existing {pos_direction} position in {underlying}",
                    "current_exposure": exposure,
                }

        return {
            "can_trade": True,
            "reason": "",
            "current_exposure": exposure,
        }

    def get_history(self) -> List[ReconciliationHistoryEntry]:
        """Get full reconciliation history."""
        return list(self._history)

    def get_last_result(self) -> Optional[ReconciliationResult]:
        """Get the most recent reconciliation result."""
        return self._last_reconciliation

    def is_healthy(self) -> bool:
        """Check if the last reconciliation was healthy."""
        if self._last_reconciliation is None:
            return True  # No reconciliation run yet = assume healthy
        return self._last_reconciliation.is_healthy and len(self._last_reconciliation.mismatches) == 0

    # ------------------------------------------------------------------
    # Comparison logic
    # ------------------------------------------------------------------

    async def _compare_matched(self, result: ReconciliationResult,
                               broker_pos: BrokerPosition,
                               internal_pos: InternalPosition):
        """Compare a position that exists on both sides."""
        matched = True

        # Check quantity
        if broker_pos.quantity != internal_pos.quantity:
            result.mismatches.append(MismatchReport(
                mismatch_type=MismatchType.QUANTITY_MISMATCH,
                severity="WARNING",
                symbol=broker_pos.symbol,
                description=f"Quantity mismatch: broker={broker_pos.quantity}, internal={internal_pos.quantity}",
                broker_position=broker_pos,
                internal_position=internal_pos,
                suggested_action="Update internal quantity to match broker",
            ))
            matched = False

        # Check direction
        broker_dir = broker_pos.direction
        internal_dir = "LONG" if internal_pos.direction in ("BULLISH", "BEARISH") else "SHORT"
        # For options, we always BUY (LONG), so direction should match
        if broker_dir != internal_dir:
            result.mismatches.append(MismatchReport(
                mismatch_type=MismatchType.DIRECTION_MISMATCH,
                severity="CRITICAL",
                symbol=broker_pos.symbol,
                description=f"Direction mismatch: broker={broker_dir}, internal={internal_dir}",
                broker_position=broker_pos,
                internal_position=internal_pos,
                suggested_action="Investigate immediately — possible manual intervention",
            ))
            matched = False

        # Check average price (with tolerance)
        if broker_pos.avg_price > 0 and internal_pos.entry_price > 0:
            price_diff_pct = abs(broker_pos.avg_price - internal_pos.entry_price) / broker_pos.avg_price * 100
            if price_diff_pct > self._price_tolerance_pct:
                result.mismatches.append(MismatchReport(
                    mismatch_type=MismatchType.PRICE_MISMATCH,
                    severity="INFO",
                    symbol=broker_pos.symbol,
                    description=f"Price mismatch: broker_avg=₹{broker_pos.avg_price:.2f}, internal=₹{internal_pos.entry_price:.2f} ({price_diff_pct:.1f}%)",
                    broker_position=broker_pos,
                    internal_position=internal_pos,
                    suggested_action=f"Update internal entry price to ₹{broker_pos.avg_price:.2f}",
                ))
                matched = False

        if matched:
            result.matched_positions += 1

    def _detect_orphaned_broker(self, result: ReconciliationResult,
                                 broker_pos: BrokerPosition):
        """Broker has a position we don't track internally."""
        result.mismatches.append(MismatchReport(
            mismatch_type=MismatchType.ORPHANED_BROKER_POSITION,
            severity="CRITICAL",
            symbol=broker_pos.symbol,
            description=f"Orphaned broker position: {broker_pos.direction} {broker_pos.quantity} @ ₹{broker_pos.avg_price:.2f} (product={broker_pos.product})",
            broker_position=broker_pos,
            suggested_action="Import into internal state or close manually",
        ))
        result.is_healthy = False

    def _detect_missing_broker(self, result: ReconciliationResult,
                                internal_pos: InternalPosition):
        """We track a position that the broker doesn't have."""
        # Could be: position already closed, order rejected, or crash during exit
        result.mismatches.append(MismatchReport(
            mismatch_type=MismatchType.MISSING_BROKER_POSITION,
            severity="WARNING",
            symbol=internal_pos.symbol,
            description=f"Internal position not found at broker: {internal_pos.direction} {internal_pos.quantity} @ ₹{internal_pos.entry_price:.2f} (status={internal_pos.status})",
            internal_position=internal_pos,
            suggested_action="Mark as closed in internal state if confirmed with broker",
        ))

    def _check_stale_positions(self, result: ReconciliationResult):
        """Flag internal positions that are too old."""
        now = datetime.now(IST)
        for trade_id, pos_dict in list(self._internal.items()):
            entry_time_str = pos_dict.get("entry_time", "")
            if not entry_time_str:
                continue
            try:
                entry_time = datetime.fromisoformat(entry_time_str)
                age_hours = (now - entry_time).total_seconds() / 3600
                if age_hours > self._max_position_age_hours:
                    result.mismatches.append(MismatchReport(
                        mismatch_type=MismatchType.STALE_POSITION,
                        severity="WARNING",
                        symbol=pos_dict.get("trading_symbol", trade_id),
                        description=f"Position age {age_hours:.1f}h exceeds max {self._max_position_age_hours}h",
                        internal_position=self._dict_to_internal(trade_id, pos_dict),
                        suggested_action="Review and manually close if needed",
                    ))
            except (ValueError, TypeError):
                pass

    # ------------------------------------------------------------------
    # Auto-resolution
    # ------------------------------------------------------------------

    async def _auto_resolve(self, result: ReconciliationResult):
        """Automatically resolve safe mismatches."""
        for mismatch in list(result.mismatches):
            if mismatch.mismatch_type == MismatchType.ORPHANED_BROKER_POSITION:
                # Import orphaned broker position into internal state
                if mismatch.broker_position:
                    await self._import_broker_position(result, mismatch.broker_position)

            elif mismatch.mismatch_type == MismatchType.MISSING_BROKER_POSITION:
                # Mark internal position as closed (broker doesn't have it)
                if mismatch.internal_position:
                    await self._mark_position_closed(result, mismatch.internal_position)

            elif mismatch.mismatch_type == MismatchType.QUANTITY_MISMATCH:
                # Update internal quantity to match broker
                if mismatch.broker_position and mismatch.internal_position:
                    await self._update_position_quantity(
                        result,
                        mismatch.internal_position.trade_id,
                        mismatch.broker_position.quantity,
                    )

            elif mismatch.mismatch_type == MismatchType.PRICE_MISMATCH:
                # Update internal entry price to match broker average
                if mismatch.broker_position and mismatch.internal_position:
                    await self._update_position_price(
                        result,
                        mismatch.internal_position.trade_id,
                        mismatch.broker_position.avg_price,
                    )

    async def _import_broker_position(self, result: ReconciliationResult,
                                      broker_pos: BrokerPosition):
        """Import an orphaned broker position into internal tracking."""
        trade_id = f"RECONCILED-{datetime.now(IST).strftime('%H%M%S')}-{broker_pos.symbol[:10]}"
        internal_dict = {
            "trade_id": trade_id,
            "order_id": broker_pos.broker_id,
            "underlying": self._extract_underlying(broker_pos.symbol),
            "direction": "BULLISH" if broker_pos.direction == "LONG" else "BEARISH",
            "quantity": broker_pos.quantity,
            "entry_price": broker_pos.avg_price,
            "sl_price": round(broker_pos.avg_price * 0.7, 2),  # Default 30% SL
            "target_price": round(broker_pos.avg_price * 1.5, 2),  # Default 50% target
            "trading_symbol": broker_pos.symbol,
            "product": broker_pos.product,
            "trade_type": "INTRADAY" if broker_pos.product == "MIS" else "NRML",
            "variety": "regular",
            "entry_time": datetime.now(IST).isoformat(),
            "status": "OPEN",
            "reconciled": True,
            "reconciliation_note": f"Imported from {result.broker_name} during reconciliation",
        }
        self._internal[trade_id] = internal_dict
        result.actions_taken.append(f"Imported orphaned position {broker_pos.symbol} as {trade_id}")
        logger.info(f"Imported orphaned broker position: {trade_id} {broker_pos.symbol}")

    async def _mark_position_closed(self, result: ReconciliationResult,
                                    internal_pos: InternalPosition):
        """Mark an internal position as closed (broker doesn't have it)."""
        if internal_pos.trade_id in self._internal:
            self._internal[internal_pos.trade_id]["status"] = "CLOSED"
            self._internal[internal_pos.trade_id]["exit_reason"] = "RECONCILIATION_CLOSE"
            self._internal[internal_pos.trade_id]["exit_time"] = datetime.now(IST).isoformat()
            self._internal[internal_pos.trade_id]["reconciled"] = True
            result.actions_taken.append(f"Marked {internal_pos.symbol} as closed (not at broker)")
            logger.info(f"Marked position {internal_pos.trade_id} as closed (not at broker)")

    async def _update_position_quantity(self, result: ReconciliationResult,
                                        trade_id: str, new_quantity: int):
        """Update internal position quantity to match broker."""
        if trade_id in self._internal:
            old_qty = self._internal[trade_id].get("quantity", 0)
            self._internal[trade_id]["quantity"] = new_quantity
            result.actions_taken.append(f"Updated {trade_id} quantity: {old_qty} -> {new_quantity}")
            logger.info(f"Updated position quantity for {trade_id}: {old_qty} -> {new_quantity}")

    async def _update_position_price(self, result: ReconciliationResult,
                                     trade_id: str, new_price: float):
        """Update internal position entry price to match broker average."""
        if trade_id in self._internal:
            old_price = self._internal[trade_id].get("entry_price", 0)
            self._internal[trade_id]["entry_price"] = new_price
            result.actions_taken.append(f"Updated {trade_id} entry_price: ₹{old_price:.2f} -> ₹{new_price:.2f}")
            logger.info(f"Updated position price for {trade_id}: ₹{old_price:.2f} -> ₹{new_price:.2f}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _dict_to_internal(trade_id: str, pos_dict: dict) -> InternalPosition:
        """Convert internal dict to InternalPosition dataclass."""
        return InternalPosition(
            trade_id=trade_id,
            symbol=pos_dict.get("trading_symbol", ""),
            exchange="NFO",
            quantity=pos_dict.get("quantity", 0),
            direction=pos_dict.get("direction", "BULLISH"),
            entry_price=pos_dict.get("entry_price", 0.0),
            product=pos_dict.get("product", "MIS"),
            status=pos_dict.get("status", "OPEN"),
            entry_time=pos_dict.get("entry_time", ""),
            sl_price=pos_dict.get("sl_price", 0.0),
            target_price=pos_dict.get("target_price", 0.0),
            order_id=pos_dict.get("order_id", ""),
            sl_order_id=pos_dict.get("sl_order_id"),
            target_order_id=pos_dict.get("target_order_id"),
        )

    @staticmethod
    def _extract_underlying(symbol: str) -> str:
        """Extract underlying index from trading symbol.

        Examples:
            NIFTY25N0724500CE -> NIFTY
            BANKNIFTY25NOV52000PE -> BANKNIFTY
        """
        symbol = symbol.upper()
        for prefix in ["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTY", "SENSEX", "BANKEX"]:
            if symbol.startswith(prefix):
                return prefix
        return "NIFTY"  # Default

    def _store_history(self, result: ReconciliationResult):
        """Store reconciliation result in history."""
        entry = ReconciliationHistoryEntry(
            timestamp=result.timestamp,
            result=result,
            resolved=result.is_healthy,
        )
        self._history.append(entry)
        # Keep last 100 entries
        if len(self._history) > 100:
            self._history = self._history[-100:]

    def _log_to_db(self, result: ReconciliationResult):
        """Log reconciliation result to database."""
        if self._db_logger is None:
            return
        try:
            if hasattr(self._db_logger, 'log_audit'):
                self._db_logger.log_audit(
                    event_type="POSITION_RECONCILIATION",
                    source="position_reconciler",
                    message=f"Reconciliation with {result.broker_name}: {result.matched_positions} matched, {len(result.mismatches)} mismatches",
                    details=result.to_dict(),
                )
        except Exception as e:
            logger.error(f"Failed to log reconciliation to DB: {e}")


# ---------------------------------------------------------------------------
# Factory / convenience
# ---------------------------------------------------------------------------

def create_reconciler(
    internal_positions_store: Dict[str, dict],
    broker_positions_fetcher: Optional[Callable[[], Awaitable[List[BrokerPosition]]]] = None,
    notification_callback: Optional[Callable[[str, dict], Awaitable[None]]] = None,
    db_logger: Any = None,
) -> PositionReconciler:
    """Factory function to create a PositionReconciler."""
    return PositionReconciler(
        internal_positions_store=internal_positions_store,
        broker_positions_fetcher=broker_positions_fetcher,
        notification_callback=notification_callback,
        db_logger=db_logger,
    )
