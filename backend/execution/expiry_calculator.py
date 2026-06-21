"""
NSE Options Expiry Calculator
=============================
Handles weekly and monthly expiry calculation for all major NSE indices.

NSE expiry schedule (effective Sep 2025):
- NIFTY:     Weekly on Tuesday, Monthly on last Tuesday
- BANKNIFTY: Weekly on Monday,  Monthly on last Monday (weeklies reintroduced)
- FINNIFTY:  Weekly on Tuesday, Monthly on last Tuesday
- MIDCPNIFTY:Weekly on Thursday, Monthly on last Thursday
- SENSEX:    Weekly on Friday,  Monthly on last Friday
- BANKEX:    Weekly on Monday,  Monthly on last Monday

Holiday handling:
- If expiry day is a trading holiday, expiry moves to the previous trading day
- Maintains a cache of NSE trading holidays (updated annually)
"""

import calendar
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Set
from functools import lru_cache

logger = logging.getLogger("niftymind.expiry_calculator")

# ---------------------------------------------------------------------------
# NSE Trading Holidays (2025) — update yearly from NSE website
# Source: https://www.nseindia.com/resources/exchange-communication-holidays
# ---------------------------------------------------------------------------
NSE_TRADING_HOLIDAYS_2025: Set[date] = {
    date(2025, 1, 1),   # New Year's Day (Wednesday)
    date(2025, 1, 26),  # Republic Day (Sunday - already non-trading)
    date(2025, 2, 26),  # Mahashivratri (Wednesday)
    date(2025, 3, 14),  # Holi (Friday)
    date(2025, 3, 31),  # Id-Ul-Fitr (Monday)
    date(2025, 4, 10),  # Mahavir Jayanti (Thursday)
    date(2025, 4, 14),  # Dr. Baba Saheb Ambedkar Jayanti (Monday)
    date(2025, 4, 18),  # Good Friday
    date(2025, 5, 1),   # Maharashtra Day (Thursday)
    date(2025, 6, 7),   # Bakri Id (Saturday - already non-trading)
    date(2025, 7, 6),   # Muharram (Sunday - already non-trading)
    date(2025, 8, 15),  # Independence Day (Friday)
    date(2025, 8, 27),  # Ganesh Chaturthi (Wednesday)
    date(2025, 9, 5),   # Krishna Janmashtami (Friday)
    date(2025, 10, 2),  # Mahatma Gandhi Jayanti (Thursday)
    date(2025, 10, 21), # Diwali Laxmi Pujan (Tuesday - special Muhurat trading)
    date(2025, 11, 5),  # Prakash Gurpurab (Wednesday)
    date(2025, 12, 25), # Christmas (Thursday)
}

# Special session days (evening/muhurat trading — NOT holidays)
SPECIAL_SESSION_DAYS_2025: Set[date] = {
    date(2025, 10, 21),  # Diwali Muhurat Trading
}

# ---------------------------------------------------------------------------
# Index expiry configuration
# ---------------------------------------------------------------------------
INDEX_EXPIRY_CONFIG: Dict[str, Dict] = {
    "NIFTY": {
        "weekly_day": calendar.TUESDAY,      # 1
        "monthly_last_weekly": True,          # Last weekly IS the monthly
        "strike_step": 50,
        "exchange_prefix": "NIFTY",
        "has_weekly": True,
    },
    "BANKNIFTY": {
        "weekly_day": calendar.MONDAY,       # 0  (weeklies reintroduced 2025)
        "monthly_last_weekly": True,
        "strike_step": 100,
        "exchange_prefix": "BANKNIFTY",
        "has_weekly": True,
    },
    "FINNIFTY": {
        "weekly_day": calendar.TUESDAY,      # 1
        "monthly_last_weekly": True,
        "strike_step": 50,
        "exchange_prefix": "FINNIFTY",
        "has_weekly": True,
    },
    "MIDCPNIFTY": {
        "weekly_day": calendar.THURSDAY,     # 3
        "monthly_last_weekly": True,
        "strike_step": 100,
        "exchange_prefix": "MIDCPNIFTY",
        "has_weekly": True,
    },
    "SENSEX": {
        "weekly_day": calendar.FRIDAY,       # 4
        "monthly_last_weekly": True,
        "strike_step": 100,
        "exchange_prefix": "SENSEX",
        "has_weekly": True,
    },
    "BANKEX": {
        "weekly_day": calendar.MONDAY,       # 0
        "monthly_last_weekly": True,
        "strike_step": 100,
        "exchange_prefix": "BANKEX",
        "has_weekly": True,
    },
}

