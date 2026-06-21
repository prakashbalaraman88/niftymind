"""
NiftyMind Options Pricing Engine
================================
Black-Scholes options pricing with full Greeks calculation.
Supports both CE (Call European) and PE (Put European) options.
Includes implied volatility (IV) calculation via Newton-Raphson method.

Used by: position_tracker.py, paper_executor.py
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
from scipy import stats
from scipy.optimize import newton

logger = logging.getLogger("niftymind.options_pricer")

IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_RISK_FREE_RATE: float = 0.10  # 10% annual — India repo rate typical
MIN_IV: float = 0.01  # floor for implied vol (1%)
MAX_IV: float = 5.00  # cap for implied vol (500%)
IV_GUESS: float = 0.25  # initial IV guess (25%)
NEWTON_MAX_ITER: int = 100
NEWTON_TOL: float = 1e-7


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Greeks:
    """First- and second-order Greeks for an option position."""

    delta: float  # price sensitivity to underlying
    gamma: float  # convexity / rate of delta change
    theta: float  # daily time decay (negative for long options)
    vega: float   # sensitivity to 1% IV change
    rho: float    # sensitivity to 1% rate change

    def to_dict(self) -> dict:
        return {
            "delta": round(self.delta, 6),
            "gamma": round(self.gamma, 6),
            "theta": round(self.theta, 4),
            "vega": round(self.vega, 4),
            "rho": round(self.rho, 4),
        }


@dataclass(frozen=True, slots=True)
class PricingResult:
    """Complete pricing result for an option."""

    premium: float       # option premium (price)
    intrinsic: float     # max(0, S-K) for call, max(0, K-S) for put
    time_value: float    # premium - intrinsic
    iv: float            # implied volatility (if calculated)
    greeks: Greeks       # all Greeks
    d1: float            # intermediate BS value
    d2: float            # intermediate BS value
    nd1: float           # N(d1)
    nd2: float           # N(d2)

    def to_dict(self) -> dict:
        return {
            "premium": round(self.premium, 4),
            "intrinsic": round(self.intrinsic, 4),
            "time_value": round(self.time_value, 4),
            "iv": round(self.iv, 4) if self.iv else None,
            "greeks": self.greeks.to_dict(),
        }


# ---------------------------------------------------------------------------
# Core Black-Scholes Engine
# ---------------------------------------------------------------------------

class BlackScholesPricer:
    """Black-Scholes-Merton options pricing engine for Nifty / BankNifty.

    Call: C = S * N(d1) - K * e^(-rT) * N(d2)
    Put:  P = K * e^(-rT) * N(-d2) - S * N(-d1)

    d1 = (ln(S/K) + (r + sigma^2/2) * T) / (sigma * sqrt(T))
    d2 = d1 - sigma * sqrt(T)
    """

    @staticmethod
    def _validate_inputs(
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
    ) -> None:
        """Validate all pricing inputs; raises ValueError on bad data."""
        if spot <= 0:
            raise ValueError(f"Spot must be > 0, got {spot}")
        if strike <= 0:
            raise ValueError(f"Strike must be > 0, got {strike}")
        if time_to_expiry < 0:
            raise ValueError(f"Time to expiry must be >= 0, got {time_to_expiry}")
        if volatility <= 0:
            raise ValueError(f"Volatility must be > 0, got {volatility}")
        if risk_free_rate < 0:
            raise ValueError(f"Risk-free rate must be >= 0, got {risk_free_rate}")

    @classmethod
    def calculate_d1_d2(
        cls,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float,
    ) -> tuple[float, float]:
        """Calculate d1 and d2 intermediate values."""
        cls._validate_inputs(spot, strike, time_to_expiry, volatility, risk_free_rate)

        if time_to_expiry == 0:
            # At expiry: handle edge case
            if spot > strike:
                return float("inf"), float("inf")
            elif spot < strike:
                return float("-inf"), float("-inf")
            else:
                return 0.0, 0.0

        sigma_sqrt_t = volatility * np.sqrt(time_to_expiry)
        d1 = (
            np.log(spot / strike)
            + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry
        ) / sigma_sqrt_t
        d2 = d1 - sigma_sqrt_t
        return d1, d2

    @classmethod
    def price(
        cls,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        option_type: str = "CE",
    ) -> PricingResult:
        """Price an option and compute all Greeks.

        Parameters
        ----------
        spot : float
            Current underlying spot price (Nifty / BankNifty level)
        strike : float
            Option strike price
        time_to_expiry : float
            Time to expiry in **years** (e.g. 7/365 for 7 days)
        volatility : float
            Annualized implied volatility (e.g. 0.20 for 20%)
        risk_free_rate : float
            Annualized risk-free rate (default 10%)
        option_type : str
            "CE" for Call European, "PE" for Put European

        Returns
        -------
        PricingResult with premium, Greeks, and decomposition.
        """
        option_type = option_type.upper()
        if option_type not in ("CE", "PE", "CALL", "PUT"):
            raise ValueError(f"option_type must be CE/PE/CALL/PUT, got {option_type}")

        is_call = option_type in ("CE", "CALL")

        # Validate
        cls._validate_inputs(spot, strike, time_to_expiry, volatility, risk_free_rate)

        # Handle expired option
        if time_to_expiry <= 0:
            if is_call:
                premium = max(0.0, spot - strike)
            else:
                premium = max(0.0, strike - spot)
            intrinsic = premium
            # Delta at expiry: 1 for ITM call, -1 for ITM put, 0.5 for ATM, 0 for OTM
            if spot > strike:
                expiry_delta = 1.0 if is_call else 0.0
            elif spot < strike:
                expiry_delta = 0.0 if is_call else -1.0
            else:
                expiry_delta = 0.5
            greeks = Greeks(
                delta=expiry_delta,
                gamma=0.0,
                theta=0.0,
                vega=0.0,
                rho=0.0,
            )
            return PricingResult(
                premium=premium,
                intrinsic=intrinsic,
                time_value=0.0,
                iv=volatility,
                greeks=greeks,
                d1=0.0,
                d2=0.0,
                nd1=0.0,
                nd2=0.0,
            )

        # Core Black-Scholes
        d1, d2 = cls.calculate_d1_d2(
            spot, strike, time_to_expiry, volatility, risk_free_rate
        )

        nd1 = stats.norm.cdf(d1)
        nd2 = stats.norm.cdf(d2)
        n_neg_d1 = stats.norm.cdf(-d1)
        n_neg_d2 = stats.norm.cdf(-d2)

        discount = np.exp(-risk_free_rate * time_to_expiry)

        if is_call:
            premium = spot * nd1 - strike * discount * nd2
            intrinsic = max(0.0, spot - strike)
        else:
            premium = strike * discount * n_neg_d2 - spot * n_neg_d1
            intrinsic = max(0.0, strike - spot)

        # Ensure premium is at least intrinsic (numerical safety)
        premium = max(premium, intrinsic)
        time_value = premium - intrinsic

        # ---- Greeks ----
        sqrt_t = np.sqrt(time_to_expiry)
        sigma_sqrt_t = volatility * sqrt_t

        # Common PDF term
        pdf_d1 = stats.norm.pdf(d1)

        # Delta
        if is_call:
            delta = nd1
        else:
            delta = nd1 - 1.0  # N(d1) - 1 for puts

        # Gamma (same for calls and puts)
        gamma = pdf_d1 / (spot * sigma_sqrt_t)

        # Theta (daily, i.e. per calendar day)
        # Formula gives annual theta; divide by 365 for daily
        if is_call:
            theta_annual = (
                -spot * pdf_d1 * volatility / (2.0 * sqrt_t)
                - risk_free_rate * strike * discount * nd2
            )
        else:
            theta_annual = (
                -spot * pdf_d1 * volatility / (2.0 * sqrt_t)
                + risk_free_rate * strike * discount * n_neg_d2
            )
        theta = theta_annual / 365.0

        # Vega (per 1% IV change = multiply by 0.01)
        vega = spot * pdf_d1 * sqrt_t * 0.01

        # Rho (per 1% rate change = multiply by 0.01)
        if is_call:
            rho = strike * time_to_expiry * discount * nd2 * 0.01
        else:
            rho = -strike * time_to_expiry * discount * n_neg_d2 * 0.01

        greeks = Greeks(
            delta=float(delta),
            gamma=float(gamma),
            theta=float(theta),
            vega=float(vega),
            rho=float(rho),
        )

        return PricingResult(
            premium=float(premium),
            intrinsic=float(intrinsic),
            time_value=float(time_value),
            iv=volatility,
            greeks=greeks,
            d1=float(d1),
            d2=float(d2),
            nd1=float(nd1),
            nd2=float(nd2),
        )

    # ---- Convenience aliases ------------------------------------------------

    @classmethod
    def call_price(
        cls,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ) -> PricingResult:
        """Price a Call European option."""
        return cls.price(spot, strike, time_to_expiry, volatility, risk_free_rate, "CE")

    @classmethod
    def put_price(
        cls,
        spot: float,
        strike: float,
        time_to_expiry: float,
        volatility: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    ) -> PricingResult:
        """Price a Put European option."""
        return cls.price(spot, strike, time_to_expiry, volatility, risk_free_rate, "PE")


# ---------------------------------------------------------------------------
# Implied Volatility
# ---------------------------------------------------------------------------

class ImpliedVolatility:
    """Calculate implied volatility from observed market prices."""

    @classmethod
    def _price_error(
        cls,
        iv: float,
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        option_type: str,
    ) -> float:
        """Difference between BS price at iv and market_price."""
        try:
            result = BlackScholesPricer.price(
                spot, strike, time_to_expiry, iv, risk_free_rate, option_type
            )
            return result.premium - market_price
        except (ValueError, OverflowError):
            return float("inf")

    @classmethod
    def _vega_for_iv(
        cls,
        iv: float,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        option_type: str,
    ) -> float:
        """Vega used as derivative in Newton-Raphson (scaled per 1 unit IV change)."""
        try:
            result = BlackScholesPricer.price(
                spot, strike, time_to_expiry, iv, risk_free_rate, option_type
            )
            # result.greeks.vega is per 1% change; scale to per unit IV
            return result.greeks.vega * 100.0
        except (ValueError, OverflowError):
            return 1e-6  # small non-zero to avoid division by zero

    @classmethod
    def calculate(
        cls,
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        option_type: str = "CE",
        initial_guess: float = IV_GUESS,
    ) -> Optional[float]:
        """Calculate implied volatility via Newton-Raphson.

        Parameters
        ----------
        market_price : float
            Observed market price of the option
        spot, strike, time_to_expiry, risk_free_rate : float
            Standard BS parameters
        option_type : str
            "CE" or "PE"
        initial_guess : float
            Starting IV estimate

        Returns
        -------
        float | None
            Implied volatility (annualized) or None if calculation fails
        """
        if market_price <= 0:
            logger.warning(f"IV calc: market_price={market_price} <= 0, returning None")
            return None
        if time_to_expiry <= 0:
            logger.warning("IV calc: option expired, returning None")
            return None

        intrinsic = max(0.0, spot - strike) if option_type.upper() in ("CE", "CALL") else max(0.0, strike - spot)
        if market_price < intrinsic * 0.99:
            logger.warning(f"IV calc: market_price {market_price} < intrinsic {intrinsic}, adjusting")
            market_price = intrinsic

        # Ensure initial guess is in bounds
        guess = max(MIN_IV, min(MAX_IV, initial_guess))

        try:
            iv = newton(
                func=lambda iv: cls._price_error(
                    iv, market_price, spot, strike, time_to_expiry, risk_free_rate, option_type
                ),
                x0=guess,
                fprime=lambda iv: cls._vega_for_iv(
                    iv, spot, strike, time_to_expiry, risk_free_rate, option_type
                ),
                tol=NEWTON_TOL,
                maxiter=NEWTON_MAX_ITER,
            )
            # Clamp to reasonable bounds
            iv = max(MIN_IV, min(MAX_IV, float(iv)))
            return iv
        except (RuntimeError, OverflowError, ValueError) as e:
            logger.warning(f"Newton-Raphson IV failed: {e}, falling back to bisection")
            return cls._bisection_iv(
                market_price, spot, strike, time_to_expiry, risk_free_rate, option_type
            )

    @classmethod
    def _bisection_iv(
        cls,
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        option_type: str,
    ) -> Optional[float]:
        """Fallback bisection method for IV when Newton-Raphson fails."""
        low, high = MIN_IV, MAX_IV
        for _ in range(100):
            mid = (low + high) / 2.0
            err_mid = cls._price_error(
                mid, market_price, spot, strike, time_to_expiry, risk_free_rate, option_type
            )
            if abs(err_mid) < NEWTON_TOL:
                return mid
            err_low = cls._price_error(
                low, market_price, spot, strike, time_to_expiry, risk_free_rate, option_type
            )
            if err_low * err_mid < 0:
                high = mid
            else:
                low = mid
        return (low + high) / 2.0


# ---------------------------------------------------------------------------
# P&L Calculator
# ---------------------------------------------------------------------------

class OptionsPnLCalculator:
    """Calculate realistic options P&L using Black-Scholes pricing.

    **CRITICAL FIX**: Replaces the naive `entry_price + index_move * delta`
    approximation with full Black-Scholes re-pricing at current spot.

    Real P&L = (current_premium - entry_premium) * quantity
    where current_premium = BS(spot_now, strike, TTE_now, IV, r, type)
    """

    def __init__(self, risk_free_rate: float = DEFAULT_RISK_FREE_RATE):
        self.risk_free_rate = risk_free_rate

    def calculate_pnl(
        self,
        entry_premium: float,
        current_spot: float,
        strike: float,
        entry_time: datetime,
        current_time: datetime,
        expiry_datetime: datetime,
        iv: float,
        quantity: int,
        option_type: str,
    ) -> dict:
        """Calculate mark-to-market P&L for an option position.

        Parameters
        ----------
        entry_premium : float
            Premium paid/received at entry
        current_spot : float
            Current underlying price
        strike : float
            Option strike
        entry_time : datetime
            When the position was opened
        current_time : datetime
            Current timestamp
        expiry_datetime : datetime
            Option expiry date+time
        iv : float
            Implied volatility (can be from entry or updated)
        quantity : int
            Position size (positive = long)
        option_type : str
            "CE" or "PE"

        Returns
        -------
        dict with unrealized_pnl, current_premium, greeks, etc.
        """
        # Time to expiry in years
        tte_seconds = (expiry_datetime - current_time).total_seconds()
        time_to_expiry = max(0.0, tte_seconds / (365.25 * 24 * 3600))

        if time_to_expiry <= 0:
            # Option has expired
            is_call = option_type.upper() in ("CE", "CALL")
            if is_call:
                current_premium = max(0.0, current_spot - strike)
            else:
                current_premium = max(0.0, strike - current_spot)
            greeks = Greeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)
        else:
            result = BlackScholesPricer.price(
                spot=current_spot,
                strike=strike,
                time_to_expiry=time_to_expiry,
                volatility=iv,
                risk_free_rate=self.risk_free_rate,
                option_type=option_type,
            )
            current_premium = result.premium
            greeks = result.greeks

        # P&L = (current - entry) * qty * lot_multiplier
        # For long positions: positive when premium rises
        # For short positions: negative when premium rises
        unrealized_pnl = (current_premium - entry_premium) * quantity

        return {
            "unrealized_pnl": round(unrealized_pnl, 2),
            "current_premium": round(current_premium, 4),
            "entry_premium": round(entry_premium, 4),
            "premium_change": round(current_premium - entry_premium, 4),
            "time_to_expiry_days": round(time_to_expiry * 365.25, 2),
            "greeks": greeks.to_dict(),
            "iv": round(iv, 4),
        }

    def estimate_index_move_pnl(
        self,
        entry_spot: float,
        current_spot: float,
        strike: float,
        entry_premium: float,
        time_to_expiry: float,
        iv: float,
        quantity: int,
        option_type: str,
    ) -> dict:
        """Quick P&L estimate from index movement (used when exact entry_time unavailable).

        This is the **correct** way to estimate options P&L:
        re-price with Black-Scholes rather than linear delta approximation.
        """
        entry_result = BlackScholesPricer.price(
            spot=entry_spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            volatility=iv,
            risk_free_rate=self.risk_free_rate,
            option_type=option_type,
        )
        # Recalculate TTE for current
        current_result = BlackScholesPricer.price(
            spot=current_spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            volatility=iv,
            risk_free_rate=self.risk_free_rate,
            option_type=option_type,
        )
        pnl = (current_result.premium - entry_result.premium) * quantity
        return {
            "unrealized_pnl": round(pnl, 2),
            "entry_premium": round(entry_result.premium, 4),
            "current_premium": round(current_result.premium, 4),
            "entry_greeks": entry_result.greeks.to_dict(),
            "current_greeks": current_result.greeks.to_dict(),
            "time_decay_premium": round(current_result.premium - entry_result.premium, 4),
        }


# ---------------------------------------------------------------------------
# Convenience module-level functions
# ---------------------------------------------------------------------------

def price_option(
    spot: float,
    strike: float,
    time_to_expiry_days: float,
    iv: float,
    option_type: str = "CE",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> PricingResult:
    """Convenience: price an option from days-to-expiry."""
    tte_years = time_to_expiry_days / 365.25
    return BlackScholesPricer.price(
        spot=spot,
        strike=strike,
        time_to_expiry=tte_years,
        volatility=iv,
        risk_free_rate=risk_free_rate,
        option_type=option_type,
    )


def calculate_iv(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry_days: float,
    option_type: str = "CE",
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> Optional[float]:
    """Convenience: calculate implied volatility from days-to-expiry."""
    tte_years = time_to_expiry_days / 365.25
    return ImpliedVolatility.calculate(
        market_price=market_price,
        spot=spot,
        strike=strike,
        time_to_expiry=tte_years,
        risk_free_rate=risk_free_rate,
        option_type=option_type,
    )


def quick_pnl(
    entry_premium: float,
    current_spot: float,
    strike: float,
    days_to_expiry: float,
    iv: float,
    quantity: int,
    option_type: str,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> dict:
    """Quick P&L estimate for an option position."""
    calc = OptionsPnLCalculator(risk_free_rate)
    return calc.estimate_index_move_pnl(
        entry_spot=current_spot,  # assume entry spot = current for quick calc
        current_spot=current_spot,
        strike=strike,
        entry_premium=entry_premium,
        time_to_expiry=days_to_expiry / 365.25,
        iv=iv,
        quantity=quantity,
        option_type=option_type,
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Example: NIFTY 25000 CE, spot=25100, 7 days to expiry, IV=15%
    result = price_option(
        spot=25100,
        strike=25000,
        time_to_expiry_days=7,
        iv=0.15,
        option_type="CE",
    )
    print(f"NIFTY 25000 CE @ 25100 spot, 7d TTE, 15% IV:")
    print(f"  Premium: {result.premium:.2f}")
    print(f"  Intrinsic: {result.intrinsic:.2f}")
    print(f"  Time Value: {result.time_value:.2f}")
    print(f"  Greeks: {result.greeks.to_dict()}")

    # Example: NIFTY 25000 PE, same parameters
    result_pe = price_option(
        spot=25100,
        strike=25000,
        time_to_expiry_days=7,
        iv=0.15,
        option_type="PE",
    )
    print(f"\nNIFTY 25000 PE @ 25100 spot, 7d TTE, 15% IV:")
    print(f"  Premium: {result_pe.premium:.2f}")
    print(f"  Greeks: {result_pe.greeks.to_dict()}")

    # IV calculation test
    iv = calculate_iv(
        market_price=result.premium,
        spot=25100,
        strike=25000,
        time_to_expiry_days=7,
        option_type="CE",
    )
    print(f"\nIV back-calculation: {iv:.4f} (expected ~0.15)")
