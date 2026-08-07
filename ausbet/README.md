# ausbet — Australian betting toolkit

All-in-one suite for the Australian punter: **bet tracker & bankroll manager**,
**odds comparison across bookmakers**, and **value / arbitrage / dutching /
hedging calculators**. Pure Python stdlib — zero dependencies.

> Gamble responsibly. This toolkit is for analysis and record-keeping; it
> cannot make a bookmaker pay out. Chasing losses is how people get hurt.

## Install

```bash
pip install -e ./ausbet        # editable install, adds `ausbet` command
# or run in place without installing:
python -m ausbet --help
```

## Quick start

```bash
# Odds conversion — all 6 formats, auto-detect input
ausbet convert 5/2
ausbet convert -200 --to fractional
ausbet convert 0.50 --from hk --to decimal

# Bet tracking (SQLite, default ./ausbet.db)
ausbet bet add --bookie Sportsbet --sport AFL --selection "Geelong h2h" \
    --odds 1.85 --stake 50
ausbet bet list --pending
ausbet bet settle 1 --result won
ausbet stats --bankroll 1000

# Value betting — EV, edge, fair odds, quarter-Kelly stake
ausbet value --odds 2.50 --prob 0.50 --bankroll 1000

# Scan a market against your own probability estimates
ausbet scan --odds "Geelong:1.85" --odds "Pies:2.00" \
    --prob "Geelong:0.55" --prob "Pies:0.45"

# Arbitrage / dutching / hedging
ausbet arb 2.10 2.05 --stake 100
ausbet dutch 2.5 3.1 4.2 --stake 100
ausbet hedge --back-odds 2.5 --back-stake 50 --lay-odds 2.6

# Odds comparison — offline sample, or live via the-odds-api.com
ausbet compare                     # bundled AFL/NRL sample, best odds + margins
ausbet compare --arb               # ...and scan for arbitrages
export ODDS_API_KEY=your_free_key  # https://the-odds-api.com (AU region)
ausbet compare --source oddsapi --cache /tmp/odds_cache.json

# Racing form scan — your runners vs the market
ausbet race --form form.csv --odds "Rocket Red:6.50" --odds "Lucky Lass:7.50"

# Bookie-vs-bookie price scan — your two bookies, one table
ausbet h2h                                    # Neds vs Sportsbet on the bundled sample
ausbet h2h --source oddsapi --cache /tmp/odds_cache.json --min-gap 2.0
ausbet h2h --sport NRL --top 5

# Multi / racing-special fairness — the multi price vs the equivalent singles
ausbet multi --leg "Collingwood:1.95" --leg "Brisbane:2.05" --offer 3.80
ausbet multi --leg "Collingwood:1.95" --leg "Brisbane:2.05" --offer 4.20 \
    --prob "Collingwood:0.52" --prob "Brisbane:0.50" --stake 10

# Auto-settle — pending h2h bets settled from final scores
ausbet results --auto --days 2               # live scores (needs ODDS_API_KEY)
ausbet results --file results.json           # offline: [{home, away, home_score, away_score, sport}]

# Betfair exchange — back + lay (creds via env, or offline fixture)
export BETFAIR_APP_KEY=... BETFAIR_USERNAME=... BETFAIR_PASSWORD=...
ausbet exchange markets --event-type 7          # horse racing markets
ausbet exchange book 1.234567890                # back/lay book for one market
ausbet compare --source betfair                 # exchange back prices in the comparator

# Arb watcher — poll sources, alert when a book goes under 100%
ausbet watch --once                             # single check (cron-friendly)
ausbet watch --source oddsapi --interval 600 --min-roi 0.5 --webhook https://...
ausbet watch --cycles 3 --quiet                 # bounded loop, silent when clean

# End-to-end offline walkthrough (tracker + compare + arb + value + formats)
ausbet demo
```

## Features

| Command | What it does |
|---|---|
| `convert` | Decimal / fractional / American / HK / Indo / Malay conversion |
| `bet add/list/settle/rm/export` | SQLite bet ledger with CSV export |
| `stats` | P&L, ROI, strike rate, avg odds, breakdown by sport & bookmaker |
| `value` | EV per $, edge %, fair odds, (fractional) Kelly stake |
| `scan` | Market scan vs your probability estimates, sorted by EV |
| `arb` | Arbitrage detection + guaranteed stake split (2+ outcomes) |
| `dutch` | Equal-profit stake split across any selection set |
| `hedge` | Equal-profit back/lay hedge maths |
| `compare` | Best price per outcome, per-bookie margin (overround) ranking |
| `race` | Racing form loader → probabilities → value scan vs market prices |
| `exchange` | Betfair API-ng: list markets, back/lay book (live or fixture) |
| `watch` | Arb watcher: poll any source, alert on sub-100% overrounds |
| `h2h` | Head-to-head price scan between your bookies (default Neds vs Sportsbet), gaps ranked |
| `multi` | Multi / racing-special fairness: price vs the singles, stacked-margin tax, model EV |
| `results` | Auto-settle pending h2h bets from final scores (live scores or JSON file) |
| `demo` | Offline walkthrough of the whole chain |

