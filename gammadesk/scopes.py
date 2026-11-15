"""Which expirations each view covers.

Indexes and ETFs (daily expirations): 0DTE = the nearest expiration, 1DTE = the one after it,
5DTE = every expiration within 5 days. Stocks: nearest, within 14 days, within 45 days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

INDEX_LIKE = frozenset({"SPX", "SPY", "QQQ", "IWM", "DIA", "NDX", "XSP", "RUT"})


@dataclass(frozen=True, slots=True)
class Scope:
    id: str
    label: str
    expiries: tuple[date, ...]


def kind(symbol: str) -> str:
    return "index" if symbol.upper() in INDEX_LIKE else "stock"


def select(expiries: set[date], today: date, symbol: str) -> list[Scope]:
    exps = sorted(e for e in expiries if e >= today)
    if not exps:
        return []

    def within(days: int) -> tuple[date, ...]:
        return tuple(e for e in exps if (e - today).days <= days) or (exps[0],)

    if kind(symbol) == "index":
        out = [Scope("0DTE", "0DTE", (exps[0],))]
        if len(exps) > 1:
            out.append(Scope("1DTE", "1DTE", (exps[1],)))
        out.append(Scope("5DTE", "5DTE", within(5)))
        return out
    return [
        Scope("near", "Nearest", (exps[0],)),
        Scope("14d", "14D", within(14)),
        Scope("45d", "45D", within(45)),
    ]
