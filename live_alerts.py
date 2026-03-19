#!/usr/bin/env python3
"""
Multi-user live alert system for bracket picks.

Polls ESPN (every 30s during live games) and Kalshi (every 10min),
sends personalized alerts to each user with an active bracket.

Alert types:
  - Halftime scores
  - Crunch time (under 5 min, close game)
  - Upset brewing (divergence pick leading big)
  - Game resolution (W/L with score tracking)
  - Odds movement (5%+ drops)
"""

import json
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode

ROOT = Path(__file__).parent
RESULTS_FILE = ROOT / "results.json"

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"

LIVE_POLL_INTERVAL = 30
KALSHI_POLL_INTERVAL = 600

# Per-user alert rate limits
MAX_ALERTS_PER_HOUR = 20

TOURNAMENT_DATES = [
    "MAR17", "MAR18", "MAR19", "MAR20", "MAR21", "MAR22",
    "MAR23", "MAR24", "MAR27", "MAR28", "MAR29", "MAR30",
    "APR05", "APR07",
]

# ─── Team abbreviation maps ────────────────────────────────────────────────

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

ESPN_ABBREV_MAP = {
    "Duke": "DUKE", "Siena": "SIE", "Ohio State": "OSU", "TCU": "TCU",
    "St. John's": "SJU", "Northern Iowa": "UNI", "Kansas": "KU",
    "Cal Baptist": "CBU", "Louisville": "LOU", "South Florida": "USF",
    "Michigan State": "MSU", "North Dakota State": "NDSU", "UCLA": "UCLA",
    "UCF": "UCF", "UConn": "UCONN", "Furman": "FUR",
    "Arizona": "ARIZ", "LIU": "LIU", "Villanova": "NOVA",
    "Utah State": "USU", "Wisconsin": "WIS", "High Point": "HPU",
    "Arkansas": "ARK", "Hawaii": "HAW", "BYU": "BYU", "Texas": "TEX",
    "Gonzaga": "GONZ", "Kennesaw State": "KENN", "Miami (FL)": "MIA",
    "Missouri": "MIZ", "Purdue": "PUR", "Queens": "QUEEN",
    "Florida": "FLA", "Prairie View A&M": "PVAMU",
    "Clemson": "CLEM", "Iowa": "IOWA", "Vanderbilt": "VAN",
    "McNeese": "MCN", "Nebraska": "NEB", "Troy": "TROY",
    "North Carolina": "UNC", "VCU": "VCU", "Illinois": "ILL",
    "Penn": "PENN", "Saint Mary's": "SMC", "Texas A&M": "TA&M",
    "Houston": "HOU", "Idaho": "IDHO",
    "Michigan": "MICH", "UMBC": "UMBC", "Georgia": "UGA",
    "Saint Louis": "SLU", "Texas Tech": "TTU", "Akron": "AKR",
    "Alabama": "ALA", "Hofstra": "HOF", "Tennessee": "TENN",
    "SMU": "SMU", "Virginia": "UVA", "Wright State": "WRST",
    "Kentucky": "UK", "Santa Clara": "SCU", "Iowa State": "ISU",
    "Tennessee State": "TNST",
}

# Round code -> results.json key
ROUND_KEY = {"R64": "64", "R32": "32", "S16": "16", "E8": "8", "F4": "4", "CHAMP": "2"}


# ─── Pick enrichment ───────────────────────────────────────────────────────

