"""GEX profile for the chart: net GEX summed into round-number strike bins around the price."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

from gammadesk.gex import StrikeRow

NICE = (0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 250, 500, 1000)
MAX_BINS = 24


def _key(x: float, size: float) -> float:
    return round(round(x / size) * size, 4)


def profile(
    rows: Sequence[StrikeRow],
    spot: float,
    cw: float | None,
    pw: float | None,
    em: float | None,
    max_bins: int = MAX_BINS,
) -> dict:
    """Bins covering both walls and 1.5 expected moves (at least 0.4% of the price) each side."""
    span = max(
        abs(cw - spot) if cw is not None else 0.0,
        abs(pw - spot) if pw is not None else 0.0,
        (em or 0.0) * 1.5,
        spot * 0.004,
    ) * 1.15
    inside = [r for r in rows if spot - span <= r.k <= spot + span]
    if not inside:
        return {"bin": None, "rows": [], "cw_bin": None, "pw_bin": None}
    ks = sorted({r.k for r in inside})
    spacing = min((b - a for a, b in pairwise(ks)), default=1.0)
    need = max(spacing, 2 * span / max_bins)
    size = next((n for n in NICE if n >= need - 1e-9), NICE[-1])
    bins: dict[float, float] = {}
    for r in inside:
        key = _key(r.k, size)
        bins[key] = bins.get(key, 0.0) + r.net
    return {
        "bin": size,
        "rows": [{"k": k, "gex": round(v / 1e9, 4)} for k, v in sorted(bins.items(), reverse=True)],
        "cw_bin": None if cw is None else _key(cw, size),
        "pw_bin": None if pw is None else _key(pw, size),
    }
