#!/usr/bin/env python3
"""
Monitor your bracket picks against live Kalshi odds.

- Polls Kalshi every 10 min for odds movement on your picked teams
- Telegrams BelowTheFloorBot when a picked team drops >5%
- After each game resolves, Telegrams: pick correct or busted
- Tracks running score: divergence picks hitting vs chalk
- Single command: python monitor.py
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
PICKS_FILE = ROOT / "bracket_picks.json"
KALSHI_FILE = ROOT / "kalshi_markets.json"
SCORE_FILE = ROOT / "monitor_score.json"
POLL_INTERVAL = 600  # 10 minutes

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def kalshi_get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{KALSHI_BASE}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def telegram_send(message: str):
    """Send a message via Telegram bot."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"  [TG] (not configured) {message}")
        return
    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        f"?chat_id={TELEGRAM_CHAT_ID}"
        f"&text={quote(message)}"
        f"&parse_mode=Markdown"
    )
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            resp.read()
        print(f"  [TG] Sent: {message[:80]}...")
    except Exception as e:
        print(f"  [TG] Failed: {e}")


def load_picks() -> list[dict]:
    with open(PICKS_FILE) as f:
        data = json.load(f)
    return data["picks"]


FRESH_SCORE = {
    "correct": 0, "busted": 0, "pending": 0,
    "diverge_correct": 0, "diverge_busted": 0,
    "chalk_correct": 0, "chalk_busted": 0,
    "resolved_games": [],
}


def load_score(reset: bool = False) -> dict:
    if reset or not SCORE_FILE.exists():
        return {**FRESH_SCORE}
    with open(SCORE_FILE) as f:
        return json.load(f)


def save_score(score: dict):
    with open(SCORE_FILE, "w") as f:
        json.dump(score, f, indent=2)


# Tournament game dates (first round through championship)
# Update these as the tournament progresses
TOURNAMENT_DATES = [
    "MAR17", "MAR18",  # First Four
    "MAR19", "MAR20",  # Round of 64, Day 1-2
    "MAR21", "MAR22",  # Round of 64, Day 3-4
    "MAR23", "MAR24",  # Round of 32
    "MAR27", "MAR28",  # Sweet 16
    "MAR29", "MAR30",  # Elite 8
    "APR05",            # Final Four
    "APR07",            # Championship
]


def is_tournament_game(ticker: str) -> bool:
    """Check if a market ticker is for a tournament game (not regular season)."""
    return any(date in ticker for date in TOURNAMENT_DATES)


