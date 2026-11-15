# Saad Radar · Gamma

لوحة تعرض مستويات القاما لصناع السوق (Call Wall و Put Wall و Flip و Net GEX والحركة المتوقعة
والفلو) على SPX و SPY و QQQ و 30 سهم أمريكي، من بيانات Cboe المجانية المتأخرة ~15 دقيقة.
تتحدث كل 5 دقائق وقت السوق على GitHub Actions وتنشر على GitHub Pages. للتعليم والمعلومات فقط،
وليست توصية.

A dealer-gamma dashboard (Call Wall, Put Wall, Flip, Net GEX, expected move, flow) for SPX, SPY,
QQQ and 30 large US stocks, built every 5 minutes in market hours from Cboe's free delayed option
data and published with GitHub Pages. Educational only, not investment advice.

## How the numbers are made (`gammadesk/`)
- Data: `cdn.cboe.com/api/global/delayed_quotes/options/{SYMBOL}.json` (`_SPX` for the index),
  unofficial and about 15 minutes delayed; fields per the open-source OpenBB Cboe provider.
- GEX per contract = gamma x open interest x 100 x spot^2 x 1%, + calls, - puts (dealers assumed
  long calls and short puts: a convention, weaker on single stocks). Gamma from Cboe, or
  Black-Scholes from the contract's IV when Cboe gives none.
- Call Wall / Put Wall = the chart's strike bin with the largest positive / negative net GEX.
- Flip = level nearest the price where total GEX changes sign, recomputing every contract's gamma
  with Black-Scholes (rates and dividends taken as 0) on a grid of levels.
- Expected move = at-the-money straddle of the last expiration in the view.
- Views: indexes and ETFs 0DTE (nearest expiration), 1DTE (the next), 5DTE (all within 5 days);
  stocks nearest, within 14 days, within 45 days.
- Flow: call and put volume, put/call, traded value (volume x mid x 100), top contracts by value,
  volume and Vol/OI (among the 50 largest by value).

## Run locally
```
python -m gammadesk.build --out site/data --symbols SPX,NVDA
python -m http.server -d site 8000
pytest -q
```

## Notes
- GitHub turns off scheduled workflows in a public repository after 60 days without activity.
  `keepalive.yml` re-enables both workflows through the Actions API every Monday so that does
  not happen; if it ever does, Actions > Build gamma dashboard > Enable workflow turns it back on.