def enrich_user_picks(user_picks: list[dict]) -> list[dict]:
    """
    Enrich flat user picks with game numbers, matchups, regions, and divergence data.

    Input:  [{"round": "R64", "team": "Duke"}, ...]
    Output: [{"picked_team": "Duke", "round": "R64", "game": 1,
              "matchup": "(1) Duke vs (16) Siena", "region": "East",
              "pick_source": "CHALK", "divergence": -0.021}, ...]
    """
    if not RESULTS_FILE.exists():
        return []

    with open(RESULTS_FILE) as f:
        results = json.load(f)

    # Build lookup: {(round_key, team_name): game_entry} from results.json
    lookup = {}
    for round_key, games in results.items():
        for g in games:
            ta = g.get("team_a", {}).get("team", "")
            tb = g.get("team_b", {}).get("team", "")
            if ta:
                lookup[(round_key, ta)] = g
            if tb:
                lookup[(round_key, tb)] = g

    enriched = []
    for pick in user_picks:
        team = pick.get("team", "")
        round_code = pick.get("round", "")
        rkey = ROUND_KEY.get(round_code, "")

        entry = lookup.get((rkey, team))
        if entry:
            model_pick = entry.get("pick", "")
            if team == model_pick:
                pick_source = entry.get("pick_source", "CHALK")
            else:
                pick_source = "USER"

            enriched.append({
                "picked_team": team,
                "round": round_code,
                "game": entry.get("game"),
                "matchup": entry.get("matchup", ""),
                "region": entry.get("region", ""),
                "pick_source": pick_source,
                "divergence": entry.get("divergence"),
                "abs_divergence": entry.get("abs_divergence"),
            })
        else:
            enriched.append({
                "picked_team": team,
                "round": round_code,
                "game": None,
                "matchup": "",
                "region": "",
                "pick_source": "USER",
                "divergence": None,
                "abs_divergence": None,
            })

    return enriched


# ─── Data fetchers ─────────────────────────────────────────────────────────

def fetch_live_scores() -> dict[str, dict]:
    """Fetch today's live scores from ESPN. Returns {espn_abbrev: game_info}."""
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    url = f"{ESPN_SCOREBOARD}?dates={today}&groups=50&limit=100"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"  [alerts] ESPN error: {e}")
        return {}

    scores = {}
    for event in data.get("events", []):
        status_obj = event.get("status", {})
        status_type = status_obj.get("type", {})
        state = status_type.get("state", "")
        description = status_type.get("description", "")
        period = status_obj.get("period", 0)
        clock = status_obj.get("displayClock", "")

        comps = event.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])

        teams = {}
        for c in competitors:
            abbrev = c.get("team", {}).get("abbreviation", "")
            name = c.get("team", {}).get("displayName", "")
            score_val = c.get("score", "0")
            try:
                teams[abbrev] = {"name": name, "score": int(score_val or 0)}
            except (ValueError, TypeError):
                teams[abbrev] = {"name": name, "score": 0}

        for abbrev in teams:
            scores[abbrev] = {
                "state": state, "description": description,
                "period": period, "clock": clock, "teams": teams,
            }

    return scores


def is_tournament_game(ticker: str) -> bool:
    return any(date in ticker for date in TOURNAMENT_DATES)


def pull_game_odds() -> dict[str, dict]:
    """Pull current Kalshi odds for tournament games."""
    odds = {}
    cursor = None
    while True:
        try:
            params = {"series_ticker": "KXNCAAMBGAME", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            url = f"{KALSHI_BASE}/markets?" + urlencode(params)
            req = Request(url, headers={"Accept": "application/json"})
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            # Rate limited or network error — return what we have so far
            if odds:
                print(f"  [alerts] Kalshi error (returning {len(odds)} partial): {e}")
            else:
                print(f"  [alerts] Kalshi error: {e}")
            break
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
                        "prob": prob, "status": status, "ticker": ticker,
                    }
        cursor = data.get("cursor")
        if not cursor or not markets:
            break
    return odds


# ─── Per-user alert state (persisted to disk) ─────────────────────────────

USERS_DIR = ROOT / "users"
ALERT_STATE_FILE = "alert_state.json"