def pull_game_odds() -> dict[str, dict]:
    """Pull tournament KXNCAAMBGAME markets, return {abbrev: {prob, status, ticker}}.

    Only includes tournament-dated games to avoid collisions with
    regular season markets that share the same team abbreviations.
    """
    odds = {}
    try:
        cursor = None
        while True:
            params = {"series_ticker": "KXNCAAMBGAME", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = kalshi_get("/markets", params)
            markets = data.get("markets", [])
            for m in markets:
                ticker = m.get("ticker", "")

                # Skip non-tournament games
                if not is_tournament_game(ticker):
                    continue

                abbrev = ticker.rsplit("-", 1)[-1] if "-" in ticker else ""
                status = m.get("status", "")
                yb = float(m.get("yes_bid_dollars", "0") or "0")
                ya = float(m.get("yes_ask_dollars", "0") or "0")
                lp = float(m.get("last_price_dollars", "0") or "0")
                if yb > 0 and ya > 0:
                    prob = (yb + ya) / 2
                elif lp > 0:
                    prob = lp
                else:
                    prob = None

                if prob is not None:
                    existing = odds.get(abbrev)
                    # Prefer active/open games over finalized ones
                    if not existing or status in ("active", "open"):
                        odds[abbrev] = {
                            "prob": prob, "status": status,
                            "ticker": ticker, "event": m.get("event_ticker", ""),
                        }
            cursor = data.get("cursor")
            if not cursor or not markets:
                break
    except Exception as e:
        print(f"  Error pulling odds: {e}")
    return odds


# Map team names to Kalshi abbreviations (reuse from bracket_divergence.py)
ABBREV_MAP = {
    "Duke": "DUKE", "Siena": "SIE", "Ohio State": "OSU", "TCU": "TCU",
    "St. John's": "SJU", "Northern Iowa": "UNI", "Kansas": "KU",
    "Cal Baptist": "CBU", "Louisville": "LOU", "South Florida": "USF",
    "Michigan State": "MSU", "North Dakota State": "NDSU", "UCLA": "UCLA",
    "UCF": "UCF", "UConn": "CONN", "Furman": "FUR",
    "Arizona": "ARIZ", "LIU": "LIU", "Villanova": "VILL",
    "Utah State": "USU", "Wisconsin": "WIS", "High Point": "HP",
    "Arkansas": "ARK", "Hawaii": "HAW", "BYU": "BYU", "Texas": "TEX",
    "Gonzaga": "GONZ", "Kennesaw State": "KENN", "Miami (FL)": "MIA",
    "Missouri": "MIZZ", "Purdue": "PUR", "Queens": "QUC",
    "Florida": "FLA", "Prairie View A&M": "PV",
    "Clemson": "CLEM", "Iowa": "IOWA", "Vanderbilt": "VAN",
    "McNeese": "MCNS", "Nebraska": "NEB", "Troy": "TROY",
    "North Carolina": "UNC", "VCU": "VCU", "Illinois": "ILL",
    "Penn": "PENN", "Saint Mary's": "SMC", "Texas A&M": "TXAM",
    "Houston": "HOU", "Idaho": "IDHO",
    "Michigan": "MICH", "UMBC": "UMBC", "Georgia": "UGA",
    "Saint Louis": "SLU", "Texas Tech": "TTU", "Akron": "AKR",
    "Alabama": "ALA", "Hofstra": "HOF", "Tennessee": "TENN",
    "SMU": "SMU", "Virginia": "UVA", "Wright State": "WRST",
    "Kentucky": "UK", "Santa Clara": "SCU", "Iowa State": "ISU",
    "Tennessee State": "TNST",
}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bracket Monitor")
    parser.add_argument("--reset", action="store_true", help="Reset score and start fresh")
    args = parser.parse_args()

    print("=" * 70)
    print("Bracket Monitor — Live Odds Tracking + Telegram Alerts")
    print("=" * 70)

    if not TELEGRAM_TOKEN:
        print("\n  Warning: TELEGRAM_BOT_TOKEN not set. Alerts will print to console only.")
    if not TELEGRAM_CHAT_ID:
        print("  Warning: TELEGRAM_CHAT_ID not set.")

    picks = load_picks()
    score = load_score(reset=args.reset)
    if args.reset:
        save_score(score)
        print("\n  Score reset to 0-0.")
    print(f"\n  Loaded {len(picks)} picks from {PICKS_FILE}")
    print(f"  Score: {score['correct']}W / {score['busted']}L / {score['pending']} pending")
    print(f"  Polling every {POLL_INTERVAL // 60} minutes\n")

    # Track previous odds for movement detection
    prev_odds: dict[str, float] = {}

    telegram_send(
        f"*Bracket Monitor started*\n"
        f"Tracking {len(picks)} picks\n"
        f"Score: {score['correct']}W / {score['busted']}L"
    )

    while True:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%H:%M:%S UTC")
        print(f"\n[{ts}] Polling Kalshi...")

        game_odds = pull_game_odds()
        print(f"  Loaded {len(game_odds)} team prices")

        for pick in picks:
            team = pick["picked_team"]
            abbrev = ABBREV_MAP.get(team)
            if not abbrev:
                continue

            game_id = pick["game"]
            matchup = pick["matchup"]
            source = pick.get("pick_source", "?")

            # Skip already resolved
            if game_id in score.get("resolved_games", []):
                continue

            market = game_odds.get(abbrev)
            if not market:
                continue

            current_prob = market["prob"]
            status = market["status"]

            # --- Check for game resolution ---
            if status in ("closed", "determined", "finalized"):
                won = current_prob >= 0.90  # Settled at ~$1.00 = won
                result = "CORRECT" if won else "BUSTED"

                score["resolved_games"].append(game_id)
                if won:
                    score["correct"] += 1
                    if source == "DIVERGE":
                        score["diverge_correct"] += 1
                    else:
                        score["chalk_correct"] += 1
                else:
                    score["busted"] += 1
                    if source == "DIVERGE":
                        score["diverge_busted"] += 1
                    else:
                        score["chalk_busted"] += 1
                save_score(score)

                emoji = "✅" if won else "❌"
                msg = (
                    f"{emoji} *Game {game_id} {result}*\n"
                    f"{matchup}\n"
                    f"Pick: {team} [{source}]\n"
                    f"Score: {score['correct']}W / {score['busted']}L\n"
                    f"Diverge: {score['diverge_correct']}W/{score['diverge_busted']}L | "
                    f"Chalk: {score['chalk_correct']}W/{score['chalk_busted']}L"
                )
                print(f"  {emoji} Game {game_id}: {team} {result}")
                telegram_send(msg)
                continue

            # --- Check for odds movement ---
            prev = prev_odds.get(f"{game_id}:{abbrev}")
            if prev is not None:
                drop = prev - current_prob
                if drop >= 0.05:  # Dropped >5%
                    msg = (
                        f"⚠️ *ODDS DROP: {team}*\n"
                        f"{matchup}\n"
                        f"Was: {prev:.0%} -> Now: {current_prob:.0%} ({drop:+.0%})\n"
                        f"Pick source: [{source}]"
                    )
                    print(f"  ⚠️  {team} dropped {drop:.0%} ({prev:.0%} -> {current_prob:.0%})")
                    telegram_send(msg)

            prev_odds[f"{game_id}:{abbrev}"] = current_prob

            # Log current state
            print(f"  Game {game_id:>2}: {team:<20} {current_prob:>5.0%}  [{source}]  ({status})")

        # Score summary
        total = score["correct"] + score["busted"]
        pct = f"{score['correct']/total:.0%}" if total > 0 else "n/a"
        print(f"\n  Running score: {score['correct']}W / {score['busted']}L ({pct})")
        print(f"  Diverge: {score['diverge_correct']}W/{score['diverge_busted']}L | "
              f"Chalk: {score['chalk_correct']}W/{score['chalk_busted']}L")
        print(f"  Next poll in {POLL_INTERVAL // 60} min...")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
