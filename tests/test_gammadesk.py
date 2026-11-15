import json
import math
from datetime import date, datetime

import pytest

from gammadesk import build, cboe, flow, gex
from gammadesk.cboe import Option
from gammadesk.net import FetchError
from gammadesk.profile import profile
from gammadesk.scopes import select
from tests.chains import body, osi

ET = gex.ET
NOW = datetime(2026, 11, 16, 11, 0, tzinfo=ET)  # Monday 11:00 New York
D0, D1, D2 = date(2026, 11, 16), date(2026, 11, 17), date(2026, 11, 20)
STRIKES = [7650 + 10 * i for i in range(15)]  # 7650 .. 7790
SPOT = 7724.1


def spx(expiries=(D0,), **kw):
    return body(SPOT, list(expiries), STRIKES, kw.pop("call_oi", {7750: 9000}),
                kw.pop("put_oi", {7700: 9000}), **kw)


# --- cboe parsing ------------------------------------------------------------------------------

def test_parse_reads_contracts_and_skips_odd_rows():
    b = spx()
    opts = b["data"]["options"]
    opts.append({"option": "SPXW1261116C07700000", "volume": 5})  # adjusted contract: skipped
    opts.append(dict(opts[0]))  # repeat: skipped
    opts.append("junk")
    chain = cboe.parse(b, "spx")
    assert chain.symbol == "SPX" and chain.spot == SPOT and chain.prev_close == SPOT - 10
    assert chain.asof == "2026-11-13 16:15:00" and len(chain.options) == 30
    c = chain.options[0]
    assert (c.root, c.expiry, c.right, c.strike) == ("SPXW", D0, "C", 7650.0)
    assert (c.oi, c.volume) == (100, 500)
    assert c.price == pytest.approx((c.bid + c.ask) / 2)
    assert cboe.quote_url("spx").endswith("/options/_SPX.json")
    assert cboe.quote_url("NVDA").endswith("/options/NVDA.json")


def test_parse_prefers_cboe_change_fields():
    b = spx()
    b["data"].update(price_change=-12.97, price_change_percent=-0.17, prev_day_close=SPOT)
    chain = cboe.parse(b, "SPX")
    data = build.build_symbol(chain, NOW)
    assert (data["change"], data["change_pct"]) == (-12.97, -0.17)


def test_parse_rejects_wrong_shapes():
    with pytest.raises(FetchError, match="unexpected response"):
        cboe.parse({"x": 1}, "SPX")
    with pytest.raises(FetchError, match="no options list"):
        cboe.parse({"data": {"current_price": 1}}, "SPX")
    with pytest.raises(FetchError, match="no underlying price"):
        cboe.parse({"data": {"options": []}}, "SPX")
    crossed = Option("X", D0, "C", 1, bid=2.0, ask=1.0, last=1.5, volume=1, oi=1, iv=None,
                     gamma=None, delta=None)
    assert crossed.price == 1.5  # a crossed quote falls back to the last trade


# --- gamma math --------------------------------------------------------------------------------

def test_black_scholes_gamma_known_value():
    # S=K=100, T=1y, 20% vol: d1 = 0.1, gamma = phi(0.1) / (100 x 0.2) = 0.019848
    assert gex.bs_gamma(100, 100, 1, 0.2) == pytest.approx(0.0198476, rel=1e-5)
    assert gex.bs_gamma(100, 100, 0, 0.2) == 0.0


def test_dollar_gex_units_and_sign():
    # gamma 0.01 x OI 100 x 100 shares x 100^2 x 1% = $10,000 per 1% move
    assert gex.dollar_gex(0.01, 100, 100, "C") == pytest.approx(10_000)
    assert gex.dollar_gex(0.01, 100, 100, "P") == pytest.approx(-10_000)


def test_walls_flip_and_expected_move():
    chain = cboe.parse(spx(), "SPX")
    rows = gex.by_strike(chain.options, chain.spot, NOW)
    cw, pw = gex.walls(rows)
    assert (cw, pw) == (7750.0, 7700.0)
    fl = gex.flip(list(chain.options), chain.spot, NOW, 0.06)
    assert fl is not None and pw < fl < cw
    em = gex.expected_move(list(chain.options), chain.spot, D0)
    k = min(STRIKES, key=lambda s: abs(s - SPOT))
    call = next(o for o in chain.options if o.strike == k and o.right == "C")
    put = next(o for o in chain.options if o.strike == k and o.right == "P")
    assert em == pytest.approx(call.price + put.price)
    assert gex.years_to_expiry(D0, datetime(2026, 11, 16, 16, 30, tzinfo=ET)) == gex.MIN_T


def test_flip_none_when_no_sign_change():
    chain = cboe.parse(spx(put_oi={k: 0 for k in STRIKES}), "SPX")  # calls only: all positive
    assert gex.flip(list(chain.options), chain.spot, NOW, 0.06) is None


# --- scopes, flow, profile -----------------------------------------------------------------------

def test_scopes_for_index_and_stock():
    exps = {date(2026, 11, 13), D0, D1, D2, date(2026, 12, 18), date(2027, 1, 15)}
    spx_scopes = select(exps, D0, "SPX")
    assert [(s.id, s.expiries) for s in spx_scopes] == [
        ("0DTE", (D0,)), ("1DTE", (D1,)), ("5DTE", (D0, D1, D2))]
    stock = select(exps, D0, "NVDA")
    assert [s.id for s in stock] == ["near", "14d", "45d"]
    assert stock[2].expiries == (D0, D1, D2, date(2026, 12, 18))
    assert select(set(), D0, "SPX") == []


