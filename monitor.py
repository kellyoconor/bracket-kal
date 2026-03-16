#!/usr/bin/env python3
"""
Monitor your bracket picks against live Kalshi odds.

- Polls Kalshi every 10 min for odds movement on your picked teams
- Telegrams when a picked team drops >5% or a game resolves
- Tracks running score: Claude picks vs Kalshi picks
- Answers your questions via Telegram using Claude + bracket context
- Single command: python monitor.py
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
PICKS_FILE = ROOT / "bracket_picks.json"
RESULTS_FILE = ROOT / "results.json"
KALSHI_FILE = ROOT / "kalshi_markets.json"
SCORE_FILE = ROOT / "monitor_score.json"
POLL_INTERVAL = 600  # 10 minutes

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")


# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def telegram_send(message: str):
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


def telegram_get_updates(last_update_id: int) -> tuple[list[dict], int]:
    """Fetch new Telegram messages since last_update_id."""
    if not TELEGRAM_TOKEN:
        return [], last_update_id
    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        f"?offset={last_update_id + 1}&limit=10&timeout=0"
    )
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        updates = data.get("result", [])
        messages = []
        new_id = last_update_id
        for u in updates:
            uid = u.get("update_id", 0)
            if uid > new_id:
                new_id = uid
            msg = u.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "").strip()
            if chat_id == str(TELEGRAM_CHAT_ID) and text:
                messages.append(text)
        return messages, new_id
    except Exception:
        return [], last_update_id


# ─── CLAUDE Q&A ──────────────────────────────────────────────────────────────

def build_bracket_context(picks: list[dict], score: dict,
                          game_odds: dict) -> str:
    """Build a context string from current bracket state for Claude."""
    lines = []
    lines.append(f"BRACKET SCORE: {score['correct']}W / {score['busted']}L")
    lines.append(f"Claude picks: {score['diverge_correct']}W/{score['diverge_busted']}L")
    lines.append(f"Kalshi picks: {score['kalshi_correct']}W/{score['kalshi_busted']}L")
    lines.append(f"Resolved: {len(score.get('resolved_games', []))} games")
    lines.append("")

    # Current round picks with live odds
    for p in picks:
        game_id = p["game"]
        team = p["picked_team"]
        source = p.get("pick_source", "?")
        ens = p.get("ensemble_prob")
        kal = p.get("kalshi_prob")
        div = p.get("divergence")
        resolved = game_id in score.get("resolved_games", [])

        abbrev = ABBREV_MAP.get(team, "")
        live = game_odds.get(abbrev, {})
        live_prob = live.get("prob")
        status = live.get("status", "")

        status_str = "RESOLVED" if resolved else status
        live_str = f" live:{live_prob:.0%}" if live_prob else ""
        ens_str = f" ens:{ens:.0%}" if ens else ""
        kal_str = f" kal:{kal:.0%}" if kal else ""
        div_str = f" div:{div:.0%}" if div else ""

        lines.append(
            f"Game {game_id} [{p.get('round','')}] {p['matchup']} "
            f"-> {team} [{source}]{ens_str}{kal_str}{div_str}{live_str} ({status_str})"
        )

    return "\n".join(lines)


def answer_question(question: str, picks: list[dict], score: dict,
                    game_odds: dict) -> str:
    """Use Claude to answer a question about the bracket."""
    if not ANTHROPIC_API_KEY:
        return "Can't answer questions — ANTHROPIC_API_KEY not set."

    import anthropic
    client = anthropic.Anthropic()

    context = build_bracket_context(picks, score, game_odds)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": f"""You are a March Madness bracket assistant. Answer the user's question using the bracket data below. Be concise and conversational — this is a Telegram message, keep it short. No markdown formatting (Telegram basic formatting only).

BRACKET DATA:
{context}

