"""Synthetic Cboe-shaped chains for tests (values made up; shapes follow the parser's source)."""

from __future__ import annotations

import math
from datetime import date

from gammadesk.gex import bs_gamma


def osi(root: str, exp: date, right: str, strike: float) -> str:
    return f"{root}{exp:%y%m%d}{right}{round(strike * 1000):08d}"


def body(
    spot: float,
    expiries: list[date],
    strikes: list[float],
    call_oi: dict[float, int],
    put_oi: dict[float, int],
    root: str = "SPXW",
    t_years: float = 2 / 365,
    iv: float = 0.15,
    volume: int = 500,
) -> dict:
    options = []
    for exp in expiries:
        for k in strikes:
            g = bs_gamma(spot, k, t_years, iv)
            for right, oi in (("C", call_oi.get(k, 100)), ("P", put_oi.get(k, 100))):
                intrinsic = max(0.0, spot - k) if right == "C" else max(0.0, k - spot)
                price = intrinsic + spot * iv * math.sqrt(t_years) * 0.4 * math.exp(
                    -abs(k - spot) / (spot * 0.01)
                )
                options.append(
                    {
                        "option": osi(root, exp, right, k),
                        "bid": round(max(0.05, price - 0.05), 2),
                        "ask": round(price + 0.05, 2),
                        "iv": iv,
                        "open_interest": oi,
                        "volume": volume,
                        "delta": 0.5,
                        "gamma": g,
                        "last_trade_price": round(price, 2),
                    }
                )
    return {
        "timestamp": "2026-11-13 16:15:00",
        "data": {"symbol": "_SPX", "current_price": spot, "close": spot,
                 "prev_day_close": spot - 10, "options": options},
    }