def test_flow_summary_and_rankings():
    def opt(k, right, vol, oi, price):
        return Option("NVDA", D2, right, k, bid=price, ask=price, last=price, volume=vol, oi=oi,
                      iv=0.5, gamma=None, delta=None)

    opts = [opt(190, "C", 1000, 500, 2.0), opt(180, "P", 300, 0, 1.0), opt(200, "C", 0, 50, 0.5)]
    f = flow.summarize(opts, 185.0)
    assert (f["call_vol"], f["put_vol"], f["pc"]) == (1000, 300, 0.3)
    assert f["usd"] == 1000 * 2.0 * 100 + 300 * 1.0 * 100
    assert [r["k"] for r in f["top"]["usd"]] == [190, 180]  # no-volume contract left out
    assert f["top"]["voi"][0]["voi"] is None  # nothing was open: newest positions first
    assert f["top"]["usd"][0]["itm"] is False and f["top"]["usd"][1]["itm"] is False


def test_profile_bins_cover_the_walls():
    chain = cboe.parse(spx(), "SPX")
    rows = gex.by_strike(chain.options, chain.spot, NOW)
    p = profile(rows, chain.spot, 7750, 7700, 9.0)
    keys = [r["k"] for r in p["rows"]]
    assert p["bin"] == 10 and keys == sorted(keys, reverse=True)
    assert 7750 in keys and 7700 in keys and (p["cw_bin"], p["pw_bin"]) == (7750, 7700)
    assert profile([], SPOT, None, None, None)["rows"] == []


def test_profile_bins_split_halves_evenly():
    rows = [gex.StrikeRow(k, net=1e9) for k in (7690, 7695, 7700, 7705, 7710)]
    p = profile(rows, 7700, 7710, 7690, None, max_bins=8)  # 10-pt bins
    assert p["bin"] == 10
    assert {r["k"]: r["gex"] for r in p["rows"]} == {7710: 2.0, 7700: 2.0, 7690: 1.0}


def test_profile_keeps_small_single_stock_values():
    # $30K per 1% in a bin must keep its bar (4 decimals of $bn rounded it to 0)
    rows = [gex.StrikeRow(k, net=3e4) for k in (20.0, 21.0, 22.0)]
    p = profile(rows, 21.0, 22.0, 20.0, None, max_bins=8)
    assert [r["gex"] for r in p["rows"]] == [0.00003, 0.00003, 0.00003]


# --- build -------------------------------------------------------------------------------------

def test_build_writes_files_keeps_stale_and_reports_errors(tmp_path, monkeypatch):
    def fetch(symbol):
        if symbol == "NVDA":
            raise FetchError("HTTP 403")
        if symbol == "AMD":
            raise FetchError("TimeoutError")
        return cboe.parse(spx((D0, D1, D2)), symbol)

    monkeypatch.setattr(build, "_previous",
                        lambda url, s: {"symbol": s, "scopes": []} if s == "AMD" else None)
    out = tmp_path / "data"
    code = build.main(["--out", str(out), "--symbols", "SPX,NVDA,AMD",
                       "--fallback-url", "https://example.invalid/site"], fetch=fetch, now=NOW)
    assert code == 0
    index = json.loads((out / "index.json").read_text())
    assert [s["symbol"] for s in index["symbols"]] == ["SPX", "AMD"]
    assert index["errors"] == {"NVDA": "HTTP 403", "AMD": "TimeoutError"}
    assert index["stale"] == ["AMD"]
    data = json.loads((out / "SPX.json").read_text())
    assert data["kind"] == "index" and data["change"] == 10.0  # from prev_day_close
    s0 = data["scopes"][0]
    assert s0["id"] == "0DTE" and (s0["cw"], s0["pw"]) == (7750.0, 7700.0)
    bars = {r["k"]: r["gex"] for r in s0["profile"]["rows"]}
    assert bars[s0["cw"]] == max(bars.values()) and bars[s0["pw"]] == min(bars.values())
    assert (s0["profile"]["cw_bin"], s0["profile"]["pw_bin"]) == (s0["cw"], s0["pw"])
    assert s0["regime"] in ("positive", "negative") and s0["net"] != 0
    assert len(s0["levels"]) == 10 and s0["flow"]["top"]["usd"]
    assert json.loads((out / "AMD.json").read_text())["stale"] is True


def test_build_skips_outside_market_hours(tmp_path, monkeypatch):
    gh = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh))
    saturday = datetime(2026, 11, 14, 12, 0, tzinfo=ET)
    called = []
    code = build.main(["--out", str(tmp_path / "d"), "--only-in-session"],
                      fetch=lambda s: called.append(s), now=saturday)
    assert code == 0 and called == [] and gh.read_text() == "skip=true\n"
    assert build.in_session(NOW) and not build.in_session(datetime(2026, 11, 16, 16, 30, tzinfo=ET))


def test_osi_helper_round_trip():
    text = osi("SPXW", D0, "P", 7712.5)
    assert text == "SPXW261116P07712500"
    assert math.isclose(int(text[-8:]) / 1000, 7712.5)