USER QUESTION: {question}"""}],
    )

    return response.content[0].text.strip()


# ─── KALSHI ──────────────────────────────────────────────────────────────────

def kalshi_get(endpoint: str, params: dict | None = None) -> dict:
    url = f"{KALSHI_BASE}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


TOURNAMENT_DATES = [
    "MAR17", "MAR18", "MAR19", "MAR20", "MAR21", "MAR22",
    "MAR23", "MAR24", "MAR27", "MAR28", "MAR29", "MAR30",
    "APR05", "APR07",
]


def is_tournament_game(ticker: str) -> bool:
    return any(date in ticker for date in TOURNAMENT_DATES)


def pull_game_odds() -> dict[str, dict]:
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


# ─── DATA ────────────────────────────────────────────────────────────────────

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


def load_picks() -> list[dict]:
    with open(PICKS_FILE) as f:
        return json.load(f)["picks"]


FRESH_SCORE = {
    "correct": 0, "busted": 0, "pending": 0,
    "diverge_correct": 0, "diverge_busted": 0,
    "kalshi_correct": 0, "kalshi_busted": 0,
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


# ─── MAIN LOOP ───────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bracket Monitor")
    parser.add_argument("--reset", action="store_true", help="Reset score and start fresh")
    args = parser.parse_args()

    print("=" * 70)
    print("Bracket Monitor — Live Odds + Telegram Q&A")
    print("=" * 70)

    if not TELEGRAM_TOKEN:
        print("\n  Warning: TELEGRAM_BOT_TOKEN not set.")
    if not TELEGRAM_CHAT_ID:
        print("  Warning: TELEGRAM_CHAT_ID not set.")

    picks = load_picks()
    score = load_score(reset=args.reset)
    if args.reset:
        save_score(score)
        print("\n  Score reset to 0-0.")
    print(f"\n  Loaded {len(picks)} picks from {PICKS_FILE}")
    print(f"  Score: {score['correct']}W / {score['busted']}L")
    print(f"  Polling every {POLL_INTERVAL // 60} minutes")
    print(f"  Q&A enabled: {'yes' if ANTHROPIC_API_KEY else 'no (set ANTHROPIC_API_KEY)'}\n")

    prev_odds: dict[str, float] = {}
    last_update_id = 0

    # Get current update_id so we don't process old messages
    _, last_update_id = telegram_get_updates(0)
    # Bump to skip any existing messages
    if last_update_id > 0:
        _, last_update_id = telegram_get_updates(last_update_id)

    diverge_count = sum(1 for p in picks if p.get("pick_source") == "DIVERGE")
    kalshi_count = len(picks) - diverge_count

    telegram_send(
        f"Bracket monitor is live.\n\n"
        f"Tracking {len(picks)} picks — {diverge_count} Claude, {kalshi_count} Kalshi.\n"
        f"I'll message you when odds move or games finish.\n\n"
        f"Ask me anything — \"how's my bracket?\", \"which games are closest?\", "
        f"\"what's the score?\""
    )

    while True:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%H:%M:%S UTC")
        print(f"\n[{ts}] Polling...")

        game_odds = pull_game_odds()
        print(f"  Loaded {len(game_odds)} team prices")

        # ─── Check for incoming questions ────────────────────────────
        messages, last_update_id = telegram_get_updates(last_update_id)
        for msg_text in messages:
            upper = msg_text.upper().strip()

            # Skip the STOP command (that's for the trader)
            if upper == "STOP":
                continue

            print(f"  [Q&A] Question: {msg_text}")
            try:
                answer = answer_question(msg_text, picks, score, game_odds)
                telegram_send(answer)
                print(f"  [Q&A] Answered.")
            except Exception as e:
                telegram_send(f"Sorry, couldn't process that: {e}")
                print(f"  [Q&A] Error: {e}")

        # ─── Check picks against live odds ───────────────────────────
        for pick in picks:
            team = pick["picked_team"]
            abbrev = ABBREV_MAP.get(team)
            if not abbrev:
                continue

            game_id = pick["game"]
            matchup = pick["matchup"]
            source = pick.get("pick_source", "?")

            if game_id in score.get("resolved_games", []):
                continue

            market = game_odds.get(abbrev)
            if not market:
                continue

            current_prob = market["prob"]
            status = market["status"]

            # ─── Game resolution ─────────────────────────────────────
            if status in ("closed", "determined", "finalized"):
                won = current_prob >= 0.90
                score["resolved_games"].append(game_id)
                if won:
                    score["correct"] += 1
                    if source == "DIVERGE":
                        score["diverge_correct"] += 1
                    else:
                        score["kalshi_correct"] += 1
                else:
                    score["busted"] += 1
                    if source == "DIVERGE":
                        score["diverge_busted"] += 1
                    else:
                        score["kalshi_busted"] += 1
                save_score(score)

                total_w = score["correct"]
                total_l = score["busted"]
                parts = matchup.split(" vs ")
                opponent = parts[1] if team in parts[0] else parts[0]

                if won:
                    if source == "DIVERGE":
                        msg = (
                            f"We nailed it. {team} wins.\n\n"
                            f"{matchup} ({pick.get('region', '')})\n\n"
                            f"This was a Claude pick — the market had them lower but "
                            f"Claude saw the edge. That's the whole point.\n\n"
                            f"Record: {total_w}-{total_l} "
                            f"({score['diverge_correct']}-{score['diverge_busted']} Claude, "
                            f"{score['kalshi_correct']}-{score['kalshi_busted']} Kalshi)"
                        )
                    else:
                        msg = (
                            f"{team} wins as expected.\n\n"
                            f"{matchup} ({pick.get('region', '')})\n\n"
                            f"Kalshi pick — market and Claude both liked them. "
                            f"No surprises here.\n\n"
                            f"Record: {total_w}-{total_l}"
                        )
                else:
                    if source == "DIVERGE":
                        div = pick.get("divergence")
                        div_str = f" (we saw a {div:.0%} gap)" if div else ""
                        msg = (
                            f"{team} is out. Claude pick missed{div_str}.\n\n"
                            f"{matchup} ({pick.get('region', '')})\n\n"
                            f"{opponent.strip()} advances. Claude liked {team} more than "
                            f"the market did, but the market was right on this one.\n\n"
                            f"Record: {total_w}-{total_l} "
                            f"({score['diverge_correct']}-{score['diverge_busted']} Claude, "
                            f"{score['kalshi_correct']}-{score['kalshi_busted']} Kalshi)"
                        )
                    else:
                        msg = (
                            f"Upset. {team} is out.\n\n"
                            f"{matchup} ({pick.get('region', '')})\n\n"
                            f"{opponent.strip()} pulls the upset. This was a Kalshi pick — "
                            f"both the market and Claude had {team}. "
                            f"Sometimes the madness wins.\n\n"
                            f"Record: {total_w}-{total_l}"
                        )

                print(f"  {'W' if won else 'L'} Game {game_id}: {team}")
                telegram_send(msg)
                continue

            # ─── Odds movement ───────────────────────────────────────
            prev = prev_odds.get(f"{game_id}:{abbrev}")
            if prev is not None:
                drop = prev - current_prob
                if drop >= 0.05:
                    pct_now = f"{current_prob:.0%}"
                    pct_was = f"{prev:.0%}"

                    if source == "DIVERGE":
                        msg = (
                            f"Heads up — {team} is sliding.\n\n"
                            f"{matchup}\n"
                            f"Was {pct_was}, now {pct_now}.\n\n"
                            f"This is a Claude pick — we overrode the market. It's moving "
                            f"against us. Could be injury news, could be sharp money. "
                            f"Worth watching."
                        )
                    else:
                        msg = (
                            f"{team} odds are dropping.\n\n"
                            f"{matchup}\n"
                            f"Was {pct_was}, now {pct_now}.\n\n"
                            f"Kalshi pick — the market is softening on them."
                        )

                    print(f"  Drop: {team} {pct_was} -> {pct_now}")
                    telegram_send(msg)

            prev_odds[f"{game_id}:{abbrev}"] = current_prob
            print(f"  Game {game_id:>2}: {team:<20} {current_prob:>5.0%}  [{source}]  ({status})")

        # Score summary
        total = score["correct"] + score["busted"]
        pct = f"{score['correct']/total:.0%}" if total > 0 else "n/a"
        print(f"\n  Running score: {score['correct']}W / {score['busted']}L ({pct})")
        print(f"  Claude: {score['diverge_correct']}W/{score['diverge_busted']}L | "
              f"Kalshi: {score['kalshi_correct']}W/{score['kalshi_busted']}L")
        print(f"  Next poll in {POLL_INTERVAL // 60} min...")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
