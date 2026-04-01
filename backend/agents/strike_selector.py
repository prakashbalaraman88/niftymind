"""Strike Selection Engine — selects optimal option strike based on strategy, Greeks, and liquidity."""

import logging

logger = logging.getLogger("niftymind.strike_selector")

# Strategy-specific thresholds
STRATEGY_CONFIG = {
    "SCALP": {
        "delta_range": (0.42, 0.58),  # ATM or 1 strike OTM
        "min_oi": 50_000,
        "max_spread": 3.0,
        "min_premium": 10.0,
        "prefer_expiry": "WEEKLY",  # Cheaper premium, more gamma
        "iv_max_ratio": 2.0,  # Max IV vs ATM IV
    },
    "INTRADAY": {
        "delta_range_high_conviction": (0.42, 0.58),  # confidence > 0.8
        "delta_range_moderate": (0.28, 0.48),  # confidence 0.65-0.8
        "min_oi": 100_000,
        "max_spread": 5.0,
        "min_premium": 10.0,
        "prefer_expiry": "WEEKLY",  # Unless >3 days to expiry
        "iv_max_ratio": 1.5,
    },
    "BTST": {
        "delta_range": (0.48, 0.68),  # ITM or ATM — survives overnight theta
        "min_oi": 50_000,
        "max_spread": 5.0,
        "min_premium": 15.0,  # Higher floor for overnight hold
        "prefer_expiry": "MONTHLY",  # Less theta overnight
        "iv_max_ratio": 1.5,
    },
}


class StrikeSelector:
    def __init__(self, capital: float = 100_000):
        self.capital = capital
        self.max_premium_pct = 0.05  # Max 5% of capital per lot

    def select_strike(
        self,
        strategy: str,
        direction: str,
        spot_price: float,
        options: list[dict],
        underlying: str,
        confidence: float = 0.7,
        atm_iv: float | None = None,
    ) -> dict | None:
        """Select the best strike for the given strategy and direction.

        Returns dict with selected strike details or None if no valid strike found.
        """
        config = STRATEGY_CONFIG.get(strategy)
        if not config:
            logger.warning(f"Unknown strategy: {strategy}")
            return None

        option_type = "CE" if direction == "BULLISH" else "PE"
        candidates = [o for o in options if o.get("option_type") == option_type]

        if not candidates:
            logger.info(f"No {option_type} options available")
            return None

        # Determine delta range based on strategy and confidence
        if strategy == "INTRADAY":
            if confidence > 0.8:
                delta_range = config["delta_range_high_conviction"]
            else:
                delta_range = config["delta_range_moderate"]
        else:
            delta_range = config["delta_range"]

        valid = []
        for opt in candidates:
            delta = abs(opt.get("delta", 0))
            oi = opt.get("oi", 0)
            bid = opt.get("bid", 0)
            ask = opt.get("ask", 0)
            ltp = opt.get("ltp", 0)
            iv = opt.get("iv", 0)
            spread = ask - bid if ask > 0 and bid > 0 else 999
            expiry_type = opt.get("expiry_type", "WEEKLY")

            # Filter 1: Delta range
            if not (delta_range[0] <= delta <= delta_range[1]):
                continue

            # Filter 2: Minimum OI (liquidity)
            if oi < config["min_oi"]:
                continue

            # Filter 3: Max bid-ask spread
            if spread > config["max_spread"]:
                continue

            # Filter 4: Minimum premium (no penny options)
            if ltp < config["min_premium"]:
                continue

            # Filter 5: Premium ceiling (max 5% of capital)
            lot_size = 25 if underlying == "NIFTY" else 15
            lot_cost = ltp * lot_size
            if lot_cost > self.capital * self.max_premium_pct:
                continue

            # Filter 6: IV check (avoid overpriced options)
            if atm_iv and atm_iv > 0 and iv > atm_iv * config["iv_max_ratio"]:
                continue

            # Filter 7: BTST — prefer monthly expiry
            if strategy == "BTST" and expiry_type == "WEEKLY":
                days_to_expiry = opt.get("days_to_expiry", 0)
                if days_to_expiry < 2:
                    continue  # Never BTST with <2 days on weekly

            # Score: prefer closer to ATM (higher delta), higher OI, tighter spread
            delta_score = 1.0 - abs(delta - 0.50) * 2  # Peaks at 0.50
            oi_score = min(1.0, oi / 500_000)
            spread_score = 1.0 - (spread / config["max_spread"])

            # BTST: bonus for monthly expiry
            expiry_bonus = 0.2 if strategy == "BTST" and expiry_type == "MONTHLY" else 0.0

            total_score = delta_score * 0.4 + oi_score * 0.3 + spread_score * 0.2 + expiry_bonus * 0.1

            valid.append({
                "strike": opt.get("strike"),
                "option_type": option_type,
                "delta": delta,
                "oi": oi,
                "spread": spread,
                "ltp": ltp,
                "iv": iv,
                "expiry_type": expiry_type,
                "score": total_score,
                "lot_cost": lot_cost,
            })

        if not valid:
            logger.info(f"No valid strikes for {strategy} {direction} on {underlying}")
            return None

        # Sort by score descending
        valid.sort(key=lambda x: x["score"], reverse=True)
        best = valid[0]

        logger.info(
            f"Selected {best['option_type']} {best['strike']} for {strategy} "
            f"(delta={best['delta']:.2f}, OI={best['oi']:,}, spread=₹{best['spread']:.1f}, "
            f"premium=₹{best['ltp']:.1f}, score={best['score']:.3f})"
        )

        return best
