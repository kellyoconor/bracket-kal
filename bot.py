#!/usr/bin/env python3
"""
Multi-user Bracket Divergence Telegram bot.

User journey:
  1. User sends /start → bot asks for ESPN bracket link or screenshot
  2. User pastes ESPN URL → bot pulls picks, shows analysis
  3. During games → bot sends live scores, odds movement, results
  4. User can ask questions anytime → bot answers with their bracket context

Data stored per user in users/{chat_id}/ directory.
"""

import json
import os
import time
import threading
import collections
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
USERS_DIR = ROOT / "users"
RESULTS_FILE = ROOT / "results.json"

# Public bot uses its own token — separate from BelowTheFloorBot (monitor)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN_PUBLIC", os.getenv("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID_ADMIN = os.getenv("TELEGRAM_CHAT_ID", "")  # Your admin chat for error alerts
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"

POLL_INTERVAL = 600
LIVE_POLL_INTERVAL = 30

# ─── RATE LIMITING ──────────────────────────────────────────────────────────

USER_RATE_LIMIT_PER_MIN = 10
USER_RATE_LIMIT_PER_HOUR = 50
GLOBAL_DAILY_BUDGET = 500

user_request_timestamps: dict[str, list[float]] = collections.defaultdict(list)
global_daily_requests: list[float] = []


def is_rate_limited(chat_id: str) -> str | None:
    """Check if a user or the global budget is rate-limited.
    Returns a message string if limited, None if OK."""
    now = time.time()

    # Global daily budget
    cutoff_day = now - 86400
    global_daily_requests[:] = [t for t in global_daily_requests if t > cutoff_day]
    if len(global_daily_requests) >= GLOBAL_DAILY_BUDGET:
        return "Bot is at capacity for today. Please try again tomorrow."

    # Per-user sliding window
    timestamps = user_request_timestamps[chat_id]
    cutoff_min = now - 60
    cutoff_hour = now - 3600
    timestamps[:] = [t for t in timestamps if t > cutoff_hour]

    recent_minute = sum(1 for t in timestamps if t > cutoff_min)
    if recent_minute >= USER_RATE_LIMIT_PER_MIN:
        return "Too many requests. Please wait a minute."

    if len(timestamps) >= USER_RATE_LIMIT_PER_HOUR:
        return "Too many requests this hour. Please slow down."

    # Record this request
    timestamps.append(now)
    global_daily_requests.append(now)
    return None


# ─── TELEGRAM ────────────────────────────────────────────────────────────────

def tg_send(chat_id: str, text: str):
    if not TELEGRAM_TOKEN:
        print(f"  [TG:{chat_id}] {text[:80]}...")
        return
    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        f"?chat_id={chat_id}"
        f"&text={quote(text)}"
    )
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as e:
        print(f"  [TG] Send failed: {e}")


def tg_get_updates(last_update_id: int) -> tuple[list[dict], int]:
    if not TELEGRAM_TOKEN:
        return [], last_update_id
    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
        f"?offset={last_update_id + 1}&limit=50&timeout=1"
    )
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        updates = data.get("result", [])
        new_id = last_update_id
        messages = []
        for u in updates:
            uid = u.get("update_id", 0)
            if uid > new_id:
                new_id = uid
            msg = u.get("message", {})
            chat_id = str(msg.get("chat", {}).get("id", ""))
            text = msg.get("text", "").strip()
            photo = msg.get("photo")
            first_name = msg.get("from", {}).get("first_name", "")
            if chat_id and (text or photo):
                messages.append({
                    "chat_id": chat_id,
                    "text": text,
                    "photo": photo,
                    "first_name": first_name,
                })
        return messages, new_id
    except Exception:
        return [], last_update_id


