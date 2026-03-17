"""
Scrape ESPN Tournament Challenge brackets from their public API.

Given a bracket URL or UUID, returns structured pick data:
  - All 63 picks with team names and seeds
  - Bracket name, user display name
  - Score tracking (if games have started)
"""

import json
import re
from urllib.request import urlopen, Request

ESPN_API = "https://gambit-api.fantasy.espn.com/apis/v1/challenges/tournament-challenge-bracket-2026"
ESPN_CHALLENGE_ID = 277

# ESPN team ID -> our team name mapping
# These IDs come from ESPN's internal team database
# Updated for 2026 tournament field
ESPN_TEAM_MAP = {
    150: "Duke", 2561: "Siena", 194: "Ohio State", 2628: "TCU",
    2599: "St. John's", 2460: "Northern Iowa", 2305: "Kansas",
    2239: "Cal Baptist", 97: "Louisville", 58: "South Florida",
    127: "Michigan State", 2449: "North Dakota State", 26: "UCLA",
    2116: "UCF", 41: "UConn", 231: "Furman",
    12: "Arizona", 2335: "LIU", 2752: "Villanova",
    328: "Utah State", 275: "Wisconsin", 2314: "High Point",
    8: "Arkansas", 62: "Hawaii", 252: "BYU", 251: "Texas",
    2250: "Gonzaga", 338: "Kennesaw State", 2390: "Miami (FL)",
    142: "Missouri", 2509: "Purdue", 2769: "Queens",
    57: "Florida", 2504: "Prairie View A&M",
    228: "Clemson", 2294: "Iowa", 238: "Vanderbilt",
    2377: "McNeese", 158: "Nebraska", 2583: "Troy",
    153: "North Carolina", 2670: "VCU", 356: "Illinois",
    219: "Penn", 2608: "Saint Mary's", 245: "Texas A&M",
    248: "Houston", 70: "Idaho",
    130: "Michigan", 2378: "UMBC", 61: "Georgia",
    139: "Saint Louis", 2641: "Texas Tech", 2006: "Akron",
    333: "Alabama", 2275: "Hofstra", 2633: "Tennessee",
    2567: "SMU", 258: "Virginia", 2773: "Wright State",
    96: "Kentucky", 2541: "Santa Clara", 66: "Iowa State",
    2634: "Tennessee State",
}

# Reverse map for lookups
TEAM_NAME_TO_ID = {v: k for k, v in ESPN_TEAM_MAP.items()}


def extract_uuid(url_or_id: str) -> str | None:
    """Extract bracket UUID from an ESPN URL or raw UUID string."""
    # Full URL
    match = re.search(r'[?&]id=([a-f0-9-]{36})', url_or_id)
    if match:
        return match.group(1)
    # Raw UUID
    if re.match(r'^[a-f0-9-]{36}$', url_or_id.strip()):
        return url_or_id.strip()
    # Numeric ID (old format)
    if url_or_id.strip().isdigit():
        return url_or_id.strip()
    return None


def fetch_bracket(uuid: str) -> dict | None:
    """Fetch bracket entry from ESPN API."""
    url = f"{ESPN_API}/entries/{uuid}"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"ESPN API error: {e}")
        return None


def parse_picks(data: dict) -> dict:
    """Parse ESPN bracket response into structured picks.

    ESPN stores picks as 'propositions' — each game in each round
    has a proposition ID, and the user's pick is a team ID.
    """
    entry_id = data.get("id", "")
    name = data.get("name", "")
    member = data.get("member", {})
    display_name = member.get("displayName", "")

    # Score info
    score_data = data.get("score", {})
    overall_score = score_data.get("overallScore", 0)
    record = score_data.get("record", {})
    wins = record.get("wins", 0)
    losses = record.get("losses", 0)

    # Extract picks from propositions
    propositions = data.get("propositions", [])
    picks = []

    for prop in propositions:
        prop_id = prop.get("id", "")
        period = prop.get("scoringPeriodId", 0)  # 1=R64, 2=R32, 3=S16, 4=E8, 5=FF, 6=Champ
        pick_team_id = prop.get("pick", prop.get("teamId", 0))

        round_map = {1: "R64", 2: "R32", 3: "S16", 4: "E8", 5: "FF", 6: "CHAMP"}
        round_name = round_map.get(period, f"R{period}")

        team_name = ESPN_TEAM_MAP.get(pick_team_id, f"Team#{pick_team_id}")

        # Check if resolved
        result = prop.get("result", "")
        correct = result == "CORRECT" if result else None

        picks.append({
            "prop_id": prop_id,
            "round": round_name,
            "team_id": pick_team_id,
            "team": team_name,
            "correct": correct,
        })

    # Also try 'selections' format (ESPN has used both)
    selections = data.get("selections", [])
    if selections and not picks:
        for sel in selections:
            team_id = sel.get("teamId", sel.get("pick", 0))
            period = sel.get("scoringPeriodId", sel.get("period", 0))
            round_map = {1: "R64", 2: "R32", 3: "S16", 4: "E8", 5: "FF", 6: "CHAMP"}
            round_name = round_map.get(period, f"R{period}")
            team_name = ESPN_TEAM_MAP.get(team_id, f"Team#{team_id}")
            picks.append({
                "round": round_name,
                "team_id": team_id,
                "team": team_name,
            })

    # Group picks by round
    by_round = {}
    for p in picks:
        by_round.setdefault(p["round"], []).append(p)

    # Try to find champion (last pick or period 6)
    champ_picks = by_round.get("CHAMP", [])
    champion = champ_picks[0]["team"] if champ_picks else None
    if not champion and picks:
        champion = picks[-1]["team"]

    # Final Four teams
    ff_picks = by_round.get("FF", [])
    final_four = [p["team"] for p in ff_picks]

    return {
        "entry_id": entry_id,
        "name": name,
        "display_name": display_name,
        "champion": champion,
        "final_four": final_four,
        "score": overall_score,
        "wins": wins,
        "losses": losses,
        "picks": picks,
        "picks_by_round": by_round,
        "total_picks": len(picks),
        "raw_keys": list(data.keys()),
    }


def fetch_and_parse(url_or_id: str) -> dict | None:
    """Full pipeline: URL -> UUID -> API -> parsed picks."""
    uuid = extract_uuid(url_or_id)
    if not uuid:
        return None

    data = fetch_bracket(uuid)
    if not data:
        return None

    return parse_picks(data)
