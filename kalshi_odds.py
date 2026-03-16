#!/usr/bin/env python3
"""
Pull NCAA Tournament odds from Kalshi's public API.
No API key required for market data.
"""

import json
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
OUTPUT_FILE = Path(__file__).parent / "kalshi_markets.json"


def kalshi_get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req) as resp:
        return json.loads(resp.read())


def discover_ncaa_markets():
    """Search for all NCAA/March Madness related markets."""
    print("Searching for NCAA Tournament markets on Kalshi...\n")

    results = {}

    # 1. Check the known championship series
    for series in ["KXMARMAD", "KXNCAAM", "KXNCAA", "KXCBB"]:
        try:
            data = kalshi_get("/markets", {
                "series_ticker": series,
                "status": "open",
                "limit": 200,
            })
            markets = data.get("markets", [])
            if markets:
                results[series] = markets
                print(f"  Found {len(markets)} markets in series {series}")
        except Exception:
            pass

    # 2. Also try the event endpoint for 2026
    for event in ["KXMARMAD-26", "KXNCAAM-26", "KXMARMAD1SEED-26"]:
        try:
            data = kalshi_get(f"/events/{event}", {"with_nested_markets": "true"})
            markets = data.get("markets", [])
            if markets:
                results[event] = markets
                print(f"  Found {len(markets)} markets in event {event}")
        except Exception:
            pass

    # 3. Broad search for anything NCAA/basketball/march madness
    for term in ["ncaa", "march madness", "college basketball", "tournament"]:
        try:
            data = kalshi_get("/markets", {
                "status": "open",
                "limit": 100,
            })
            markets = data.get("markets", [])
            # Filter by title containing our search term
            matched = [m for m in markets if term.lower() in m.get("title", "").lower()]
            if matched:
                results[f"search:{term}"] = matched
                print(f"  Found {len(matched)} markets matching '{term}'")
        except Exception:
            pass

    return results


def extract_championship_odds(markets: list[dict]) -> list[dict]:
    """Extract team championship win probabilities from market data."""
    teams = []
    for m in markets:
        yes_bid = float(m.get("yes_bid", m.get("yes_bid_dollars", "0")) or "0")
        yes_ask = float(m.get("yes_ask", m.get("yes_ask_dollars", "0")) or "0")
        last_price = float(m.get("last_price", m.get("last_price_dollars", "0")) or "0")

        # Use midpoint of bid/ask if available, otherwise last trade
        if yes_bid > 0 and yes_ask > 0:
            implied_prob = (yes_bid + yes_ask) / 2
        elif last_price > 0:
            implied_prob = last_price
        else:
            continue

        teams.append({
            "ticker": m.get("ticker", ""),
            "title": m.get("title", ""),
            "implied_prob": round(implied_prob, 4),
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "last_price": last_price,
            "volume_24h": m.get("volume_24h", m.get("volume_24h_fp", "0")),
        })

    return sorted(teams, key=lambda t: t["implied_prob"], reverse=True)


def main():
    all_markets = discover_ncaa_markets()

    if not all_markets:
        print("\nNo NCAA markets found on Kalshi right now.")
        print("This could mean:")
        print("  - Markets haven't opened yet for the 2026 tournament")
        print("  - Different series tickers are being used")
        print("  - Markets are temporarily closed")
        print("\nFalling back to manual matchups.json — update it with current odds.")
        sys.exit(0)

    # Save raw data
    with open(OUTPUT_FILE, "w") as f:
        json.dump(all_markets, f, indent=2, default=str)
    print(f"\nRaw market data saved to {OUTPUT_FILE}")

    # Extract and display championship odds
    print("\n" + "=" * 70)
    print("NCAA CHAMPIONSHIP ODDS (from Kalshi)")
    print("=" * 70)

    for source, markets in all_markets.items():
        teams = extract_championship_odds(markets)
        if teams:
            print(f"\nSource: {source}")
            print(f"{'Team':<40} {'Prob':>8} {'Bid':>8} {'Ask':>8}")
            print("-" * 70)
            for t in teams[:30]:  # Top 30
                print(f"{t['title']:<40} {t['implied_prob']:>7.1%} {t['yes_bid']:>7.1%} {t['yes_ask']:>7.1%}")

    print("\nNote: Kalshi may only have championship winner markets,")
    print("not individual game matchups. For game-level odds, you may")
    print("need to update matchups.json manually from Kalshi's website.")
    print("Run: python bracket_divergence.py  to assess divergence.\n")


if __name__ == "__main__":
    main()
