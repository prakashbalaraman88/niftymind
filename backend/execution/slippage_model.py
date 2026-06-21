"""
NiftyMind Slippage Model
========================
Realistic slippage simulation for paper trading.

Models:
- Market impact based on order size relative to average daily volume
- Volatility-adjusted slippage (higher vol = wider spreads)
- Time-of-day adjustments (opening/closing auctions = more slippage)
- Instrument-specific microstructure (options vs futures vs index)

Used by: paper_executor.py
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, time, timezone, timedelta
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger("niftymind.slippage")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Time-of-day multipliers (Indian market: 09:15 - 15:30 IST)
# Higher values = more slippage
TOD_MULTIPLIERS: dict[tuple[time, time], float] = {
    (time(9, 15), time(9, 30)): 2.5,   # Opening auction / high volatility
    (time(9, 30), time(10, 0)): 1.5,   # Early morning elevated vol
    (time(10, 0), time(10, 30)): 1.2,  # Settling
    (time(10, 30), time(12, 0)): 1.0,  # Normal trading (baseline)
    (time(12, 0), time(13, 0)): 0.9,   # Lunch lull
    (time(13, 0), time(14, 0)): 1.0,   # Afternoon normal
    (time(14, 0), time(14, 30)): 1.1,  # Pre-close building
    (time(14, 30), time(15, 15)): 1.4, # Close positioning
    (time(15, 15), time(15, 30)): 2.0, # Closing auction
}

# Base slippage bps (basis points) by instrument type
BASE_SLIPPAGE_BPS: dict[str, float] = {
    "index": 0.5,      # Nifty 50 spot (very liquid)
    "future": 1.0,     # Nifty/BankNifty futures
    "option_itm": 2.0, # Deep ITM options
    "option_atm": 3.0, # ATM options
    "option_otm": 5.0, # OTM options
    "option_deep_otm": 10.0, # Deep OTM (illiquid)
}

# Volatility regime multipliers (applied to base slippage)
VOL_REGIME_MULTIPLIERS: dict[str, float] = {
    "low": 0.7,      # VIX < 15
    "normal": 1.0,   # VIX 15-25
    "high": 1.6,     # VIX 25-35
    "extreme": 2.5,  # VIX > 35
}

# Minimum slippage in absolute terms (prevent zero slippage)
MIN_SLIPPAGE_ABSOLUTE: dict[str, float] = {
    "index": 0.05,
    "future": 0.10,
    "option": 0.05,
}

# Typical ADV (Average Daily Volume) for Indian markets (approximate)
TYPICAL_ADV: dict[str, int] = {
    "NIFTY": 50_000,        # Nifty futures lots per day
    "BANKNIFTY": 30_000,    # BankNifty futures lots per day
    "NIFTY_OPT": 1_000_000, # Nifty options lots per day
    "BANKNIFTY_OPT": 500_000,
}

LOT_SIZES: dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
}


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_LOSS = "STOP_LOSS"
    SL_MARKET = "SL_MARKET"


class InstrumentType(Enum):
    INDEX = "index"
    FUTURE = "future"
    OPTION_ITM = "option_itm"
    OPTION_ATM = "option_atm"
    OPTION_OTM = "option_otm"
    OPTION_DEEP_OTM = "option_deep_otm"


@dataclass(frozen=True, slots=True)
class SlippageEstimate:
    """Result of slippage calculation."""

    slippage_amount: float      # Absolute slippage in price terms
    slippage_bps: float         # Slippage in basis points
    fill_price: float           # Estimated fill price after slippage
    market_impact_bps: float    # Component from order size
    vol_impact_bps: float       # Component from volatility
    tod_impact_bps: float       # Component from time-of-day
    total_adjustment: float     # Composite multiplier applied

    def to_dict(self) -> dict:
        return {
            "slippage_amount": round(self.slippage_amount, 4),
            "slippage_bps": round(self.slippage_bps, 2),
            "fill_price": round(self.fill_price, 4),
            "market_impact_bps": round(self.market_impact_bps, 2),
            "vol_impact_bps": round(self.vol_impact_bps, 2),
            "tod_impact_bps": round(self.tod_impact_bps, 2),
            "total_adjustment": round(self.total_adjustment, 4),
        }


# ---------------------------------------------------------------------------
# Slippage Model
# ---------------------------------------------------------------------------

class SlippageModel:
    """Realistic slippage model for Nifty/BankNifty paper trading.

    Slippage is composed of:
        base_slippage * (1 + market_impact + vol_adjustment) * tod_multiplier

    For BUY orders:  fill = market_price + slippage
    For SELL orders: fill = market_price - slippage
    """

    def __init__(
        self,
        enable_stochastic: bool = True,
        random_seed: Optional[int] = None,
    ):
        self.enable_stochastic = enable_stochastic
        if random_seed is not None:
            random.seed(random_seed)
            np.random.seed(random_seed)

    # ---- Time-of-day -------------------------------------------------------

    @staticmethod
    def _get_tod_multiplier(current_time: Optional[datetime] = None) -> float:
        """Get time-of-day slippage multiplier."""
        if current_time is None:
            current_time = datetime.now(IST)

        t = current_time.time()
        for (start, end), mult in TOD_MULTIPLIERS.items():
            if start <= t < end:
                return mult

        # Default: normal trading hours fallback
        if time(9, 15) <= t <= time(15, 30):
            return 1.0

        # Pre/post market
        return 3.0

    @staticmethod
    def _get_tod_label(current_time: Optional[datetime] = None) -> str:
        """Get human-readable time-of-day label."""
        if current_time is None:
            current_time = datetime.now(IST)
        t = current_time.time()
        for (start, end), _ in TOD_MULTIPLIERS.items():
            if start <= t < end:
                return f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}"
        return "OTHER"

    # ---- Volatility regime -------------------------------------------------

    @staticmethod
    def _get_volatility_regime(current_iv: Optional[float] = None) -> str:
        """Classify volatility regime from IV or VIX proxy.

        IV ranges for Indian markets:
        - Low:    < 12% annualized
        - Normal: 12-22%
        - High:   22-35%
        - Extreme: > 35%
        """
        if current_iv is None:
            return "normal"
        if current_iv < 0.12:
            return "low"
        elif current_iv < 0.22:
            return "normal"
        elif current_iv < 0.35:
            return "high"
        else:
            return "extreme"

    # ---- Market impact -----------------------------------------------------

    @classmethod
    def _market_impact(
        cls,
        quantity: int,
        underlying: str = "NIFTY",
        instrument_type: InstrumentType = InstrumentType.OPTION_ATM,
    ) -> float:
        """Calculate market impact from order size relative to ADV.

        Uses the square-root law: impact ~ sqrt(order_size / ADV)
        """
        adv_key = underlying.upper()
        if "OPT" in instrument_type.value:
            adv_key += "_OPT"

        adv = TYPICAL_ADV.get(adv_key, 50_000)

        # Convert quantity to lots
        lot_size = LOT_SIZES.get(underlying.upper(), 25)
        lots = max(1, quantity // lot_size)

        # Square-root market impact model
        participation = lots / adv
        impact = np.sqrt(max(0.0, participation)) * 100  # in bps

        # Cap impact at reasonable levels
        return min(impact, 50.0)  # max 50 bps

    # ---- Instrument classification -----------------------------------------

    @staticmethod
    def classify_instrument(
        spot: float,
        strike: float,
        option_type: Optional[str] = None,
        is_future: bool = False,
        is_index: bool = False,
    ) -> InstrumentType:
        """Classify instrument for slippage determination."""
        if is_index:
            return InstrumentType.INDEX
        if is_future:
            return InstrumentType.FUTURE
        if option_type is None:
            return InstrumentType.OPTION_ATM

        # Classify by moneyness
        moneyness = spot / strike if strike > 0 else 1.0
        opt_type = option_type.upper()

        if opt_type in ("CE", "CALL"):
            if moneyness > 1.05:
                return InstrumentType.OPTION_ITM
            elif moneyness > 0.98:
                return InstrumentType.OPTION_ATM
            elif moneyness > 0.95:
                return InstrumentType.OPTION_OTM
            else:
                return InstrumentType.OPTION_DEEP_OTM
        else:  # PE / PUT
            if moneyness < 0.95:
                return InstrumentType.OPTION_ITM
            elif moneyness < 1.02:
                return InstrumentType.OPTION_ATM
            elif moneyness < 1.05:
                return InstrumentType.OPTION_OTM
            else:
                return InstrumentType.OPTION_DEEP_OTM

    # ---- Main estimation method -------------------------------------------

    def estimate_slippage(
        self,
        market_price: float,
        quantity: int,
        side: OrderSide,
        order_type: OrderType = OrderType.MARKET,
        underlying: str = "NIFTY",
        spot: Optional[float] = None,
        strike: Optional[float] = None,
        option_type: Optional[str] = None,
        is_future: bool = False,
        is_index: bool = False,
        current_iv: Optional[float] = None,
        current_time: Optional[datetime] = None,
    ) -> SlippageEstimate:
        """Estimate realistic slippage for a paper trade.

        Parameters
        ----------
        market_price : float
            Current market price (LTP)
        quantity : int
            Order quantity
        side : OrderSide
            BUY or SELL
        order_type : OrderType
            MARKET, LIMIT, STOP_LOSS, SL_MARKET
        underlying : str
            "NIFTY" or "BANKNIFTY"
        spot, strike, option_type : optional
            For options: to classify ITM/ATM/OTM
        is_future, is_index : bool
            Instrument flags
        current_iv : float | None
            Current implied volatility (annualized)
        current_time : datetime | None
            Order timestamp (defaults to now)

        Returns
        -------
        SlippageEstimate with all components
        """
        if market_price <= 0:
            logger.warning(f"Slippage: market_price={market_price} <= 0, returning zero slippage")
            return SlippageEstimate(
                slippage_amount=0.0,
                slippage_bps=0.0,
                fill_price=market_price,
                market_impact_bps=0.0,
                vol_impact_bps=0.0,
                tod_impact_bps=0.0,
                total_adjustment=1.0,
            )

        # Classify instrument
        instrument = self.classify_instrument(
            spot=spot or market_price,
            strike=strike or market_price,
            option_type=option_type,
            is_future=is_future,
            is_index=is_index,
        )

        # Base slippage in bps
        base_bps = BASE_SLIPPAGE_BPS.get(instrument.value, 3.0)

        # Order type adjustment
        if order_type == OrderType.LIMIT:
            base_bps *= 0.3  # Limit orders have much less slippage
        elif order_type in (OrderType.STOP_LOSS, OrderType.SL_MARKET):
            base_bps *= 1.5  # Stop orders experience more slippage

        # Market impact from order size
        impact_bps = self._market_impact(quantity, underlying, instrument)

        # Volatility regime adjustment
        vol_regime = self._get_volatility_regime(current_iv)
        vol_mult = VOL_REGIME_MULTIPLIERS.get(vol_regime, 1.0)

        # Time-of-day multiplier
        tod_mult = self._get_tod_multiplier(current_time)

        # Stochastic noise (log-normal around 1.0)
        if self.enable_stochastic:
            noise = np.exp(np.random.normal(0.0, 0.15))
            tod_mult *= noise

        # Composite slippage in bps
        total_bps = (base_bps + impact_bps) * vol_mult * tod_mult

        # Convert bps to absolute price slippage
        slippage_amount = market_price * total_bps / 10_000

        # Ensure minimum slippage
        min_slip_key = "option" if "option" in instrument.value else instrument.value
        min_slip = MIN_SLIPPAGE_ABSOLUTE.get(min_slip_key, 0.05)
        slippage_amount = max(slippage_amount, min_slip)

        # Apply direction
        is_buy = side == OrderSide.BUY
        fill_price = market_price + slippage_amount if is_buy else market_price - slippage_amount
        fill_price = max(0.05, fill_price)

        # Decomposition for analysis
        vol_component = base_bps * (vol_mult - 1.0)
        tod_component = (base_bps + impact_bps) * vol_mult * (tod_mult - 1.0) if tod_mult > 1 else 0.0

        return SlippageEstimate(
            slippage_amount=slippage_amount,
            slippage_bps=total_bps,
            fill_price=round(fill_price, 4),
            market_impact_bps=impact_bps,
            vol_impact_bps=vol_component,
            tod_impact_bps=tod_component,
            total_adjustment=vol_mult * tod_mult,
        )

    # ---- Convenience wrappers ----------------------------------------------

    def apply_slippage_to_fill(
        self,
        market_price: float,
        quantity: int,
        side: str,  # "BUY" or "SELL"
        **kwargs,
    ) -> float:
        """One-liner: get slippage-adjusted fill price."""
        estimate = self.estimate_slippage(
            market_price=market_price,
            quantity=quantity,
            side=OrderSide(side.upper()),
            **kwargs,
        )
        return estimate.fill_price

    def get_slippage_components(
        self,
        market_price: float,
        quantity: int,
        side: str,
        **kwargs,
    ) -> dict:
        """Get full slippage decomposition as a dict."""
        estimate = self.estimate_slippage(
            market_price=market_price,
            quantity=quantity,
            side=OrderSide(side.upper()),
            **kwargs,
        )
        return estimate.to_dict()


# ---------------------------------------------------------------------------
# Pre-configured model instances
# ---------------------------------------------------------------------------

def conservative_model() -> SlippageModel:
    """Conservative (higher) slippage estimates — safer for paper trading."""
    return SlippageModel(enable_stochastic=True, random_seed=None)


def aggressive_model() -> SlippageModel:
    """Aggressive (lower) slippage estimates — for optimistic scenarios."""
    # We create a modified model by subclassing approach via wrapper
    model = SlippageModel(enable_stochastic=False)
    return model


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    model = SlippageModel(enable_stochastic=False)

    # Test ATM Nifty option
    est = model.estimate_slippage(
        market_price=150.0,
        quantity=2500,  # 100 lots
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        underlying="NIFTY",
        spot=25000,
        strike=25000,
        option_type="CE",
        current_iv=0.18,
        current_time=datetime(2024, 6, 21, 11, 0, 0, tzinfo=IST),
    )
    print(f"ATM Nifty CE Buy @ 11:00 AM:")
    print(f"  Slippage: {est.slippage_amount:.2f} ({est.slippage_bps:.1f} bps)")
    print(f"  Fill price: {est.fill_price:.2f}")
    print(f"  Components: {est.to_dict()}")

    # Test opening vs closing
    est_open = model.estimate_slippage(
        market_price=150.0,
        quantity=2500,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        underlying="NIFTY",
        spot=25000,
        strike=25000,
        option_type="CE",
        current_iv=0.18,
        current_time=datetime(2024, 6, 21, 9, 20, 0, tzinfo=IST),
    )
    est_close = model.estimate_slippage(
        market_price=150.0,
        quantity=2500,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        underlying="NIFTY",
        spot=25000,
        strike=25000,
        option_type="CE",
        current_iv=0.18,
        current_time=datetime(2024, 6, 21, 15, 20, 0, tzinfo=IST),
    )
    print(f"\nOpening (09:20) slippage: {est_open.slippage_bps:.1f} bps")
    print(f"Closing (15:20) slippage: {est_close.slippage_bps:.1f} bps")
