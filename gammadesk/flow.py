"""Option flow summary for a set of contracts: volume, put/call, traded value, top contracts."""

from __future__ import annotations

from collections.abc import Sequence

from gammadesk.cboe import Option

TOP = 10
VOI_POOL = 50  # Vol/OI is ranked among the 50 contracts with the most traded value


def summarize(options: Sequence[Option], spot: float, top: int = TOP) -> dict:
    call_vol = sum(o.volume for o in options if o.right == "C")
    put_vol = sum(o.volume for o in options if o.right == "P")
    rows = []
    for o in options:
        if o.volume <= 0:
            continue
        price = o.price or 0.0
        rows.append(
            {
                "k": o.strike,
                "side": o.right,
                "exp": o.expiry.isoformat(),
                "vol": o.volume,
                "oi": o.oi,
                "voi": round(o.volume / o.oi, 2) if o.oi > 0 else None,
                "usd": round(o.volume * price * 100),
                "itm": (o.strike < spot) if o.right == "C" else (o.strike > spot),
            }
        )
    by_usd = sorted(rows, key=lambda r: r["usd"], reverse=True)
    by_vol = sorted(rows, key=lambda r: r["vol"], reverse=True)
    pool = by_usd[:VOI_POOL]
    by_voi = sorted(
        pool, key=lambda r: float("inf") if r["voi"] is None else r["voi"], reverse=True
    )
    return {
        "call_vol": call_vol,
        "put_vol": put_vol,
        "pc": round(put_vol / call_vol, 2) if call_vol else None,
        "usd": sum(r["usd"] for r in rows),
        "top": {"usd": by_usd[:top], "vol": by_vol[:top], "voi": by_voi[:top]},
    }