def tg_get_photo(file_id: str) -> bytes | None:
    """Download a photo from Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        file_path = data["result"]["file_path"]
        dl_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
        req = Request(dl_url)
        with urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception as e:
        print(f"  Photo download failed: {e}")
        return None


# ─── USER DATA ───────────────────────────────────────────────────────────────

def user_dir(chat_id: str) -> Path:
    sanitized = str(int(chat_id))  # Force numeric — rejects path traversal
    d = USERS_DIR / sanitized
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_user(chat_id: str) -> dict:
    path = user_dir(chat_id) / "user.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"chat_id": chat_id, "state": "new", "picks": [], "score": {
        "correct": 0, "busted": 0, "resolved_games": [],
        "diverge_correct": 0, "diverge_busted": 0,
        "kalshi_correct": 0, "kalshi_busted": 0,
    }}


def save_user(chat_id: str, data: dict):
    path = user_dir(chat_id) / "user.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_all_users() -> list[str]:
    if not USERS_DIR.exists():
        return []
    return [d.name for d in USERS_DIR.iterdir() if d.is_dir() and (d / "user.json").exists()]


# ─── ESPN BRACKET INTAKE ─────────────────────────────────────────────────────

def handle_espn_link(chat_id: str, text: str, user: dict) -> str:
    """Process an ESPN bracket URL and load picks."""
    from espn_scraper import fetch_and_parse

    result = fetch_and_parse(text)
    if not result:
        return (
            "Couldn't read that bracket. Make sure it's a valid ESPN "
            "Tournament Challenge link like:\n"
            "fantasy.espn.com/games/tournament-challenge-bracket-2026/bracket?id=..."
        )

    if result["total_picks"] == 0:
        return (
            f"Found your bracket ({result['name']} by {result['display_name']}) "
            f"but no picks yet. Fill out your bracket on ESPN first, then send "
            f"the link again."
        )

    # Store picks
    user["state"] = "active"
    user["bracket_name"] = result["name"]
    user["display_name"] = result["display_name"]
    user["espn_entry_id"] = result["entry_id"]
    user["champion"] = result["champion"]
    user["final_four"] = result["final_four"]
    user["picks"] = result["picks"]
    user["picks_by_round"] = result["picks_by_round"]
    user["total_picks"] = result["total_picks"]
    save_user(chat_id, user)

    # Build response
    champ = result["champion"] or "TBD"
    ff = ", ".join(result["final_four"]) if result["final_four"] else "TBD"
    total = result["total_picks"]

    return (
        f"Got it — '{result['name']}' by {result['display_name']}.\n\n"
        f"Loaded {total} picks.\n"
        f"Champion: {champ}\n"
        f"Final Four: {ff}\n\n"
        f"Give me a sec to run the divergence analysis against live Kalshi odds..."
    )


# ─── SCREENSHOT INTAKE ───────────────────────────────────────────────────────

def handle_screenshot(chat_id: str, photo_data: bytes, user: dict) -> str:
    """Process a bracket screenshot using Claude Vision."""
    if not ANTHROPIC_API_KEY:
        return "Screenshot analysis isn't available — ANTHROPIC_API_KEY not set."

    import anthropic
    import base64

    client = anthropic.Anthropic()
    b64 = base64.b64encode(photo_data).decode()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
                },
                {
                    "type": "text",
                    "text": """This is a March Madness bracket. Extract every pick visible.

Return ONLY valid JSON in this exact format:
{
  "champion": "Team Name",
  "final_four": ["Team1", "Team2", "Team3", "Team4"],
  "picks": [
    {"round": "R64", "team": "Team Name"},
    {"round": "R32", "team": "Team Name"},
    ...
  ]
}