# Month codes for weekly expiry symbols (Zerodha format)
# Jan-Sep = 1-9, Oct = O, Nov = N, Dec = D
MONTH_CODE_MAP: Dict[int, str] = {
    1: "1", 2: "2", 3: "3", 4: "4", 5: "5",
    6: "6", 7: "7", 8: "8", 9: "9",
    10: "O", 11: "N", 12: "D",
}


class ExpiryCalculator:
    """Calculate NSE options expiry dates with holiday awareness."""

    def __init__(self, holidays: Optional[Set[date]] = None):
        """
        Args:
            holidays: Override the default NSE holiday set. If None, uses built-in 2025 holidays.
        """
        self._holidays: Set[date] = set(NSE_TRADING_HOLIDAYS_2025)
        if holidays:
            self._holidays.update(holidays)
        self._special_sessions: Set[date] = set(SPECIAL_SESSION_DAYS_2025)
        self._holiday_cache: Dict[int, Set[date]] = {}  # year -> holidays

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_weekly_expiry(self, underlying: str, reference_date: Optional[date] = None) -> date:
        """Return the nearest weekly expiry date for the given underlying.

        If the calculated expiry falls on a holiday, moves to the previous trading day.
        If reference_date is on expiry day before market close, returns that same day.
        If reference_date is on expiry day after market close, returns next week's expiry.
        """
        underlying = underlying.upper().replace(" ", "")
        config = self._get_config(underlying)
        ref = reference_date or date.today()
        now = datetime.now()

        if not config["has_weekly"]:
            return self.get_monthly_expiry(underlying, ref)

        expiry_weekday = config["weekly_day"]
        days_ahead = (expiry_weekday - ref.weekday()) % 7

        # If today IS expiry day
        if days_ahead == 0:
            market_closed = now.time() >= datetime.strptime("15:30", "%H:%M").time()
            if market_closed:
                days_ahead = 7  # Move to next week

        expiry = ref + timedelta(days=days_ahead)

        # Adjust for holidays: move to previous trading day
        expiry = self._adjust_for_holiday(expiry)

        return expiry

    def get_monthly_expiry(self, underlying: str, reference_date: Optional[date] = None) -> date:
        """Return the nearest monthly expiry date for the given underlying.

        Monthly expiry is the last occurrence of the weekly expiry weekday in the month.
        If that day is a holiday, moves to the previous trading day.
        """
        underlying = underlying.upper().replace(" ", "")
        config = self._get_config(underlying)
        ref = reference_date or date.today()

        expiry_weekday = config["weekly_day"]
        year, month = ref.year, ref.month

        # Find the last occurrence of the weekday in the month
        expiry = self._last_weekday_of_month(year, month, expiry_weekday)

        # If expiry has passed (or today is expiry day after market close), move to next month
        now = datetime.now()
        market_closed = now.time() >= datetime.strptime("15:30", "%H:%M").time()
        if expiry < ref or (expiry == ref and market_closed):
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1
            expiry = self._last_weekday_of_month(year, month, expiry_weekday)

        # Adjust for holidays
        expiry = self._adjust_for_holiday(expiry)

        return expiry

    def get_expiry_symbol_suffix(self, underlying: str, reference_date: Optional[date] = None,
                                  use_monthly: bool = False) -> str:
        """Generate the expiry portion of a Zerodha trading symbol.

        Weekly format:  {YY}{M}{DD}  e.g. "25N07" for 7 Nov 2025
        Monthly format: {YY}{MMM}   e.g. "25NOV" for Nov 2025

        Args:
            underlying: Index name (NIFTY, BANKNIFTY, etc.)
            reference_date: Date to calculate expiry from (defaults to today)
            use_monthly: Force monthly expiry symbol
        """
        underlying = underlying.upper().replace(" ", "")
        config = self._get_config(underlying)

        if use_monthly or not config["has_weekly"]:
            expiry = self.get_monthly_expiry(underlying, reference_date)
            return f"{expiry.strftime('%y')}{expiry.strftime('%b').upper()}"

        expiry = self.get_weekly_expiry(underlying, reference_date)

        # Check if this weekly IS the monthly expiry
        monthly = self.get_monthly_expiry(underlying, reference_date)
        if expiry == monthly:
            # Use monthly format
            return f"{expiry.strftime('%y')}{expiry.strftime('%b').upper()}"

        # Weekly format: YY + month_code + DD
        month_code = MONTH_CODE_MAP.get(expiry.month, str(expiry.month))
        return f"{expiry.strftime('%y')}{month_code}{expiry.day:02d}"

    def build_trading_symbol(self, underlying: str, strike: int, option_type: str,
                             reference_date: Optional[date] = None,
                             use_monthly: bool = False) -> str:
        """Build a complete Zerodha-format trading symbol.

        Example: NIFTY25N0724500CE
        """
        underlying = underlying.upper().replace(" ", "")
        config = self._get_config(underlying)
        prefix = config["exchange_prefix"]
        expiry_suffix = self.get_expiry_symbol_suffix(underlying, reference_date, use_monthly)
        option_type = option_type.upper()

        return f"{prefix}{expiry_suffix}{int(strike)}{option_type}"

    def is_expiry_day(self, underlying: str, check_date: Optional[date] = None) -> bool:
        """Check if the given date (or today) is expiry day for the underlying."""
        check_date = check_date or date.today()
        weekly = self.get_weekly_expiry(underlying, check_date)
        return check_date == weekly

    def is_monthly_expiry_day(self, underlying: str, check_date: Optional[date] = None) -> bool:
        """Check if the given date (or today) is the monthly expiry day."""
        check_date = check_date or date.today()
        weekly = self.get_weekly_expiry(underlying, check_date)
        monthly = self.get_monthly_expiry(underlying, check_date)
        return check_date == weekly == monthly

    def get_expiry_for_option_symbol(self, symbol: str) -> Optional[date]:
        """Extract and return the expiry date from a trading symbol.

        Supports both weekly and monthly formats.
        """
        # Try to identify the underlying prefix
        for idx_name, config in INDEX_EXPIRY_CONFIG.items():
            prefix = config["exchange_prefix"]
            if symbol.startswith(prefix):
                remainder = symbol[len(prefix):]
                # Try monthly format first: YYMMM (e.g., 25NOV)
                if len(remainder) >= 5:
                    year_str = remainder[:2]
                    month_str = remainder[2:5].upper()
                    try:
                        year = 2000 + int(year_str)
                        month = list(calendar.month_abbr).index(month_str)
                        if 1 <= month <= 12:
                            # This is a monthly expiry
                            return self._last_weekday_of_month(year, month, config["weekly_day"])
                    except (ValueError, IndexError):
                        pass

                    # Try weekly format: YYMDD or YYMMDD (e.g., 25N07)
                    if len(remainder) >= 5:
                        year_str = remainder[:2]
                        month_code = remainder[2]
                        day_str = remainder[3:5]
                        try:
                            year = 2000 + int(year_str)
                            day = int(day_str)
                            # Reverse map month code
                            month = None
                            for m, code in MONTH_CODE_MAP.items():
                                if code == month_code.upper():
                                    month = m
                                    break
                            if month and 1 <= day <= 31:
                                return date(year, month, day)
                        except (ValueError, IndexError):
                            pass
                break
        return None

    def get_all_upcoming_expiries(self, underlying: str, weeks: int = 4,
                                   reference_date: Optional[date] = None) -> List[date]:
        """Get a list of upcoming weekly expiry dates."""
        underlying = underlying.upper().replace(" ", "")
        ref = reference_date or date.today()
        config = self._get_config(underlying)
        if not config["has_weekly"]:
            return [self.get_monthly_expiry(underlying, ref)]

        expiries = []
        seen = set()
        current = ref
        expiry_weekday = config["weekly_day"]

        while len(expiries) < weeks:
            days_ahead = (expiry_weekday - current.weekday()) % 7
            if days_ahead == 0:
                # Check if market is still open
                now = datetime.now()
                market_closed = now.time() >= datetime.strptime("15:30", "%H:%M").time()
                if market_closed:
                    days_ahead = 7

            expiry = current + timedelta(days=days_ahead)
            expiry = self._adjust_for_holiday(expiry)

            if expiry not in seen:
                seen.add(expiry)
                expiries.append(expiry)

            current = expiry + timedelta(days=1)

        return expiries

    def days_to_expiry(self, underlying: str, check_date: Optional[date] = None) -> int:
        """Return the number of calendar days until the next expiry."""
        check_date = check_date or date.today()
        expiry = self.get_weekly_expiry(underlying, check_date)
        return (expiry - check_date).days

    def add_holidays(self, holidays: List[date]) -> None:
        """Add additional holidays (e.g., from external API)."""
        self._holidays.update(holidays)
        self._holiday_cache.clear()

    def is_trading_holiday(self, check_date: date) -> bool:
        """Check if a date is an NSE trading holiday."""
        return check_date in self._holidays

    def is_trading_day(self, check_date: date) -> bool:
        """Check if markets are open on the given date."""
        if check_date.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        return not self.is_trading_holiday(check_date)

    def next_trading_day(self, check_date: date) -> date:
        """Return the next trading day from the given date."""
        next_day = check_date + timedelta(days=1)
        while not self.is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

    def previous_trading_day(self, check_date: date) -> date:
        """Return the previous trading day from the given date."""
        prev_day = check_date - timedelta(days=1)
        while not self.is_trading_day(prev_day):
            prev_day -= timedelta(days=1)
        return prev_day

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_config(self, underlying: str) -> dict:
        """Get expiry configuration for an underlying."""
        underlying = underlying.upper().replace(" ", "")
        if underlying not in INDEX_EXPIRY_CONFIG:
            logger.warning(f"Unknown underlying '{underlying}', defaulting to NIFTY config")
            return INDEX_EXPIRY_CONFIG["NIFTY"]
        return INDEX_EXPIRY_CONFIG[underlying]

    @staticmethod
    def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
        """Return the last occurrence of a weekday in a given month."""
        last_day = calendar.monthrange(year, month)[1]
        d = date(year, month, last_day)
        offset = (d.weekday() - weekday) % 7
        return d - timedelta(days=offset)

    def _adjust_for_holiday(self, expiry: date) -> date:
        """If expiry falls on a holiday, move to the previous trading day."""
        original = expiry
        max_shifts = 5  # Safety limit
        shifts = 0

        while (expiry.weekday() >= 5 or expiry in self._holidays) and shifts < max_shifts:
            expiry -= timedelta(days=1)
            shifts += 1

        if original != expiry:
            logger.info(f"Expiry shifted from {original} to {expiry} (holiday/weekend)")

        return expiry


