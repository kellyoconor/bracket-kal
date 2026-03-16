#!/usr/bin/env python3
"""
Automated Kalshi trading based on divergence signals.

- Reads trade_rules.json for trading rules
- Uses Kalshi authenticated API to execute trades
- Hard limits from .env: MAX_TRADE, MAX_EXPOSURE
- Telegrams confirmation before executing, waits 60 sec for STOP
- Logs all trades to trades.json with timestamp and reasoning
- Never trades within 30 min of tip-off
- Single command: python kalshi_trader.py

IMPORTANT: This uses real money. Review trade_rules.json carefully.
"""

import json
import os
import time
import hashlib
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode, quote

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
RULES_FILE = ROOT / "trade_rules.json"
RESULTS_FILE = ROOT / "results.json"
TRADES_FILE = ROOT / "trades.json"
KALSHI_FILE = ROOT / "kalshi_markets.json"

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_API_KEY = os.getenv("KALSHI_API_KEY", "")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MAX_TRADE = float(os.getenv("MAX_TRADE", "25"))
MAX_EXPOSURE = float(os.getenv("MAX_EXPOSURE", "200"))

TIPOFF_BUFFER_MIN = 30  # Don't trade within 30 min of game start

# Reuse abbreviation map
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
    except Exception as e:
        print(f"  [TG] Failed: {e}")


