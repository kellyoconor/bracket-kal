#!/usr/bin/env python3
"""
Pull ALL NCAA Tournament odds from Kalshi's public API.
No API key required for market data.

Series discovered:
  KXMARMAD          Championship winner — "Will Duke win it all?"
  KXNCAAMBGAME      Per-game winner — "Duke at Siena Winner?" (LIVE H2H odds)
  KXMARMADSEEDWIN   Seed upset props — "Will a #16 seed win in R64?"
  KXMARMADSEED      Seed advancement — "Will a #1 seed win the championship?"
  KXMARMADUPSET     Upset totals — "At least 7 upsets in R64?"
  KXMARMADPTS       Player points — "Will any player score 40+?"
  KXMARMAD1SEED     1-seed props
  KXMARMADCONF      Conference props

Priority for game-level picks:
  1. KXNCAAMBGAME (direct H2H winner contracts) — best signal
  2. KXMARMAD (championship odds, derived into H2H) — fallback
"""

import json
import re
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
ROOT = Path(__file__).parent
OUTPUT_FILE = ROOT / "kalshi_markets.json"

# All known March Madness series
ALL_SERIES = {
    "KXMARMAD":         "Championship Winner",
    "KXNCAAMBGAME":     "Per-Game Winner",
    "KXMARMADSEEDWIN":  "Seed Upset Props",
    "KXMARMADSEED":     "Seed Advancement",
    "KXMARMADUPSET":    "Upset Totals",
    "KXMARMADPTS":      "Player Points Props",
    "KXMARMAD1SEED":    "1-Seed Props",
    "KXMARMADCONF":     "Conference Props",
}


def kalshi_get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_market_price(m: dict) -> float | None:
    yb = float(m.get("yes_bid_dollars", m.get("yes_bid", "0")) or "0")
    ya = float(m.get("yes_ask_dollars", m.get("yes_ask", "0")) or "0")
    lp = float(m.get("last_price_dollars", m.get("last_price", "0")) or "0")
    if yb > 0 and ya > 0:
        return (yb + ya) / 2
    if lp > 0:
        return lp
    return None


def paginate_markets(series: str, status: str = "open") -> list[dict]:
    """Paginate through all markets in a series."""
    all_markets = []
    cursor = None
    while True:
        params = {"series_ticker": series, "limit": 200}
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        data = kalshi_get("/markets", params)
        batch = data.get("markets", [])
        all_markets.extend(batch)
        cursor = data.get("cursor")
        if not cursor or not batch:
            break
    return all_markets


def pull_all_series() -> dict:
    """Pull every market from every NCAA tournament series."""
    results = {}
    for series, label in ALL_SERIES.items():
        print(f"  {label:<25} ({series})...", end=" ", flush=True)
        try:
            # Pull with status=open first; if that fails, pull without status filter
            try:
                all_mkts = paginate_markets(series, "open")
            except Exception:
                all_mkts = []
            # Also pull without status filter to catch active/other states, dedup
            try:
                no_filter = paginate_markets(series, "")
                seen = {m.get("ticker"): m for m in all_mkts}
                for m in no_filter:
                    seen.setdefault(m.get("ticker"), m)
                all_mkts = list(seen.values())
            except Exception:
                pass

            results[series] = all_mkts
            if all_mkts:
                print(f"{len(all_mkts)} markets")
            else:
                print("none")
        except Exception as e:
            results[series] = []
            print(f"error: {e}")
        time.sleep(0.3)  # Rate limit courtesy
    return results


def parse_game_winners(markets: list[dict]) -> list[dict]:
    """Parse KXNCAAMBGAME markets into structured matchup data.

    Each event has 2 contracts (one per team). Group by event,
    extract team names and win probabilities.
    """
    by_event = {}
    for m in markets:
        evt = m.get("event_ticker", "")
        by_event.setdefault(evt, []).append(m)

    games = []
    for evt_ticker, mkts in sorted(by_event.items()):
        teams = []
        for m in mkts:
            price = get_market_price(m)
            ticker = m.get("ticker", "")
            title = m.get("title", "")
            abbrev = ticker.rsplit("-", 1)[-1] if "-" in ticker else ""
            # Extract team names from event title: "Siena at Duke"
            # or from market title: "George Washington at Utah Valley Winner?"
            yb = float(m.get("yes_bid_dollars", "0") or "0")
            ya = float(m.get("yes_ask_dollars", "0") or "0")
            teams.append({
                "abbrev": abbrev,
                "ticker": ticker,
                "win_prob": round(price, 4) if price is not None else None,
                "yes_bid": yb,
                "yes_ask": ya,
            })

        # Sort favorite first
        teams.sort(key=lambda t: t["win_prob"] or 0, reverse=True)

        # Extract matchup name from event title
        evt_data = mkts[0]
        status = evt_data.get("status", "")

        games.append({
            "event_ticker": evt_ticker,
            "status": status,
            "teams": teams,
        })

    return games


