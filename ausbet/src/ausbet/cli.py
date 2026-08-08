"""ausbet CLI — tracker, comparator, value & arbitrage calculators.

Subcommands:
    convert   Odds format conversion (all 6 formats)
    bet       add / list / settle / rm / export
    stats     P&L, ROI, strike rate, by sport & bookmaker
    value     EV / edge / fair odds / Kelly stake
    scan      scan a market against your probability estimates for value
    arb       arbitrage detection + stake split
    dutch     equal-profit stake split
    hedge     equal-profit back/lay hedge
    compare   best-odds + overround across bookmakers (static file or live API)
    h2h       bookie-vs-bookie price scan (default: Neds vs Sportsbet)
    multi     multi / racing-special fairness vs placing the singles
    results   auto-settle pending h2h bets from final scores
    demo      offline end-to-end walkthrough
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from ausbet import __version__
from ausbet import arbitrage as arb
from ausbet import form as form_mod
from ausbet import multi as multi_mod
from ausbet import odds as odds_mod
from ausbet import results as results_mod
from ausbet import value as value_mod
from ausbet import watch as watch_mod
from ausbet.bankroll import kelly_fraction, kelly_stake
from ausbet.betfair import BetfairExchangeSource
from ausbet.compare import StaticSource, TheOddsAPISource, compare, head_to_head
from ausbet.odds import FORMATS, convert, format_odds, overround_pct, parse
from ausbet.tracker import Bet, BetStore

SAMPLE_MARKETS = Path(__file__).parent / "data" / "sample_market.json"
SAMPLE_FORM = Path(__file__).parent / "data" / "sample_form.csv"
SAMPLE_BETFAIR = Path(__file__).parent / "data" / "sample_betfair.json"

DEFAULT_DB = "ausbet.db"


# ---------------------------------------------------------------- helpers

def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(lines)


def _open_store(db: str) -> BetStore:
    return BetStore(db)


# ---------------------------------------------------------------- convert

def cmd_convert(args: argparse.Namespace) -> int:
    decimal = parse(args.odds, fmt=args.from_fmt)
    if args.to:
        print(f"{args.odds} ({args.from_fmt or 'detected'}) -> {args.to}: {format_odds(decimal, args.to)}")
    else:
        print(f"decimal {decimal:.2f}  (= {args.odds} {'[' + args.from_fmt + ']' if args.from_fmt else ''})\n")
        for fmt in FORMATS:
            if fmt == "decimal":
                continue
            print(f"  {fmt:<10} {format_odds(decimal, fmt)}")
    return 0


# ---------------------------------------------------------------- bet CRUD

def cmd_bet(args: argparse.Namespace) -> int:
    store = _open_store(args.db)
    try:
        if args.action == "add":
            bet = Bet(
                bookmaker=args.bookie,
                sport=args.sport,
                competition=args.competition or "",
                market=args.market or "",
                selection=args.selection,
                odds=parse(args.odds),
                stake=args.stake,
                result=args.result,
                payout=args.payout,
            )
            bid = store.add(bet)
            print(f"added bet #{bid}: {bet.sport} {bet.selection} @ {bet.odds:.2f} for ${bet.stake:.2f}")
        elif args.action == "list":
            bets = store.list(pending_only=args.pending, limit=args.limit)
            if not bets:
                print("no bets recorded")
                return 0
            rows = [
                [str(b.id), b.timestamp[:16], b.bookmaker, b.sport, b.selection,
                 f"{b.odds:.2f}", f"${b.stake:.2f}", b.result or "pending"]
                for b in bets
            ]
            print(_table(["id", "time", "bookie", "sport", "selection", "odds", "stake", "result"], rows))
        elif args.action == "settle":
            updated = store.settle(args.bet_id, args.result, args.payout)
            print(f"bet #{updated.id}: {updated.result} — returned ${updated.payout:.2f}")
        elif args.action == "rm":
            store.delete(args.bet_id)
            print(f"deleted bet #{args.bet_id}")
        elif args.action == "export":
            path = store.export_csv(args.path)
            print(f"exported {len(store.list(limit=10_000))} bets to {path}")
    finally:
        store.close()
    return 0


# ---------------------------------------------------------------- stats

def cmd_stats(args: argparse.Namespace) -> int:
    store = _open_store(args.db)
    try:
        s = store.stats()
    finally:
        store.close()
    print(_table(
        ["metric", "value"],
        [
            ["total bets", str(s.total_bets)],
            ["settled", f"{s.settled} (pending: {s.pending})"],
            ["staked", f"${s.staked:.2f}"],
            ["returned", f"${s.returned:.2f}"],
            ["profit", f"${s.profit:+.2f}"],
            ["ROI", f"{s.roi_pct:+.2f}%"],
            ["strike rate", f"{s.strike_rate_pct:.1f}%"],
            ["avg odds (decided)", f"{s.avg_odds:.2f}"],
        ],
    ))
    for label, dim in (("by sport", s.by_sport), ("by bookmaker", s.by_bookmaker)):
        if not dim:
            continue
        print(f"\n{label}:")
        rows = [
            [k, str(v["bets"]), f"${v['staked']:.2f}", f"${v['profit']:+.2f}", f"{v['roi_pct']:+.2f}%"]
            for k, v in sorted(dim.items(), key=lambda kv: kv[1]["profit"], reverse=True)
        ]
        print(_table(["key", "bets", "staked", "profit", "ROI"], rows))
    if args.bankroll is not None:
        print(f"\nbankroll after {s.profit:+.2f}: ${args.bankroll + s.profit:.2f}")
    return 0


# ---------------------------------------------------------------- value

def cmd_value(args: argparse.Namespace) -> int:
    decimal = parse(args.odds)
    ev = value_mod.expected_value(decimal, args.prob)
    fair = value_mod.fair_odds(args.prob)
    kelly = kelly_fraction(decimal, args.prob)
    print(f"odds {decimal:.2f}  prob {args.prob:.4f}")
    print(f"  fair odds      {fair:.2f}")
    print(f"  edge           {ev * 100:+.2f}% per $1 staked")
    print(f"  value bet      {'YES' if ev > 0 else 'NO'}")
    if args.bankroll:
        stake = kelly_stake(decimal, args.prob, args.bankroll, args.kelly_fraction)
        print(f"  kelly ({args.kelly_fraction:.0%}) stake  ${stake:.2f}  (full-kelly fraction {kelly:.4f})")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    selections = []
    for item in args.odds:
        name, _, o = item.rpartition(":")
        selections.append((name.strip(), o.strip()))
    probs = {}
    for item in args.prob:
        name, _, p = item.rpartition(":")
        probs[name.strip()] = float(p)
    if len(selections) != len(probs) or {n for n, _ in selections} != set(probs):
        print("selections and probabilities must name the same set of outcomes", file=sys.stderr)
        return 1
    picks = value_mod.scan_market(selections, probs)
    rows = [
        [p.selection, f"{p.odds:.2f}", f"{p.prob_est:.2%}",
         f"{p.ev_per_unit:+.3f}", f"{p.edge_pct:+.1f}%", f"{p.kelly_fraction:.3f}",
         "VALUE" if p.is_value else "-"]
        for p in picks
    ]
    print(_table(["selection", "odds", "prob", "EV/$", "edge", "kelly f", "flag"], rows))
    return 0


# ---------------------------------------------------------------- arb / dutch / hedge

def cmd_arb(args: argparse.Namespace) -> int:
    odds = [parse(o) for o in args.odds]
    print(f"overround: {overround_pct(odds):.2f}%  ({'ARBITRAGE' if arb.is_arbitrage(odds) else 'no arbitrage'})")
    try:
        plan = arb.arbitrage_stakes(odds, args.stake)
    except ValueError as exc:
        print(f"  {exc}")
        return 1
    _print_plan(plan, args.stake)
    return 0


def cmd_dutch(args: argparse.Namespace) -> int:
    odds = [parse(o) for o in args.odds]
    plan = arb.dutch_stakes(odds, args.stake)
    print(f"overround: {overround_pct(odds):.2f}%")
    _print_plan(plan, args.stake)
    return 0


def _print_plan(plan: arb.StakingPlan, total: float) -> None:
    rows = [
        [f"selection {i + 1}", f"{o:.2f}", f"${s:.2f}"]
        for i, (o, s) in enumerate(zip(plan.odds, plan.stakes))
    ]
    print(_table(["", "odds", "stake"], rows))
    print(f"total staked        ${plan.total:.2f}")
    print(f"guaranteed return   ${plan.guaranteed_return:.2f}")
    print(f"locked profit       ${plan.profit:+.2f}  (ROI {plan.roi_pct:+.2f}%)")


def cmd_hedge(args: argparse.Namespace) -> int:
    lay_stake, profit = arb.hedge_stake(args.back_odds, args.back_stake, args.lay_odds)
    print(f"back  {args.back_stake:.2f} @ {args.back_odds:.2f}")
    print(f"lay   {lay_stake:.2f} @ {args.lay_odds:.2f}")
    print(f"locked profit either way: ${profit:+.2f}")
    return 0


# ---------------------------------------------------------------- compare

def cmd_compare(args: argparse.Namespace) -> int:
    if args.source == "static":
        source = StaticSource(args.file or SAMPLE_MARKETS)
    elif args.source == "oddsapi":
        source = TheOddsAPISource(cache_path=args.cache)
    elif args.source == "betfair":
        source = BetfairExchangeSource(event_type_ids=(args.event_type,), fixture=args.fixture)
    else:
        print(f"unknown source {args.source!r}", file=sys.stderr)
        return 1
    try:
        if isinstance(source, TheOddsAPISource):
            keys = [k.strip() for k in args.sport_keys.split(",")] if args.sport_keys else None
            markets = source.fetch(sport_keys=keys)
        else:
            markets = source.fetch()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    comps = compare(markets)
    if not comps:
        print("no markets to compare")
        return 0
    for c in comps:
        print(c.render(top=args.top))
    if args.arb:
        print("== arbitrage scan (best price across bookies per outcome) ==")
        found = 0
        for c in comps:
            if c.best_overround_pct < 100.0:
                odds = [o for _, o in c.best.values()]
                plan = arb.arbitrage_stakes(odds, 100.0)
                print(f"\nARB FOUND: {c.sport} — {c.event} [{c.market}]  (overround {c.best_overround_pct:.2f}%)")
                for name, stake, o in zip(c.best, plan.stakes, plan.odds):
                    print(f"   {name:<24} ${stake:>7.2f} @ {o:.2f}")
                found += 1
        if not found:
            print("no arbitrages found in current prices")
    return 0


# ---------------------------------------------------------------- race form

def cmd_race(args: argparse.Namespace) -> int:
    runners = form_mod.load_form(args.form)
    odds = [(n.strip(), o.strip()) for n, _, o in (x.rpartition(":") for x in args.odds)]
    probs, _picks = form_mod.race_scan(runners, odds)
    odds_map = {n: parse(o) for n, o in odds}
    rows = []
    for r in sorted((x for x in runners if not x.scratched), key=lambda x: x.number):
        p = probs[r.name]
        fair = value_mod.fair_odds(p)
        actual = odds_map.get(r.name)
        ev = value_mod.expected_value(actual, p) if actual else None
        flag = "VALUE" if ev is not None and ev > 0 else ("no odds" if actual is None else "-")
        rows.append([
            str(r.number), r.name,
            f"{r.weight:.1f}" if r.weight is not None else "-",
            r.form_figures or "-",
            str(r.last_start) if r.last_start is not None else "—",
            f"{p:.1%}", f"{fair:.2f}",
            f"{actual:.2f}" if actual else "-",
            f"{ev:+.3f}" if ev is not None else "-",
            flag,
        ])
    print(_table(["#", "runner", "wgt", "form", "last", "prob", "fair", "odds", "EV/$", "flag"], rows))
    scratches = [r.name for r in runners if r.scratched]
    if scratches:
        print(f"scratched: {', '.join(scratches)}")
    return 0


# ---------------------------------------------------------------- exchange

def cmd_exchange(args: argparse.Namespace) -> int:
    source = BetfairExchangeSource(event_type_ids=(args.event_type,), fixture=args.fixture)
    try:
        markets = source.fetch()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.action == "markets":
        if not markets:
            print("no markets returned")
            return 0
        for m in markets:
            print(f"{m.market_id:<16} {m.event:<34} {m.market}  ({len(m.outcomes)} runners)")
        return 0
    market = next((m for m in markets if m.market_id == args.market_id), None)
    if market is None:
        print(f"market {args.market_id!r} not found in fetched markets", file=sys.stderr)
        return 1
    rows = []
    for o in market.outcomes:
        gap = f"{(1.0 / o.lay - 1.0 / o.odds) * 100:.2f}%" if o.lay else "-"
        rows.append([o.name, f"{o.odds:.2f}", f"{o.lay:.2f}" if o.lay else "-", gap])
    print(f"{market.sport} — {market.event} [{market.market}]")
    print(_table(["runner", "back", "lay", "back-lay gap"], rows))
    return 0


# ---------------------------------------------------------------- watch

def cmd_watch(args: argparse.Namespace) -> int:
    if args.source == "static":
        source = StaticSource(args.file or SAMPLE_MARKETS)
    elif args.source == "oddsapi":
        source = TheOddsAPISource(cache_path=args.cache)
    else:
        source = BetfairExchangeSource(event_type_ids=(args.event_type,), fixture=args.fixture)
    if args.once:
        try:
            alerts = watch_mod.watch_once(source, args.min_roi, args.stake)
        except (RuntimeError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if alerts:
            watch_mod.notify(alerts, args.webhook)
        else:
            print("no arbs found")
        return 0
    watch_mod.watch_loop(
        source,
        interval=args.interval,
        cycles=args.cycles,
        min_roi=args.min_roi,
        stake=args.stake,
        webhook_url=args.webhook,
        quiet=args.quiet,
    )
    return 0


# ---------------------------------------------------------------- h2h scan

def cmd_h2h(args: argparse.Namespace) -> int:
    if args.source == "static":
        source = StaticSource(args.file or SAMPLE_MARKETS)
    elif args.source == "oddsapi":
        source = TheOddsAPISource(cache_path=args.cache)
    else:
        source = BetfairExchangeSource(event_type_ids=(args.event_type,), fixture=args.fixture)
    try:
        if isinstance(source, TheOddsAPISource):
            keys = [k.strip() for k in args.sport_keys.split(",")] if args.sport_keys else None
            markets = source.fetch(sport_keys=keys)
        else:
            markets = source.fetch()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    bookies = [b.strip() for b in args.bookies.split(",") if b.strip()]
    rows = head_to_head(markets, bookies=bookies, sport_filter=args.sport)
    if args.min_gap is not None:
        rows = [r for r in rows if r.gap_pct >= args.min_gap]
    if not rows:
        print(
            "no h2h markets priced by all requested bookies"
            + (f" with a gap >= {args.min_gap}%" if args.min_gap is not None else "")
        )
        return 0
    current: tuple | None = None
    shown = 0
    for r in rows:
        key = (r.sport, r.event)
        if key != current:
            print(f"\n{r.sport} — {r.event} [h2h]")
            current = key
        prices = "   ".join(f"{b}: {o:.2f}" for b, o in r.prices.items())
        print(f"  {r.outcome:<26} {prices}   BEST {r.better} @ {r.better_odds:.2f}  (+{r.gap_pct:.1f}%)")
        shown += 1
        if args.top and shown >= args.top:
            break
    big = max(rows, key=lambda r: r.gap_pct)
    print(
        f"\n{len(rows)} priced gap(s) — biggest: {big.event} {big.outcome} — "
        f"{big.better} @ {big.better_odds:.2f} is +{big.gap_pct:.1f}% over the other bookie"
    )
    return 0


# ---------------------------------------------------------------- multi

def cmd_multi(args: argparse.Namespace) -> int:
    legs = []
    for item in args.leg:
        name, _, o = item.rpartition(":")
        legs.append((name.strip(), o.strip()))
    probs = None
    if args.prob:
        probs = {}
        for item in args.prob:
            name, _, p = item.rpartition(":")
            probs[name.strip()] = float(p)
    a = multi_mod.analyze_multi(legs, offer=args.offer, stake=args.stake, probs=probs)
    rows = [[leg.name, f"{leg.odds:.2f}", f"{1.0 / leg.odds:.1%}"] for leg in a.legs]
    print(_table(["leg", "single odds", "implied"], rows))
    print(f"combined implied      {a.combined_implied:.4f}")
    print(f"fair price (singles)  {a.singles_price:.2f}")
    if a.offer is not None:
        print(f"offered price         {a.offer:.2f}  ({a.diff_pct:+.1f}% vs singles)")
        if a.stake:
            n = len(a.legs)
            singles_ret = (a.stake / n) * sum(leg.odds for leg in a.legs)
            print(
                f"${a.stake:.2f} on the multi pays ${a.stake * a.offer:.2f} if all legs land; "
                f"the same ${a.stake:.2f} split across the singles pays ${singles_ret:.2f} if all legs land"
            )
    if a.model_fair is not None:
        ev = f"   EV {a.model_ev:+.3f}/$" if a.model_ev is not None else ""
        print(f"your model fair       {a.model_fair:.2f}{ev}")
    print(f"verdict: {a.verdict}")
    return 0


# ---------------------------------------------------------------- results

def cmd_results(args: argparse.Namespace) -> int:
    if args.file:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
        games = results_mod.games_from_scores_api(raw)
    elif args.auto:
        source = TheOddsAPISource(cache_path=args.cache)
        try:
            keys = [k.strip() for k in args.sport_keys.split(",")] if args.sport_keys else None
            raw = source.fetch_scores(days=args.days, sport_keys=keys)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        games = results_mod.games_from_scores_api(raw)
    else:
        print("use --auto (live scores) or --file <results.json>", file=sys.stderr)
        return 1
    store = _open_store(args.db)
    try:
        report = results_mod.auto_settle(store, games)
    finally:
        store.close()
    if report.settled:
        rows = [
            [str(b.id), b.sport, b.selection, b.result or "", f"${b.payout or 0:.2f}"]
            for b in report.settled
        ]
        print(f"settled {len(report.settled)}:")
        print(_table(["id", "sport", "selection", "result", "payout"], rows))
    else:
        print("no pending h2h bets settled")
    for label, bets in (
        ("unmatched (no game found)", report.unmatched),
        ("ambiguous team match", report.ambiguous),
        ("draw — left pending", report.draws),
    ):
        if bets:
            print(f"{label}: {', '.join(f'#{b.id} {b.selection}' for b in bets)}")
    return 0


# ---------------------------------------------------------------- demo

def cmd_demo(args: argparse.Namespace) -> int:
    tmp = tempfile.TemporaryDirectory(prefix="ausbet_demo_")
    db = Path(tmp.name) / "demo.db"
    store = BetStore(db)
    try:
        sample_bets = [
            ("Sportsbet", "AFL", "Geelong h2h", 1.85, 50.0, "won"),
            ("Ladbrokes", "AFL", "Collingwood h2h", 2.00, 25.0, "lost"),
            ("Betfair", "NRL", "Melbourne -4.5", 1.90, 40.0, "won"),
            ("Sportsbet", "NRL", "Brisbane +4.5", 1.92, 30.0, "lost"),
            ("TAB", "Cricket", "Smith top runscorer", 4.50, 10.0, "void"),
            ("PointsBet", "AFL", "Geelong 40+ margin", 5.00, 20.0, None),
        ]
        for bookie, sport, selection, odds, stake, result in sample_bets:
            store.add(Bet(bookmaker=bookie, sport=sport, competition="", market="h2h",
                          selection=selection, odds=odds, stake=stake, result=result))
        print("=== 1. BET TRACKER ===")
        print(_table(
            ["id", "time", "bookie", "sport", "selection", "odds", "stake", "result"],
            [[str(b.id), b.timestamp[:16], b.bookmaker, b.sport, b.selection,
              f"{b.odds:.2f}", f"${b.stake:.2f}", b.result or "pending"] for b in store.list()],
        ))
        s = store.stats()
        print(f"\nROI {s.roi_pct:+.2f}%  profit ${s.profit:+.2f}  strike {s.strike_rate_pct:.1f}%  "
              f"(staked ${s.staked:.2f}, pending {s.pending})")
    finally:
        store.close()

    print("\n=== 2. ODDS COMPARISON (static sample) ===")
    comps = compare(StaticSource(SAMPLE_MARKETS).fetch())
    for c in comps:
        print(c.render())

    print("=== 3. ARBITRAGE SCAN ===")
    for c in comps:
        if c.best_overround_pct < 100.0:
            odds = [o for _, o in c.best.values()]
            names = [n for n in c.best]
            plan = arb.arbitrage_stakes(odds, 100.0)
            print(f"ARB: {c.event} [{c.market}]  overround {c.best_overround_pct:.2f}%")
            for name, stake, o in zip(names, plan.stakes, plan.odds):
                print(f"   {name:<22} ${stake:>7.2f} @ {o:.2f}")
            print(f"   -> lock ${plan.profit:+.2f} on $100")

    print("\n=== 4. VALUE / KELLY ===")
    for odds, prob in ((2.10, 0.55), (1.85, 0.45)):
        ev = value_mod.expected_value(odds, prob)
        stake = kelly_stake(odds, prob, 1000.0)
        print(f"odds {odds:.2f} prob {prob:.2f} -> EV {ev:+.3f}/$ "
              f"{'VALUE' if ev > 0 else 'no edge'}; quarter-kelly on $1000: ${stake:.2f}")

    print("\n=== 5. FORMATS ===")
    for v, f in (("1.85", None), ("5/2", None), ("+150", None), ("-200", None), ("0.50", "hk")):
        print(f"  {v:<7} -> decimal {parse(v, fmt=f):.3f}")

    print("\n=== 6. RACING FORM SCAN (sample_form.csv) ===")
    runners = form_mod.load_form(SAMPLE_FORM)
    probs, picks = form_mod.race_scan(
        runners,
        [("Mighty Mo", 6.00), ("Rocket Red", 6.50), ("Lucky Lass", 7.50), ("Fleetwood", 7.50)],
    )
    for r in sorted((x for x in runners if not x.scratched), key=lambda x: x.number):
        p = probs[r.name]
        print(f"  {r.number}. {r.name:<14} wgt {r.weight:.1f}  form {r.form_figures or '-':<7} "
              f"prob {p:.1%}  fair {value_mod.fair_odds(p):.2f}")
    for pick in picks[:2]:
        tag = "VALUE" if pick.is_value else "no edge"
        print(f"  -> {pick.selection}: market {pick.odds:.2f} vs fair {pick.prob_est:.1%} -> EV {pick.ev_per_unit:+.3f}/$ ({tag})")

    print("\n=== 7. BETFAIR EXCHANGE (fixture) + WATCH ===")
    for m in BetfairExchangeSource(fixture=SAMPLE_BETFAIR).fetch():
        print(f"  {m.market_id} {m.event}: " + "  ".join(
            f"{o.name} back {o.odds:.2f} / lay {o.lay:.2f}" for o in m.outcomes))
    alerts = watch_mod.scan_for_arbs(StaticSource(SAMPLE_MARKETS).fetch(), min_roi=0.0)
    if alerts:
        a = alerts[0]
        print(f"  watch: {len(alerts)} arb(s) found — {a.event}: lock ${a.profit:+.2f} on $100 "
              f"(ROI {a.roi_pct:+.2f}%)")
    else:
        print("  watch: no arbs found")

    tmp.cleanup()
    return 0


# ---------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ausbet", description="Australian betting toolkit")
    p.add_argument("--version", action="version", version=f"ausbet {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("convert", help="convert odds between formats")
    c.add_argument("odds")
    c.add_argument("--from", dest="from_fmt", choices=FORMATS, help="input format (auto-detected if omitted)")
    c.add_argument("--to", dest="to", choices=FORMATS, help="output format (default: all)")
    c.set_defaults(func=cmd_convert)

    b = sub.add_parser("bet", help="bet tracker CRUD")
    bsub = b.add_subparsers(dest="action", required=True)
    add = bsub.add_parser("add", help="record a bet")
    add.add_argument("--bookie", required=True)
    add.add_argument("--sport", required=True)
    add.add_argument("--selection", required=True)
    add.add_argument("--odds", required=True, help="any supported odds format")
    add.add_argument("--stake", type=float, required=True)
    add.add_argument("--competition", default="")
    add.add_argument("--market", default="")
    add.add_argument("--result", choices=("won", "lost", "void"))
    add.add_argument("--payout", type=float, help="actual return (defaults to odds*stake on win)")
    ls = bsub.add_parser("list", help="list bets")
    ls.add_argument("--pending", action="store_true")
    ls.add_argument("--limit", type=int, default=100)
    st = bsub.add_parser("settle", help="settle a bet")
    st.add_argument("bet_id", type=int)
    st.add_argument("--result", choices=("won", "lost", "void"), required=True)
    st.add_argument("--payout", type=float)
    rm = bsub.add_parser("rm", help="delete a bet")
    rm.add_argument("bet_id", type=int)
    ex = bsub.add_parser("export", help="export all bets to CSV")
    ex.add_argument("path")
    for subp in (add, ls, st, rm, ex):
        subp.add_argument("--db", default=DEFAULT_DB, help="sqlite db path")
    b.set_defaults(func=cmd_bet)

    s = sub.add_parser("stats", help="P&L statistics")
    s.add_argument("--db", default=DEFAULT_DB)
    s.add_argument("--bankroll", type=float, help="starting bankroll to add profit to")
    s.set_defaults(func=cmd_stats)

    v = sub.add_parser("value", help="EV / edge / fair odds / Kelly")
    v.add_argument("--odds", required=True)
    v.add_argument("--prob", type=float, required=True, help="your win probability (0..1)")
    v.add_argument("--bankroll", type=float)
    v.add_argument("--kelly-fraction", type=float, default=0.25)
    v.set_defaults(func=cmd_value)

    sc = sub.add_parser("scan", help="scan a market for value vs your probabilities")
    sc.add_argument("--odds", action="append", required=True, metavar="NAME:ODDS")
    sc.add_argument("--prob", action="append", required=True, metavar="NAME:PROB")
    sc.set_defaults(func=cmd_scan)

    a = sub.add_parser("arb", help="arbitrage check + stake split (2+ outcomes)")
    a.add_argument("odds", nargs="+", metavar="ODDS")
    a.add_argument("--stake", type=float, default=100.0)
    a.set_defaults(func=cmd_arb)

    d = sub.add_parser("dutch", help="equal-profit dutch stake split")
    d.add_argument("odds", nargs="+", metavar="ODDS")
    d.add_argument("--stake", type=float, default=100.0)
    d.set_defaults(func=cmd_dutch)

    h = sub.add_parser("hedge", help="equal-profit back/lay hedge")
    h.add_argument("--back-odds", type=float, required=True)
    h.add_argument("--back-stake", type=float, required=True)
    h.add_argument("--lay-odds", type=float, required=True)
    h.set_defaults(func=cmd_hedge)

    cp = sub.add_parser("compare", help="best odds + overround across bookmakers")
    cp.add_argument("--source", choices=("static", "oddsapi", "betfair"), default="static")
    cp.add_argument("--file", help="static JSON/CSV (default: bundled sample)")
    cp.add_argument("--cache", help="cache live odds to this file")
    cp.add_argument("--fixture", help="betfair offline fixture (catalogue+book JSON)")
    cp.add_argument("--event-type", default="61420", help="betfair event type id (61420=AFL, 1477=NRL, 7=horse)")
    cp.add_argument("--top", type=int, help="show only the N lowest-margin bookies")
    cp.add_argument("--arb", action="store_true", help="scan for arbitrages")
    cp.add_argument("--sport-keys", help="the-odds-api sport keys (default: AFL+NRL, e.g. aussierules_afl,rugbyleague_nrl)")
    cp.set_defaults(func=cmd_compare)

    r = sub.add_parser("race", help="racing form scan: probabilities + value picks")
    r.add_argument("--form", required=True, help="form CSV/JSON (see README schema)")
    r.add_argument("--odds", action="append", default=[], metavar="NAME:ODDS", help="repeatable market prices")
    r.set_defaults(func=cmd_race)

    ex = sub.add_parser("exchange", help="Betfair exchange: list markets / back-lay book")
    exsub = ex.add_subparsers(dest="action", required=True)
    exm = exsub.add_parser("markets", help="list fetched markets")
    exb = exsub.add_parser("book", help="back/lay table for one market")
    exb.add_argument("market_id")
    for subp in (exm, exb):
        subp.add_argument("--fixture", help="offline JSON fixture (catalogue+book)")
        subp.add_argument("--event-type", default="61420", help="betfair event type id")
    ex.set_defaults(func=cmd_exchange)

    w = sub.add_parser("watch", help="arb watcher: poll sources, alert on sub-100%% overrounds")
    w.add_argument("--source", choices=("static", "oddsapi", "betfair"), default="static")
    w.add_argument("--file", help="static JSON/CSV (default: bundled sample)")
    w.add_argument("--cache", help="oddsapi response cache")
    w.add_argument("--fixture", help="betfair offline fixture")
    w.add_argument("--event-type", default="61420")
    w.add_argument("--interval", type=float, default=300.0, help="seconds between cycles")
    w.add_argument("--cycles", type=int, default=0, help="0 = run forever")
    w.add_argument("--min-roi", type=float, default=0.0, help="only alert on arbs >= this ROI %%")
    w.add_argument("--stake", type=float, default=100.0)
    w.add_argument("--once", action="store_true", help="single check then exit (cron-friendly)")
    w.add_argument("--webhook", help="HTTP POST url for alerts")
    w.add_argument("--quiet", action="store_true", help="suppress no-arb cycle messages")
    w.set_defaults(func=cmd_watch)

    hh = sub.add_parser("h2h", help="bookie-vs-bookie price scan (default: Neds vs Sportsbet)")
    hh.add_argument("--source", choices=("static", "oddsapi", "betfair"), default="static")
    hh.add_argument("--file", help="static JSON/CSV (default: bundled sample)")
    hh.add_argument("--cache", help="oddsapi response cache")
    hh.add_argument("--fixture", help="betfair offline fixture")
    hh.add_argument("--event-type", default="61420")
    hh.add_argument("--bookies", default="neds,sportsbet", help="comma-separated bookie names")
    hh.add_argument("--sport", help="filter by sport (e.g. AFL, NRL)")
    hh.add_argument("--min-gap", type=float, help="only show gaps >= this %%")
    hh.add_argument("--top", type=int, help="show only the N biggest gaps")
    hh.add_argument("--sport-keys", help="the-odds-api sport keys (default: AFL+NRL, e.g. aussierules_afl,rugbyleague_nrl)")
    hh.set_defaults(func=cmd_h2h)

    ml = sub.add_parser("multi", help="multi / racing-special fairness vs placing the singles")
    ml.add_argument("--leg", action="append", required=True, metavar="NAME:ODDS",
                    help="repeatable: best single price for each leg")
    ml.add_argument("--offer", type=float, help="the bookie's multi price")
    ml.add_argument("--stake", type=float, default=10.0)
    ml.add_argument("--prob", action="append", metavar="NAME:PROB",
                    help="repeatable: your win probability per leg")
    ml.set_defaults(func=cmd_multi)

    rs = sub.add_parser("results", help="auto-settle pending h2h bets from final scores")
    rs.add_argument("--auto", action="store_true",
                    help="fetch live scores from the-odds-api (needs ODDS_API_KEY)")
    rs.add_argument("--file", help="results JSON [{home, away, home_score, away_score, sport}]")
    rs.add_argument("--days", type=int, default=2, help="days of scores to fetch (--auto)")
    rs.add_argument("--cache", help="oddsapi response cache")
    rs.add_argument("--sport-keys", help="the-odds-api sport keys (default: all AU football codes)")
    rs.add_argument("--db", default=DEFAULT_DB)
    rs.set_defaults(func=cmd_results)

    dm = sub.add_parser("demo", help="offline end-to-end walkthrough")
    dm.set_defaults(func=cmd_demo)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