Use standard team names (Duke, not Blue Devils). Include every pick you can read from the image.""",
                },
            ],
        }],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return "Couldn't read the bracket from that image. Try a clearer screenshot, or paste your ESPN bracket link instead."

    picks = parsed.get("picks", [])
    if not picks:
        return "I can see the bracket but couldn't extract specific picks. Try sending a closer screenshot of each region, or paste your ESPN bracket link."

    user["state"] = "active"
    user["bracket_name"] = "Screenshot bracket"
    user["champion"] = parsed.get("champion")
    user["final_four"] = parsed.get("final_four", [])
    user["picks"] = picks
    user["total_picks"] = len(picks)
    save_user(chat_id, user)

    champ = parsed.get("champion", "TBD")
    ff = ", ".join(parsed.get("final_four", [])) or "TBD"

    return (
        f"Read your bracket from the screenshot.\n\n"
        f"Loaded {len(picks)} picks.\n"
        f"Champion: {champ}\n"
        f"Final Four: {ff}\n\n"
        f"Give me a sec to run the divergence analysis against live Kalshi odds..."
    )


# ─── DIVERGENCE ANALYSIS ────────────────────────────────────────────────────

def run_analysis(chat_id: str, user: dict) -> str:
    """Run divergence analysis on user's picks vs ensemble results."""
    if not RESULTS_FILE.exists():
        return "No ensemble results available yet. Run bracket_divergence.py first."

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    # Build ensemble picks lookup: {game_num: result}
    ensemble_by_matchup = {}
    for round_key, games in results.items():
        for g in games:
            matchup = g.get("matchup", "")
            ensemble_by_matchup[matchup] = g

    user_picks = user.get("picks", [])
    if not user_picks:
        return "No picks loaded. Send me your ESPN bracket link."

    agreements = 0
    disagreements = []

    for pick in user_picks:
        team = pick.get("team", "")
        # Try to find this game in ensemble results
        for matchup, ens in ensemble_by_matchup.items():
            if team in matchup:
                ens_pick = ens.get("pick", "")
                if team == ens_pick:
                    agreements += 1
                else:
                    kalshi = ens.get("kalshi_prob")
                    ensemble = ens.get("ensemble_prob")
                    disagreements.append({
                        "matchup": matchup,
                        "your_pick": team,
                        "our_pick": ens_pick,
                        "kalshi_prob": kalshi,
                        "ensemble_prob": ensemble,
                        "divergence": ens.get("abs_divergence"),
                    })
                break

    # Save analysis
    user["analysis"] = {
        "agreements": agreements,
        "disagreements": disagreements,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    save_user(chat_id, user)

    if not disagreements:
        return (
            f"Interesting — your bracket matches our ensemble model on every "
            f"pick I could match. Either you're using the same signals we are, "
            f"or great minds think alike.\n\n"
            f"I'll track your picks live and message you during games."
        )

    # Show top disagreements
    lines = [
        f"Found {len(disagreements)} games where your picks differ from "
        f"our ensemble model.\n"
    ]

    # Sort by divergence
    sorted_dis = sorted(disagreements, key=lambda d: d.get("divergence") or 0, reverse=True)

    lines.append("Your boldest picks:\n")
    for d in sorted_dis[:5]:
        kal = d["kalshi_prob"]
        ens = d["ensemble_prob"]
        kal_str = f"{kal:.0%}" if kal else "?"
        ens_str = f"{ens:.0%}" if ens else "?"
        lines.append(
            f"  {d['matchup']}\n"
            f"  You: {d['your_pick']} | We: {d['our_pick']}\n"
            f"  Kalshi: {kal_str} | Ensemble: {ens_str}\n"
        )

    lines.append(
        f"\n{agreements} picks match, {len(disagreements)} differ.\n"
        f"I'll track all your picks live and message you during games."
    )

    return "\n".join(lines)


# ─── Q&A ─────────────────────────────────────────────────────────────────────

def answer_user_question(chat_id: str, question: str, user: dict) -> str:
    if not ANTHROPIC_API_KEY:
        return "Q&A isn't available — API key not configured."

    import anthropic
    client = anthropic.Anthropic()

    # Build context from user's bracket
    picks = user.get("picks", [])
    champ = user.get("champion", "?")
    ff = user.get("final_four", [])
    score = user.get("score", {})
    analysis = user.get("analysis", {})

    context_lines = [
        f"User: {user.get('display_name', user.get('chat_id', '?'))}",
        f"Bracket: {user.get('bracket_name', '?')}",
        f"Champion: {champ}",
        f"Final Four: {', '.join(ff) if ff else '?'}",
        f"Total picks: {user.get('total_picks', len(picks))}",
        f"Score: {score.get('correct', 0)}W / {score.get('busted', 0)}L",
        f"Agreements with ensemble: {analysis.get('agreements', '?')}",
        f"Disagreements: {len(analysis.get('disagreements', []))}",
    ]

    # Add pick details
    for p in picks[:40]:  # Limit context size
        context_lines.append(f"  {p.get('round', '?')}: {p.get('team', '?')}")

    context = "\n".join(context_lines)

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{
            "role": "user",
            "content": f"""You are a March Madness bracket assistant. Answer the user's question about their bracket. Be concise and conversational — this is a Telegram message. No markdown.

RULES:
1. Only cite facts from the BRACKET DATA below. Do not invent statistics.
2. If the user asks something not covered by the data, say "I don't have that information in the bracket data."
3. Do not cite win percentages, historical records, or KenPom numbers unless they appear in the data below.
4. Never suggest placing bets, trades, or wagers. This is for bracket pool entertainment only.
5. Keep answers concise and grounded in the provided data.

IMPORTANT: This is for entertainment and bracket pool analysis only. Never give financial advice.

BRACKET DATA:
{context}

QUESTION: {question}""",
        }],
    )

    return response.content[0].text.strip()