# ---------------------------------------------------------------------------
# Singleton instance for application-wide use
# ---------------------------------------------------------------------------
_default_calculator: Optional[ExpiryCalculator] = None


def get_default_calculator() -> ExpiryCalculator:
    """Get the default singleton ExpiryCalculator instance."""
    global _default_calculator
    if _default_calculator is None:
        _default_calculator = ExpiryCalculator()
    return _default_calculator


def set_default_calculator(calculator: ExpiryCalculator) -> None:
    """Set the default singleton ExpiryCalculator instance."""
    global _default_calculator
    _default_calculator = calculator


# ---------------------------------------------------------------------------
# Convenience functions (module-level API)
# ---------------------------------------------------------------------------

def get_weekly_expiry(underlying: str, reference_date: Optional[date] = None) -> date:
    """Convenience: get weekly expiry using default calculator."""
    return get_default_calculator().get_weekly_expiry(underlying, reference_date)


def get_monthly_expiry(underlying: str, reference_date: Optional[date] = None) -> date:
    """Convenience: get monthly expiry using default calculator."""
    return get_default_calculator().get_monthly_expiry(underlying, reference_date)


def get_expiry_symbol_suffix(underlying: str, reference_date: Optional[date] = None,
                              use_monthly: bool = False) -> str:
    """Convenience: get expiry symbol suffix using default calculator."""
    return get_default_calculator().get_expiry_symbol_suffix(underlying, reference_date, use_monthly)


def build_trading_symbol(underlying: str, strike: int, option_type: str,
                         reference_date: Optional[date] = None,
                         use_monthly: bool = False) -> str:
    """Convenience: build trading symbol using default calculator."""
    return get_default_calculator().build_trading_symbol(underlying, strike, option_type,
                                                          reference_date, use_monthly)


def is_expiry_day(underlying: str, check_date: Optional[date] = None) -> bool:
    """Convenience: check expiry day using default calculator."""
    return get_default_calculator().is_expiry_day(underlying, check_date)