## Odds formats

| Format | Example | Meaning |
|---|---|---|
| decimal | `1.85` | return per $1 staked |
| fractional | `5/2`, `5-2` | profit per stake |
| american | `+150` / `-200` | win 150 on 100 / stake 200 to win 100 |
| hk | `0.50` | profit per $1 staked |
| indo | `+2.00` / `-1.25` | win 2 per 1 / stake 1.25 to win 1 |
| malay | `+0.80` / `-0.80` | win 0.8 per 1 / stake 0.8 to win 1 |

Decimal / fractional / American auto-detect; HK / Indo / Malay are ambiguous
with decimal, so pass `--from hk|indo|malay` explicitly.

## Architecture

```
ausbet/
├── pyproject.toml       standalone package (src layout)
├── README.md
├── src/ausbet/
│   ├── __init__.py      version
│   ├── __main__.py      python -m ausbet
│   ├── cli.py           argparse CLI + demo
│   ├── odds.py          format parsing/conversion (decimal canonical)
│   ├── bankroll.py      Kelly / flat / percent staking
│   ├── value.py         EV, edge, fair odds, market scanner
│   ├── arbitrage.py     arb / dutch / hedge maths
│   ├── tracker.py       SQLite BetStore + P&L Stats
│   ├── compare.py       OddsSource protocol: StaticSource + TheOddsAPI
│   ├── form.py          racing form loader + probability model
│   ├── betfair.py       Betfair API-ng adapter (back + lay, fixture mode)
│   ├── watch.py         arb watcher loop + webhook notify
│   ├── multi.py         multi / parlay / racing-special fairness vs the singles
│   ├── results.py       auto-settle pending h2h bets from final scores
│   └── data/            sample_market.json, sample_form.csv, sample_betfair.json
└── tests/               171 pytest tests (no network)
```

### Live odds (`compare --source oddsapi`)

The comparator uses [the-odds-api.com](https://the-odds-api.com) — a free API
whose AU coverage includes Sportsbet, Ladbrokes, Bet365, TAB, Neds, Betfair
and PointsBet. Set `ODDS_API_KEY` (free signup, ~500 req/month) and cache
responses with `--cache` to stay inside the free tier. The `OddsSource`
protocol makes it trivial to add other adapters.

### Betfair exchange (`exchange`, `compare --source betfair`)

Official Betfair API-ng via stdlib urllib. Credentials come from env vars:
`BETFAIR_APP_KEY` (register a free app key at developer.betfair.com),
`BETFAIR_USERNAME`, `BETFAIR_PASSWORD`. Back prices feed the comparator as a
bookmaker; lay prices ride along and render as a side-by-side, so you can
price a real hedge (back at bookie, lay on the exchange). Without credentials,
`--fixture` replays a saved catalogue+book JSON — the bundled sample keeps
everything testable offline.

### Racing form (`race`)

CSV/JSON of runners (number, name, barrier, weight kg, form figures like
`231x45`, career starts/wins, last-start position, jockey, trainer,
scratched). The probability model is a deliberate, transparent heuristic —
last-start, recent form figures, career win ratio and weight, normalised to a
full book — and `race --odds NAME:ODDS ...` flags any runner whose market
price beats its form-derived fair odds. Swap in your own model by feeding
`scan` the probabilities directly.

### Arb watcher (`watch`)

Poll any source (`static` default, `oddsapi`, `betfair`) on an interval;
alert with a stake plan whenever the best prices sum to under 100%
overround. `--once` runs a single check and exits — that's the cron-friendly
shape. `--webhook` POSTs the alert as JSON to any endpoint (e.g. a Telegram
bot or virgo webhook).

### Stats semantics

- Pending bets are excluded from staked/returned; shown as open exposure.
- `void` counts as settled with the stake returned.
- A won bet with no explicit payout defaults to `odds × stake`.

## Roadmap

- [x] Betfair exchange adapter (official API, lay-side odds)
- [x] Racing form loader (CSV scratchings, weights) feeding `scan`
- [x] Automated odds snapshot job (cron) that alerts on arbs
- [ ] Excel export + simple HTML report
- [ ] Track-the-tracker: bankroll curve over time

## Tests

```bash
cd ausbet && /c/Python314/python.exe -m pytest tests/ -v
```