class UserAlertState:
    __slots__ = ("chat_id", "alerted_keys", "prev_odds", "alert_timestamps")

    def __init__(self, chat_id: str = ""):
        self.chat_id = chat_id
        self.alerted_keys: set[str] = set()
        self.prev_odds: dict[str, float] = {}
        self.alert_timestamps: list[float] = []

    def can_send(self) -> bool:
        now = time.time()
        cutoff = now - 3600
        self.alert_timestamps = [t for t in self.alert_timestamps if t > cutoff]
        return len(self.alert_timestamps) < MAX_ALERTS_PER_HOUR

    def record_send(self):
        self.alert_timestamps.append(time.time())

    def save(self):
        """Persist alerted_keys and prev_odds to disk."""
        if not self.chat_id:
            return
        state_dir = USERS_DIR / str(self.chat_id)
        if not state_dir.exists():
            return
        path = state_dir / ALERT_STATE_FILE
        data = {
            "alerted_keys": list(self.alerted_keys),
            "prev_odds": self.prev_odds,
        }
        try:
            import tempfile, os
            fd, tmp = tempfile.mkstemp(dir=state_dir, suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except Exception as e:
            print(f"  [alerts] Save state failed for {self.chat_id}: {e}")

    @classmethod
    def load(cls, chat_id: str) -> "UserAlertState":
        """Load persisted state from disk, or create fresh."""
        state = cls(chat_id)
        path = USERS_DIR / str(chat_id) / ALERT_STATE_FILE
        if path.exists():
            try:
                with open(path) as f:
                    data = json.load(f)
                state.alerted_keys = set(data.get("alerted_keys", []))
                state.prev_odds = data.get("prev_odds", {})
            except Exception as e:
                print(f"  [alerts] Load state failed for {chat_id}: {e}")
        return state


_alert_states: dict[str, UserAlertState] = {}


def _get_alert_state(chat_id: str) -> UserAlertState:
    if chat_id not in _alert_states:
        _alert_states[chat_id] = UserAlertState.load(chat_id)
    return _alert_states[chat_id]


# ─── Alert checker ─────────────────────────────────────────────────────────

def check_alerts_for_user(
    enriched_picks: list[dict],
    score: dict,
    live_scores: dict,
    game_odds: dict,
    alert_state: UserAlertState,
) -> tuple[list[str], bool]:
    """
    Check for alerts for a single user.
    Returns (list of message strings, whether score was modified).
    """
    messages = []
    score_changed = False

    # Only process the earliest unresolved round per team for ALL alert types.
    # This prevents R32 projected matchups from triggering during R64 games
    # (both ESPN live scores and Kalshi odds movement/resolution).
    processed_teams: set[str] = set()

    for pick in enriched_picks:
        team = pick["picked_team"]
        game_id = pick.get("game")
        matchup = pick.get("matchup", "")
        source = pick.get("pick_source", "?")
        region = pick.get("region", "")
        divergence = pick.get("divergence")

        if not game_id:
            continue
        if game_id in score.get("resolved_games", []):
            # Still mark team as processed so later-round picks are skipped
            processed_teams.add(team)
            continue

        # Skip if we already processed an earlier-round pick for this team
        if team in processed_teams:
            continue

        # ─── Live score alerts (ESPN) ─────────────────────────────
        espn_abbrev = ESPN_ABBREV_MAP.get(team)

        if espn_abbrev and espn_abbrev in live_scores:
            game = live_scores[espn_abbrev]
            if game["state"] == "in":
                teams = game["teams"]
                our_score = teams.get(espn_abbrev, {}).get("score", 0)
                opp_abbrevs = [a for a in teams if a != espn_abbrev]
                opp_score = teams[opp_abbrevs[0]]["score"] if opp_abbrevs else 0
                opp_name = teams[opp_abbrevs[0]]["name"] if opp_abbrevs else "opponent"

                # Use the actual live game for display, not projected bracket matchup
                live_matchup = f"{team} vs {opp_name}"
                if region:
                    live_matchup += f" ({region})"

                period = game["period"]
                clock = game["clock"]
                description = game["description"]
                margin = abs(our_score - opp_score)
                leading = our_score > opp_score
                tied = our_score == opp_score

                # Halftime
                alert_key = f"{game_id}:{description}"
                if description == "Halftime" and alert_key not in alert_state.alerted_keys:
                    if leading:
                        status_word = f"leads by {margin}"
                    elif tied:
                        status_word = "tied"
                    else:
                        status_word = f"trails by {margin}"

                    msg = (
                        f"\U0001f3c0 Halftime: {team} {our_score}, {opp_name} {opp_score}\n\n"
                        f"{live_matchup}\n"
                        f"Your pick {status_word}."
                    )
                    alert_state.alerted_keys.add(alert_key)
                    messages.append(msg)

                # Crunch time
                elif period == 2 and ":" in clock and alert_key not in alert_state.alerted_keys:
                    try:
                        mins = int(clock.split(":")[0])
                    except ValueError:
                        mins = 99
                    if mins < 5 and margin <= 8:
                        if leading:
                            verb = "holding on"
                        elif tied:
                            verb = "tied up"
                        else:
                            verb = "fighting back"
                        msg = (
                            f"\U0001f525 Crunch time: {team} {our_score}, {opp_name} {opp_score} "
                            f"({clock} left)\n\n"
                            f"{live_matchup}\n"
                            f"{team} {verb}."
                        )
                        alert_state.alerted_keys.add(alert_key)
                        messages.append(msg)

                # Upset brewing
                upset_key = f"{game_id}:upset_alert"
                if (source in ("DIVERGE", "USER") and leading and margin >= 10
                        and upset_key not in alert_state.alerted_keys):
                    div_str = f" with a {abs(divergence):.0%} gap" if divergence else ""
                    msg = (
                        f"\U0001f6a8 Upset brewing: {team} up {margin}! "
                        f"({our_score}-{opp_score}, {clock} {description})\n\n"
                        f"{live_matchup}\n"
                        f"Bold pick paying off{div_str}."
                    )
                    alert_state.alerted_keys.add(upset_key)
                    messages.append(msg)

        # ─── Kalshi odds: resolution + movement ───────────────────
        kalshi_abbrev = ABBREV_MAP.get(team)
        if not kalshi_abbrev:
            continue
        market = game_odds.get(kalshi_abbrev)
        if not market:
            continue

        current_prob = market["prob"]
        status = market["status"]

        # Game resolution — only trust if ESPN confirms the team actually played
        if status in ("closed", "determined", "finalized"):
            espn_abbrev = ESPN_ABBREV_MAP.get(team)
            espn_game = live_scores.get(espn_abbrev, {}) if espn_abbrev else {}
            espn_state = espn_game.get("state", "")

            if espn_state not in ("in", "post"):
                # Kalshi closed this market but the team didn't play today —
                # phantom closure from another team's elimination. Skip it.
                continue

            won = current_prob >= 0.90
            score["resolved_games"].append(game_id)
            if won:
                score["correct"] += 1
            else:
                score["busted"] += 1
            score_changed = True

            total_w = score["correct"]
            total_l = score["busted"]
            parts = matchup.split(" vs ")
            opponent = parts[1] if len(parts) > 1 and team in parts[0] else (parts[0] if len(parts) > 1 else "opponent")

            if won:
                if source == "DIVERGE":
                    context = (
                        f"This was a model pick — the market had them lower "
                        f"but our model saw the edge."
                    )
                elif source == "USER":
                    context = "Your pick paid off."
                else:
                    context = "Chalk pick — no surprises here."
                msg = (
                    f"\u2705 {team} wins!\n\n"
                    f"{matchup} ({region})\n"
                    f"{context}\n\n"
                    f"\U0001f4ca Record: {total_w}W / {total_l}L"
                )
            else:
                if source == "DIVERGE":
                    div_str = f" (we saw a {abs(divergence):.0%} gap)" if divergence else ""
                    context = (
                        f"Model pick missed{div_str}. Our model liked {team} "
                        f"more than the market did, but the market was right."
                    )
                elif source == "USER":
                    context = f"Your pick — tough break."
                else:
                    context = f"Both the market and model had {team}. Sometimes the madness wins."
                msg = (
                    f"\u274c {team} is out.\n\n"
                    f"{matchup} ({region})\n"
                    f"{opponent.strip()} advances.\n"
                    f"{context}\n\n"
                    f"\U0001f4ca Record: {total_w}W / {total_l}L"
                )
            messages.append(msg)

            # If the team lost, cascade to all future-round picks so they
            # never fire (Kalshi closes those markets immediately).
            if not won:
                for future_pick in enriched_picks:
                    if future_pick["picked_team"] == team:
                        fid = future_pick.get("game")
                        if fid and fid not in score["resolved_games"]:
                            score["resolved_games"].append(fid)
                            score_changed = True

            continue

        # Odds movement
        odds_key = f"{game_id}:{kalshi_abbrev}"
        prev = alert_state.prev_odds.get(odds_key)
        if prev is not None:
            drop = prev - current_prob
            if drop >= 0.05:
                if source == "DIVERGE":
                    context = (
                        f"\n\nThis is a model pick — we overrode the market here. "
                        f"It's moving against us. Could be injury news, could be "
                        f"sharp money. Worth watching."
                    )
                elif source == "USER":
                    context = (
                        f"\n\nThis is one of your picks that differs from our model. "
                        f"The market is moving against it."
                    )
                else:
                    context = (
                        f"\n\nChalk pick — both the market and model liked them, "
                        f"but the market is softening."
                    )
                msg = (
                    f"\U0001f4c9 Market movement: {team} dropping.\n\n"
                    f"{matchup}\n"
                    f"Was {prev:.0%}, now {current_prob:.0%}."
                    f"{context}"
                )
                messages.append(msg)
        alert_state.prev_odds[odds_key] = current_prob

        # Mark team as processed so later-round picks are skipped
        processed_teams.add(team)

    return messages, score_changed


# ─── Main alert loop ───────────────────────────────────────────────────────

def alert_loop(get_users_fn, send_fn, save_score_fn, stop_event: threading.Event):
    """
    Background alert loop. Polls ESPN/Kalshi and sends alerts to all active users.

    Args:
        get_users_fn: () -> list[(chat_id, user_data)] with enriched picks
        send_fn: (chat_id, message) -> None
        save_score_fn: (chat_id, score_dict) -> None (thread-safe score update)
        stop_event: threading.Event
    """
    print("  [alerts] Live alert loop started")
    game_odds: dict[str, dict] = {}
    last_kalshi_poll = 0.0
    any_live = False

    while not stop_event.is_set():
        try:
            # ESPN live scores (shared across all users)
            live_scores = fetch_live_scores()
            any_live = any(g.get("state") == "in" for g in live_scores.values())

            # Kalshi odds (every 10 min)
            if time.time() - last_kalshi_poll >= KALSHI_POLL_INTERVAL:
                game_odds = pull_game_odds()
                last_kalshi_poll = time.time()
                if game_odds:
                    print(f"  [alerts] Loaded {len(game_odds)} Kalshi prices")

            # Check each user
            users = get_users_fn()
            for chat_id, user in users:
                try:
                    enriched = user.get("enriched_picks", [])
                    if not enriched:
                        continue
                    if not user.get("alerts_enabled", True):
                        continue

                    alert_state = _get_alert_state(chat_id)
                    score = user.get("score", {
                        "correct": 0, "busted": 0, "resolved_games": [],
                    })

                    msgs, score_changed = check_alerts_for_user(
                        enriched, score, live_scores, game_odds, alert_state,
                    )

                    for msg in msgs:
                        if alert_state.can_send():
                            send_fn(chat_id, msg)
                            alert_state.record_send()

                    # Persist alert state (prev_odds, alerted_keys) to disk
                    if msgs or game_odds:
                        alert_state.save()

                    if score_changed:
                        try:
                            save_score_fn(chat_id, score)
                        except Exception as e:
                            print(f"  [alerts] Save failed for {chat_id}: {e}")

                except Exception as e:
                    print(f"  [alerts] Error for user {chat_id}: {e}")
                    continue

        except Exception as e:
            print(f"  [alerts] Error: {e}")

        # Poll faster during live games
        wait = LIVE_POLL_INTERVAL if any_live else KALSHI_POLL_INTERVAL
        stop_event.wait(wait)

    print("  [alerts] Alert loop stopped")