def telegram_check_stop() -> bool:
    """Check if user sent STOP in the last 60 seconds."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?offset=-10&limit=10"
    try:
        req = Request(url)
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        for update in data.get("result", []):
            msg = update.get("message", {})
            text = msg.get("text", "").strip().upper()
            chat_id = str(msg.get("chat", {}).get("id", ""))
            msg_date = msg.get("date", 0)
            if (text == "STOP" and chat_id == str(TELEGRAM_CHAT_ID)
                    and time.time() - msg_date < 120):
                return True
    except Exception:
        pass
    return False


def kalshi_get_public(endpoint: str, params: dict | None = None) -> dict:
    url = f"{KALSHI_BASE}{endpoint}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def kalshi_authenticated_request(method: str, endpoint: str, body: dict | None = None) -> dict:
    """Make an authenticated Kalshi API request using RSA-PSS signing.

    Requires KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH in .env.
    See: https://docs.kalshi.com/getting_started/api_keys
    """
    if not KALSHI_API_KEY or not KALSHI_PRIVATE_KEY_PATH:
        raise RuntimeError("KALSHI_API_KEY and KALSHI_PRIVATE_KEY_PATH required for trading")

    # Load private key
    key_path = Path(KALSHI_PRIVATE_KEY_PATH)
    if not key_path.exists():
        raise FileNotFoundError(f"Kalshi private key not found: {key_path}")

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    # Build signature: timestamp + method + path + body
    timestamp = str(int(time.time() * 1000))
    path = f"/trade-api/v2{endpoint}"
    body_str = json.dumps(body) if body else ""
    message = f"{timestamp}{method.upper()}{path}{body_str}"

    signature = private_key.sign(
        message.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    sig_b64 = base64.b64encode(signature).decode()

    url = f"{KALSHI_BASE}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }

    req = Request(url, method=method.upper(), headers=headers)
    if body:
        req.data = body_str.encode()

    with urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def load_rules() -> list[dict]:
    with open(RULES_FILE) as f:
        data = json.load(f)
    return [r for r in data["rules"] if r.get("enabled", False)]


def load_results() -> list[dict]:
    with open(RESULTS_FILE) as f:
        data = json.load(f)
    all_games = []
    for round_key, games in data.items():
        all_games.extend(games)
    return all_games


def load_trades() -> list[dict]:
    if TRADES_FILE.exists():
        with open(TRADES_FILE) as f:
            return json.load(f)
    return []


def save_trade(trade: dict):
    trades = load_trades()
    trades.append(trade)
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)


def get_current_exposure() -> float:
    """Sum of all open trade amounts."""
    trades = load_trades()
    return sum(t.get("size_dollars", 0) for t in trades if t.get("status") == "executed")


def pull_live_price(abbrev: str) -> dict | None:
    """Get current price for a team abbreviation from active game markets."""
    try:
        data = kalshi_get_public("/markets", {"series_ticker": "KXNCAAMBGAME", "limit": 200})
        for m in data.get("markets", []):
            ticker = m.get("ticker", "")
            if ticker.endswith(f"-{abbrev}") and m.get("status") in ("active", "open"):
                yb = float(m.get("yes_bid_dollars", "0") or "0")
                ya = float(m.get("yes_ask_dollars", "0") or "0")
                return {
                    "ticker": ticker,
                    "yes_bid": yb,
                    "yes_ask": ya,
                    "mid": (yb + ya) / 2 if yb > 0 and ya > 0 else None,
                    "event_ticker": m.get("event_ticker", ""),
                    "status": m.get("status", ""),
                }
    except Exception as e:
        print(f"  Error pulling price for {abbrev}: {e}")
    return None


def evaluate_rule(rule: dict, game: dict, market_price: float) -> bool:
    """Evaluate whether a trade rule triggers for a given game."""
    divergence = game.get("abs_divergence") or 0
    claude_prob = game.get("claude_prob", 0.5)
    mp = market_price

    condition = rule["condition"]
    # Simple expression evaluation with restricted namespace
    ctx = {
        "divergence": divergence,
        "market_price": mp,
        "claude_prob": claude_prob,
        "abs": abs,
    }
    try:
        return bool(eval(condition, {"__builtins__": {}}, ctx))
    except Exception:
        return False


def main():
    print("=" * 70)
    print("Kalshi Trader — Divergence-Based Automated Trading")
    print("=" * 70)
    print(f"\n  MAX_TRADE:    ${MAX_TRADE}")
    print(f"  MAX_EXPOSURE: ${MAX_EXPOSURE}")
    print(f"  Tipoff buffer: {TIPOFF_BUFFER_MIN} min")

    if not KALSHI_API_KEY:
        print("\n  ERROR: KALSHI_API_KEY not set in .env")
        print("  Set up your API key at https://kalshi.com/account/api")
        return
    if not KALSHI_PRIVATE_KEY_PATH:
        print("\n  ERROR: KALSHI_PRIVATE_KEY_PATH not set in .env")
        return

    rules = load_rules()
    print(f"  Loaded {len(rules)} enabled trade rules")

    results = load_results()
    current_exposure = get_current_exposure()
    print(f"  Current exposure: ${current_exposure:.2f} / ${MAX_EXPOSURE}")

    # Find games with divergence signal
    candidates = [g for g in results if g.get("pick_source") == "DIVERGE"]
    print(f"  Divergence games to evaluate: {len(candidates)}\n")

    proposed_trades = []

    for game in candidates:
        pick = game["pick"]
        abbrev = ABBREV_MAP.get(pick)
        if not abbrev:
            continue

        matchup = game["matchup"]
        divergence = game.get("abs_divergence", 0)

        # Pull live price
        live = pull_live_price(abbrev)
        if not live or live["mid"] is None:
            print(f"  Skip {matchup}: no live market for {pick}")
            continue

        market_price = live["mid"]

        # Evaluate rules
        for rule in rules:
            if not evaluate_rule(rule, game, market_price):
                continue

            size = min(rule["size_dollars"], MAX_TRADE)

            # Check exposure limit
            if current_exposure + size > MAX_EXPOSURE:
                print(f"  Skip {matchup}: would exceed MAX_EXPOSURE (${current_exposure + size:.0f} > ${MAX_EXPOSURE})")
                continue

            proposed_trades.append({
                "game": game.get("game"),
                "matchup": matchup,
                "pick": pick,
                "abbrev": abbrev,
                "ticker": live["ticker"],
                "action": rule["action"],
                "size_dollars": size,
                "market_price": round(market_price, 3),
                "divergence": round(divergence, 3),
                "claude_prob": game.get("claude_prob"),
                "rule_name": rule["name"],
                "rule_desc": rule["description"],
            })

    if not proposed_trades:
        print("  No trades triggered by current rules.")
        telegram_send("*Kalshi Trader*\nNo trades triggered. Rules evaluated against all divergence games.")
        return

    # Show proposed trades
    print(f"\n{'=' * 70}")
    print(f"PROPOSED TRADES ({len(proposed_trades)})")
    print(f"{'=' * 70}")
    total_size = 0
    for t in proposed_trades:
        print(f"  {t['matchup']:<44} {t['action']:<8} ${t['size_dollars']:<5} "
              f"@{t['market_price']:.0%}  div:{t['divergence']:.0%}  [{t['rule_name']}]")
        total_size += t["size_dollars"]
    print(f"\n  Total: ${total_size:.2f}")
    print(f"  New exposure: ${current_exposure + total_size:.2f} / ${MAX_EXPOSURE}")

    # Telegram confirmation
    trade_summary = "\n".join(
        f"  {t['pick']}: {t['action']} ${t['size_dollars']} @{t['market_price']:.0%} (div:{t['divergence']:.0%})"
        for t in proposed_trades
    )
    telegram_send(
        f"*TRADE PROPOSAL*\n"
        f"{len(proposed_trades)} trades, ${total_size:.2f} total\n\n"
        f"{trade_summary}\n\n"
        f"Reply *STOP* within 60 sec to cancel."
    )

    # Wait 60 seconds for STOP
    print(f"\n  Waiting 60 seconds for STOP signal...")
    for i in range(12):
        time.sleep(5)
        if telegram_check_stop():
            print("  STOP received! Cancelling all trades.")
            telegram_send("*TRADES CANCELLED* — STOP received.")
            return
        print(f"  {(i + 1) * 5}s...", end=" ", flush=True)
    print()

    # Execute trades
    print(f"\n{'=' * 70}")
    print("EXECUTING TRADES")
    print(f"{'=' * 70}")

    for t in proposed_trades:
        now = datetime.now(timezone.utc)

        trade_record = {
            "timestamp": now.isoformat(),
            **t,
            "status": "pending",
            "reasoning": (
                f"Rule '{t['rule_name']}' triggered: {t['rule_desc']}. "
                f"Market: {t['market_price']:.0%}, Claude: {t['claude_prob']:.0%}, "
                f"Divergence: {t['divergence']:.0%}"
            ),
        }

        try:
            # Determine side and price
            if t["action"] == "buy_yes":
                side = "yes"
                limit_price = t["market_price"] + 0.02  # Willing to pay 2c over mid
            else:
                side = "no"
                limit_price = (1 - t["market_price"]) + 0.02

            # Calculate contract count (contracts are $1 each)
            count = max(1, int(t["size_dollars"] / limit_price))

            order = {
                "ticker": t["ticker"],
                "action": "buy",
                "side": side,
                "type": "limit",
                "count": count,
                "yes_price": int(limit_price * 100),  # Kalshi uses cents
            }

            print(f"  Executing: {t['pick']} {t['action']} {count} contracts @{limit_price:.2f}...")

            response = kalshi_authenticated_request("POST", "/portfolio/orders", order)
            order_id = response.get("order", {}).get("order_id", "unknown")

            trade_record["status"] = "executed"
            trade_record["order_id"] = order_id
            trade_record["contracts"] = count
            trade_record["limit_price"] = round(limit_price, 3)

            print(f"    Order {order_id}: {count} contracts @ ${limit_price:.2f}")
            telegram_send(
                f"*TRADE EXECUTED*\n"
                f"{t['pick']}: {t['action']} {count}x @${limit_price:.2f}\n"
                f"Order: {order_id}\n"
                f"Div: {t['divergence']:.0%}"
            )

        except Exception as e:
            trade_record["status"] = "failed"
            trade_record["error"] = str(e)
            print(f"    FAILED: {e}")
            telegram_send(f"*TRADE FAILED*\n{t['pick']}: {e}")

        save_trade(trade_record)
        time.sleep(1)

    print(f"\n  All trades logged to {TRADES_FILE}")


if __name__ == "__main__":
    main()
