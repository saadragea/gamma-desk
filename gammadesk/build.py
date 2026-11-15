"""Build the dashboard data files.

python -m gammadesk.build --out site/data [--only-in-session] [--symbols SPX,NVDA]
                          [--fallback-url https://<user>.github.io/<repo>]

Writes one <SYMBOL>.json per symbol and index.json. A symbol whose fetch fails keeps the copy
already published at --fallback-url, marked stale, so one bad fetch never blanks the page.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from datetime import time as dtime
from pathlib import Path

from gammadesk import cboe, flow, gex
from gammadesk.cboe import Chain
from gammadesk.net import FetchError, get_json
from gammadesk.profile import profile
from gammadesk.scopes import Scope, kind, select

# SPX, SPY and QQQ, then the 30 stocks of the Telegram scanner (most options volume in 2026,
# Macroption, Cboe group exchanges; GOOG dropped as a duplicate of GOOGL, SNDK in its place).
SYMBOLS = (
    "SPX", "SPY", "QQQ",
    "NVDA", "TSLA", "AAPL", "AMZN", "MSFT", "INTC", "MU", "PLTR", "META", "MSTR",
    "AMD", "NFLX", "GOOGL", "SMCI", "SOFI", "MARA", "IREN", "SPCX", "ORCL", "AVGO",
    "HOOD", "NOK", "COIN", "NBIS", "CRWV", "ONDS", "TSM", "BMNR", "BABA", "SNDK",
)
FLIP_WIDTH = {"index": 0.06, "stock": 0.15}
SESSION = (dtime(9, 25), dtime(16, 20))  # New York; covers the open and SPX's 16:15 close

Fetch = Callable[[str], Chain]


def _r(x: float | None, d: int = 2) -> float | None:
    return None if x is None else round(x, d)


def build_scope(chain: Chain, scope: Scope, now: datetime) -> dict:
    spot = chain.spot
    opts = [o for o in chain.options if o.expiry in scope.expiries]
    rows = gex.by_strike(opts, spot, now)
    net = sum(r.net for r in rows)
    cw, pw = gex.walls(rows)
    fl = gex.flip(opts, spot, now, FLIP_WIDTH[kind(chain.symbol)])
    em = gex.expected_move(opts, spot, scope.expiries[-1])
    if fl is not None:
        regime = "positive" if spot > fl else "negative"
    else:
        regime = "positive" if net > 0 else "negative" if net < 0 else "unknown"
    top = sorted(rows, key=lambda r: abs(r.net), reverse=True)[:10]
    levels = [
        {
            "k": r.k,
            "gex": round(r.net / 1e6, 1),
            "oi": r.oi_c + r.oi_p,
            "vol": r.vol_c + r.vol_p,
            "iv": _r(r.iv * 100 if r.iv else None, 1),
        }
        for r in sorted(top, key=lambda r: r.k, reverse=True)
    ]
    return {
        "id": scope.id,
        "label": scope.label,
        "expiries": [e.isoformat() for e in scope.expiries],
        "contracts": len(opts),
        "net": round(net / 1e9, 4),
        "flip": _r(fl),
        "cw": cw,
        "pw": pw,
        "em": _r(em),
        "em_pct": _r(em / spot * 100 if em else None),
        "regime": regime,
        "profile": profile(rows, spot, cw, pw, em),
        "levels": levels,
        "flow": flow.summarize(opts, spot),
    }


def build_symbol(chain: Chain, now: datetime) -> dict:
    scopes = select({o.expiry for o in chain.options}, now.date(), chain.symbol)
    change = chain.spot - chain.prev_close if chain.prev_close else None
    return {
        "symbol": chain.symbol,
        "kind": kind(chain.symbol),
        "spot": round(chain.spot, 2),
        "change": _r(change),
        "change_pct": _r(change / chain.prev_close * 100 if change is not None else None),
        "asof": chain.asof,
        "built": now.isoformat(timespec="seconds"),
        "scopes": [build_scope(chain, s, now) for s in scopes],
    }


def in_session(now: datetime) -> bool:
    return now.weekday() < 5 and SESSION[0] <= now.time() <= SESSION[1]


def _github_output(key: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")


def _previous(base_url: str, symbol: str) -> dict | None:
    try:
        body = get_json(
            f"{base_url.rstrip('/')}/data/{symbol}.json", {}, urllib.request.urlopen, 15, 0
        )
    except FetchError:
        return None
    return body if isinstance(body, dict) and body.get("symbol") == symbol else None


def main(
    argv: list[str] | None = None, fetch: Fetch = cboe.fetch, now: datetime | None = None
) -> int:
    p = argparse.ArgumentParser(prog="python -m gammadesk.build")
    p.add_argument("--out", default="site/data")
    p.add_argument("--symbols", help="comma-separated, default: the built-in list")
    p.add_argument("--only-in-session", action="store_true", help="do nothing outside hours")
    p.add_argument("--fallback-url", help="published site, to keep a symbol whose fetch fails")
    args = p.parse_args(argv)

    now = now or datetime.now(gex.ET)
    if args.only_in_session and not in_session(now):
        _github_output("skip", "true")
        print(f"outside market hours ({now:%a %H:%M} ET): nothing to do")
        return 0

    symbols = [s.strip().upper() for s in args.symbols.split(",")] if args.symbols else SYMBOLS
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    built: dict[str, dict] = {}
    errors: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {s: pool.submit(fetch, s) for s in symbols}
        for s, fut in futures.items():
            try:
                built[s] = build_symbol(fut.result(), now)
            except FetchError as exc:
                errors[s] = str(exc)
            except Exception as exc:  # a bug for one symbol must not blank the others
                errors[s] = f"build error: {type(exc).__name__}"
                traceback.print_exc()
    stale: list[str] = []
    if args.fallback_url:
        for s in symbols:
            if s not in built and (prev := _previous(args.fallback_url, s)) is not None:
                prev["stale"] = True
                built[s] = prev
                stale.append(s)
    for s, data in built.items():
        (out / f"{s}.json").write_text(json.dumps(data, separators=(",", ":")), "utf-8")
    index = {
        "built": now.isoformat(timespec="seconds"),
        "symbols": [{"symbol": s, "kind": kind(s)} for s in symbols if s in built],
        "errors": errors,
        "stale": stale,
    }
    (out / "index.json").write_text(json.dumps(index, separators=(",", ":")), "utf-8")
    _github_output("skip", "false")
    print(f"built {len(built) - len(stale)}/{len(symbols)}, stale {stale or 'none'}, "
          f"errors {errors or 'none'}")
    return 0 if built else 1


if __name__ == "__main__":
    sys.exit(main())