# ─── MESSAGE HANDLER ─────────────────────────────────────────────────────────

def handle_message(msg: dict):
    chat_id = msg["chat_id"]
    text = msg["text"]
    photo = msg["photo"]
    first_name = msg["first_name"]

    # Validate chat_id is numeric (Fix 4)
    try:
        str(int(chat_id))
    except (ValueError, TypeError):
        print(f"  Invalid chat_id: {chat_id!r}")
        return

    # Rate limit check (Fix 1) — skip for cheap commands
    is_expensive = text.lower() not in ("/start", "start", "hi", "hello", "hey", "/help", "help", "/score", "score")
    if is_expensive or photo:
        limited = is_rate_limited(chat_id)
        if limited:
            tg_send(chat_id, limited)
            return

    user = load_user(chat_id)

    # /start command
    if text.lower() in ("/start", "start", "hi", "hello", "hey"):
        user["first_name"] = first_name
        user["state"] = "awaiting_bracket"
        save_user(chat_id, user)
        tg_send(chat_id,
            f"Hey {first_name}! I'm your March Madness bracket assistant.\n\n"
            f"I'll analyze your picks against live prediction market odds "
            f"and our ensemble model (KenPom + Log5 + seed history + AI), "
            f"then track your bracket live during games.\n\n"
            f"Send me one of:\n"
            f"  1. Your ESPN bracket link\n"
            f"  2. A screenshot of your bracket\n\n"
            f"Or just tell me your Final Four and champion.\n\n"
            f"For entertainment and analysis only — not financial advice."
        )
        return

    # Photo = screenshot intake
    if photo:
        tg_send(chat_id, "Reading your bracket from the screenshot...")
        largest = max(photo, key=lambda p: p.get("width", 0) * p.get("height", 0))
        photo_data = tg_get_photo(largest["file_id"])
        if photo_data and len(photo_data) > 5 * 1024 * 1024:
            tg_send(chat_id, "Image too large. Please send a screenshot under 5MB.")
            return
        if photo_data:
            response = handle_screenshot(chat_id, photo_data, user)
            tg_send(chat_id, response)
            if user.get("state") == "active":
                analysis = run_analysis(chat_id, user)
                tg_send(chat_id, analysis)
        else:
            tg_send(chat_id, "Couldn't download that image. Try again?")
        return

    # ESPN link detection
    if "espn.com" in text.lower() or "fantasy.espn" in text.lower():
        tg_send(chat_id, "Pulling your bracket from ESPN...")
        response = handle_espn_link(chat_id, text, user)
        tg_send(chat_id, response)
        if user.get("state") == "active":
            analysis = run_analysis(chat_id, user)
            tg_send(chat_id, analysis)
        return

    # Quick start: user just names their champion/Final Four
    if user.get("state") == "awaiting_bracket":
        # Check if they're naming teams
        from bracket_divergence import BRACKET
        all_teams = set()
        for m in BRACKET:
            all_teams.add(m["higher_seed"]["team"].lower())
            all_teams.add(m["lower_seed"]["team"].lower())

        mentioned = [t for t in all_teams if t in text.lower()]
        if len(mentioned) >= 1:
            # They're telling us their picks verbally — use Claude to parse
            tg_send(chat_id, "Let me figure out your picks...")
            response = answer_user_question(chat_id,
                f"The user said: '{text}'. Extract any bracket picks they mentioned "
                f"(champion, Final Four, specific game picks). List what you understood.",
                user)
            tg_send(chat_id, response)
            tg_send(chat_id,
                "\nFor full tracking, send your ESPN bracket link — "
                "I can pull all 63 picks automatically.")
            return

    # /score command
    if text.lower() in ("/score", "score", "what's the score", "whats the score", "how am i doing"):
        score = user.get("score", {})
        total_w = score.get("correct", 0)
        total_l = score.get("busted", 0)
        if total_w + total_l == 0:
            tg_send(chat_id, "No games resolved yet. I'll message you as results come in.")
        else:
            tg_send(chat_id,
                f"Your bracket: {total_w}W / {total_l}L\n"
                f"Resolved: {len(score.get('resolved_games', []))} games")
        return

    # /help
    if text.lower() in ("/help", "help"):
        tg_send(chat_id,
            "Here's what I can do:\n\n"
            "Send me your ESPN bracket link to load your picks\n"
            "Send a screenshot of your bracket\n"
            "Ask me anything about your bracket\n\n"
            "Commands:\n"
            "  /score — your current record\n"
            "  /help — this message\n\n"
            "Or just ask naturally:\n"
            "  \"how's my bracket?\"\n"
            "  \"who do I have in the Final Four?\"\n"
            "  \"what's my riskiest pick?\"")
        return

    # General Q&A — user is asking a question
    if user.get("state") == "active" and user.get("picks"):
        response = answer_user_question(chat_id, text, user)
        tg_send(chat_id, response)
        return

    # Fallback
    if user.get("state") == "new":
        tg_send(chat_id,
            "Send me your ESPN bracket link to get started, or type /start.")
    else:
        tg_send(chat_id,
            "I don't have your bracket yet. Send me your ESPN bracket link "
            "or a screenshot of your bracket.")


# ─── MAIN LOOP ───────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("Bracket Divergence Bot — Multi-User")
    print("=" * 70)

    if not TELEGRAM_TOKEN:
        print("\n  ERROR: TELEGRAM_BOT_TOKEN not set.")
        return

    print(f"  Anthropic Q&A: {'enabled' if ANTHROPIC_API_KEY else 'disabled'}")
    print(f"  Users dir: {USERS_DIR}")
    print(f"  Polling for messages...\n")

    last_update_id = 0
    # Skip existing messages
    _, last_update_id = tg_get_updates(0)
    if last_update_id > 0:
        _, last_update_id = tg_get_updates(last_update_id)

    while True:
        try:
            messages, last_update_id = tg_get_updates(last_update_id)

            for msg in messages:
                print(f"  [{msg['chat_id']}] {msg.get('text', '<photo>')[:60]}")
                try:
                    handle_message(msg)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    tg_send(msg["chat_id"], "Something went wrong. Please try again.")

        except Exception as e:
            print(f"  Poll error: {e}")

        time.sleep(2)  # Check for messages every 2 seconds


if __name__ == "__main__":
    main()
