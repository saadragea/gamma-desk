"""Dealer gamma exposure (GEX) from an option chain.

Per contract: GEX = gamma x open interest x 100 x spot^2 x 0.01, in dollars per 1% move of the
underlying, + for calls and - for puts. The sign assumes dealers are long the calls and short
the puts the public holds; that is a convention, not something the data shows. It fits index
options best; on single stocks the public often buys calls, so the sign there is weaker.

walls(): the strike with the largest positive net GEX (call wall) and the largest negative one
(put wall). The dashboard applies it to the chart's strike bins (gammadesk/build.py).
Flip = the underlying level where total GEX changes sign, found by recomputing every contract's
gamma with Black-Scholes (its own IV, rates and dividends taken as 0) on a grid of levels around
the price, and taking the crossing nearest the price.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from gammadesk.cboe import Option

ET = ZoneInfo("America/New_York")
YEAR = 365 * 24 * 3600
MIN_T = 1 / (365 * 24)  # one hour: an expiring option's gamma is not allowed to blow up
_SQRT_2PI = math.sqrt(2 * math.pi)


def years_to_expiry(expiry: date, now: datetime) -> float:
    close = datetime.combine(expiry, time(16, 0), tzinfo=ET)
    return max((close - now).total_seconds() / YEAR, MIN_T)


def bs_gamma(spot: float, strike: float, t: float, iv: float) -> float:
    if spot <= 0 or strike <= 0 or t <= 0 or iv <= 0:
        return 0.0
    v = iv * math.sqrt(t)
    d1 = (math.log(spot / strike) + 0.5 * iv * iv * t) / v
    return math.exp(-0.5 * d1 * d1) / (_SQRT_2PI * spot * v)


def dollar_gex(gamma: float, oi: int, spot: float, right: str) -> float:
    sign = 1.0 if right == "C" else -1.0
    return sign * gamma * oi * 100 * spot * spot * 0.01


def contract_gamma(o: Option, spot: float, now: datetime) -> float:
    if o.gamma and o.gamma > 0:
        return o.gamma
    if o.iv:
        return bs_gamma(spot, o.strike, years_to_expiry(o.expiry, now), o.iv)
    return 0.0


@dataclass(slots=True)
class StrikeRow:
    k: float
    net: float = 0.0  # dollars per 1% move
    oi_c: int = 0
    oi_p: int = 0
    vol_c: int = 0
    vol_p: int = 0
    iv_w: float = 0.0  # sum of iv x open interest, for an OI-weighted IV
    iv_n: int = 0

    @property
    def iv(self) -> float | None:
        return self.iv_w / self.iv_n if self.iv_n else None


def by_strike(options: Iterable[Option], spot: float, now: datetime) -> list[StrikeRow]:
    rows: dict[float, StrikeRow] = {}
    for o in options:
        r = rows.setdefault(o.strike, StrikeRow(o.strike))
        if o.oi > 0:
            r.net += dollar_gex(contract_gamma(o, spot, now), o.oi, spot, o.right)
            if o.iv:
                r.iv_w += o.iv * o.oi
                r.iv_n += o.oi
        if o.right == "C":
            r.oi_c += o.oi
            r.vol_c += o.volume
        else:
            r.oi_p += o.oi
            r.vol_p += o.volume
    return sorted(rows.values(), key=lambda r: r.k)


def walls(rows: Sequence[StrikeRow]) -> tuple[float | None, float | None]:
    pos = max(rows, key=lambda r: r.net, default=None)
    neg = min(rows, key=lambda r: r.net, default=None)
    cw = pos.k if pos is not None and pos.net > 0 else None
    pw = neg.k if neg is not None and neg.net < 0 else None
    return cw, pw


def total_at(options: Sequence[Option], level: float, now: datetime) -> float:
    total = 0.0
    for o in options:
        if o.oi <= 0 or not o.iv:
            continue
        g = bs_gamma(level, o.strike, years_to_expiry(o.expiry, now), o.iv)
        total += dollar_gex(g, o.oi, level, o.right)
    return total


def flip(
    options: Sequence[Option], spot: float, now: datetime, width: float, steps: int = 60
) -> float | None:
    """Level nearest the price where total GEX changes sign, within +-width; None if none."""
    near = [o for o in options if o.oi > 0 and o.iv and abs(o.strike / spot - 1) <= width * 2]
    if not near:
        return None
    levels = [spot * (1 - width + 2 * width * i / steps) for i in range(steps + 1)]
    values = [total_at(near, lv, now) for lv in levels]
    crossings: list[float] = []
    for i in range(steps):
        a, b, va, vb = levels[i], levels[i + 1], values[i], values[i + 1]
        if va == 0:
            crossings.append(a)
        elif va * vb < 0:
            crossings.append(a + (b - a) * (-va) / (vb - va))
    return min(crossings, key=lambda x: abs(x - spot)) if crossings else None


def expected_move(options: Sequence[Option], spot: float, expiry: date) -> float | None:
    """At-the-money straddle of `expiry`: call + put at the strike nearest the price."""
    by_k: dict[float, dict[str, float]] = {}
    for o in options:
        if o.expiry == expiry and o.price:
            by_k.setdefault(o.strike, {})[o.right] = o.price
    pairs = [(k, v) for k, v in by_k.items() if "C" in v and "P" in v]
    if not pairs:
        return None
    _, v = min(pairs, key=lambda kv: abs(kv[0] - spot))
    return v["C"] + v["P"]