def parse_championship(markets: list[dict]) -> list[dict]:
    teams = []
    for m in markets:
        price = get_market_price(m)
        if price is None:
            continue
        title = m.get("title", "")
        team = title.replace("Will ", "").replace(
            " win the College Basketball National Championship?", ""
        ).strip()
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        teams.append({"team": team, "prob": round(price, 4), "bid": yb, "ask": ya})
    return sorted(teams, key=lambda t: t["prob"], reverse=True)


def parse_props(markets: list[dict], series: str) -> list[dict]:
    """Generic parser for prop/futures markets."""
    props = []
    for m in markets:
        price = get_market_price(m)
        title = m.get("title", "")
        ticker = m.get("ticker", "")
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        props.append({
            "ticker": ticker,
            "title": title,
            "prob": round(price, 4) if price is not None else None,
            "bid": yb,
            "ask": ya,
        })
    return sorted(props, key=lambda p: p["prob"] or 0, reverse=True)


def main():
    print("=" * 90)
    print("Kalshi NCAA Tournament — Full Market Pull")
    print("=" * 90)
    print()

    raw = pull_all_series()

    # --- Save raw data ---
    # Backward-compatible: championship under "KXMARMAD" key
    with open(OUTPUT_FILE, "w") as f:
        json.dump(raw, f, indent=2, default=str)
    total = sum(len(v) for v in raw.values())
    print(f"\n  Saved {total} total markets to {OUTPUT_FILE}")

    # === CHAMPIONSHIP ===
    champ = parse_championship(raw.get("KXMARMAD", []))
    print(f"\n{'=' * 90}")
    print(f"CHAMPIONSHIP WINNER ({len(champ)} teams)")
    print(f"{'=' * 90}")
    print(f"  {'Team':<25} {'Prob':>7} {'Bid':>7} {'Ask':>7}")
    print(f"  {'-' * 50}")
    for t in champ[:25]:
        print(f"  {t['team']:<25} {t['prob']:>6.1%} {t['bid']:>6.1%} {t['ask']:>6.1%}")

    # === PER-GAME WINNERS ===
    game_mkts = raw.get("KXNCAAMBGAME", [])
    games = parse_game_winners(game_mkts)
    # Filter to active/open tournament games (not finalized regular season)
    live_games = [g for g in games if g["status"] in ("active", "open")]
    print(f"\n{'=' * 90}")
    print(f"PER-GAME WINNER MARKETS ({len(live_games)} live games)")
    print(f"{'=' * 90}")
    for g in live_games:
        teams = g["teams"]
        if len(teams) >= 2:
            t1, t2 = teams[0], teams[1]
            print(f"  {g['event_ticker']:<55} {t1['abbrev']:<6} {t1['win_prob'] or 0:>5.0%}  vs  {t2['abbrev']:<6} {t2['win_prob'] or 0:>5.0%}")

    # === PROPS / FUTURES ===
    prop_series = [
        ("KXMARMADSEEDWIN", "SEED UPSET PROPS"),
        ("KXMARMADSEED", "SEED ADVANCEMENT FUTURES"),
        ("KXMARMADUPSET", "UPSET TOTAL PROPS"),
        ("KXMARMADPTS", "PLAYER POINTS PROPS"),
        ("KXMARMAD1SEED", "1-SEED PROPS"),
        ("KXMARMADCONF", "CONFERENCE PROPS"),
    ]
    for series, label in prop_series:
        mkts = raw.get(series, [])
        if not mkts:
            continue
        props = parse_props(mkts, series)
        print(f"\n{'=' * 90}")
        print(f"{label} ({len(props)} markets)")
        print(f"{'=' * 90}")
        for p in props[:15]:
            prob_str = f"{p['prob']:.0%}" if p["prob"] is not None else "n/a"
            print(f"  {prob_str:>5}  {p['title']}")
        if len(props) > 15:
            print(f"  ... and {len(props) - 15} more")

    # === SUMMARY ===
    print(f"\n{'=' * 90}")
    print("SUMMARY")
    print(f"{'=' * 90}")
    for series, label in ALL_SERIES.items():
        count = len(raw.get(series, []))
        status = "LIVE" if count > 0 else "---"
        print(f"  {label:<25} {series:<20} {count:>4} markets  [{status}]")
    print(f"  {'─' * 55}")
    print(f"  {'TOTAL':<45} {total:>4} markets")
    print()


if __name__ == "__main__":
    main()
