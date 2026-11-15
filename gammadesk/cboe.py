"""Cboe delayed option quotes: free, about 15 minutes delayed, the JSON behind cboe.com pages.

Unofficial and undocumented. URL and fields follow the open-source OpenBB Cboe provider
(openbb_cboe/models/options_chains.py): indexes take a leading underscore (_SPX holds SPX and
SPXW); each option has "option" (OSI-style symbol), bid, ask, iv (decimal), open_interest,
volume, delta, gamma and last_trade_price; the underlying has current_price, close and
prev_day_close. A response in another shape is a FetchError, never silent zeros.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass
from datetime import date

from gammadesk.net import BROWSER_UA, FetchError, Opener, get_json, num

URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
INDEXES = frozenset({"SPX", "NDX", "RUT", "XSP", "VIX", "DJX", "OEX", "XEO", "MRUT"})
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
}
_OPTION = re.compile(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$")


@dataclass(frozen=True, slots=True)
class Option:
    root: str  # SPX or SPXW for the index; the ticker for stocks and ETFs
    expiry: date
    right: str  # "C" or "P"
    strike: float
    bid: float | None
    ask: float | None
    last: float | None
    volume: int  # contracts traded in the session so far
    oi: int  # open interest at the previous close
    iv: float | None  # decimal, 0.18 = 18%
    gamma: float | None  # per share, per 1 point of the underlying
    delta: float | None

    @property
    def price(self) -> float | None:
        """Mid when the quote is sane, else the last trade; None when neither exists."""
        if self.bid and self.ask and 0 < self.bid <= self.ask:
            return (self.bid + self.ask) / 2
        return self.last if self.last and self.last > 0 else None


@dataclass(frozen=True, slots=True)
class Chain:
    symbol: str
    spot: float
    prev_close: float | None
    asof: str | None  # Cboe's own timestamp for the snapshot, as given
    options: tuple[Option, ...]
    change: float | None = None  # Cboe's price_change / price_change_percent when given
    change_pct: float | None = None


def quote_url(symbol: str) -> str:
    s = symbol.upper()
    return URL.format(symbol=f"_{s}" if s in INDEXES else s)


def parse(body: object, symbol: str) -> Chain:
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        keys = sorted(body)[:8] if isinstance(body, dict) else type(body).__name__
        raise FetchError(f"unexpected response: {keys}")
    raw = data.get("options")
    if not isinstance(raw, list):
        raise FetchError(f"no options list: data keys {sorted(data)[:8]}")
    spot = num(data.get("current_price")) or num(data.get("close"))
    if not spot or spot <= 0:
        raise FetchError("no underlying price")
    options: list[Option] = []
    seen: set[str] = set()
    for o in raw:
        if not isinstance(o, dict):
            continue
        text = str(o.get("option") or "").strip()
        m = _OPTION.match(text)
        if not m or text in seen:  # adjusted or non-standard contract, or a repeat
            continue
        seen.add(text)
        root, yy, mm, dd, cp, strike8 = m.groups()
        try:
            expiry = date(2000 + int(yy), int(mm), int(dd))
        except ValueError:
            continue
        volume = num(o.get("volume")) or 0.0
        oi = num(o.get("open_interest")) or 0.0
        options.append(
            Option(
                root=root,
                expiry=expiry,
                right=cp,
                strike=int(strike8) / 1000,
                bid=num(o.get("bid")),
                ask=num(o.get("ask")),
                last=num(o.get("last_trade_price")),
                volume=max(0, int(volume)),
                oi=max(0, int(oi)),
                iv=(num(o.get("iv")) or None),
                gamma=(num(o.get("gamma")) or None),
                delta=num(o.get("delta")),
            )
        )
    asof = body.get("timestamp") or data.get("last_trade_time")
    return Chain(
        symbol=symbol.upper(),
        spot=spot,
        prev_close=num(data.get("prev_day_close")),
        asof=str(asof) if asof else None,
        options=tuple(options),
        change=num(data.get("price_change")),
        change_pct=num(data.get("price_change_percent")),
    )


def fetch(symbol: str, opener: Opener = urllib.request.urlopen, timeout: float = 20.0) -> Chain:
    return parse(get_json(quote_url(symbol), HEADERS, opener, timeout, retries=1), symbol)
