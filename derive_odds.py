#!/usr/bin/env python3
"""
Derive implied first-round head-to-head win probabilities from Kalshi
championship odds. For each matchup, normalize both teams' championship
prices against each other to get an implied game-level probability.

Reads:  matchups.json, kalshi_markets.json
Writes: matchups_with_odds.json
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
MATCHUPS_FILE = ROOT / "matchups.json"
KALSHI_FILE = ROOT / "kalshi_markets.json"
OUTPUT_FILE = ROOT / "matchups_with_odds.json"

# Map matchups.json team names -> Kalshi market names
# Kalshi uses abbreviations like "St." and "Hawai'i"
TEAM_ALIASES = {
    # State -> St. abbreviations
    "Michigan State": "Michigan St.",
    "Ohio State": "Ohio St.",
    "Utah State": "Utah St.",
    "Iowa State": "Iowa St.",
    "Mississippi State": "Mississippi St.",
    "Kennesaw State": "Kennesaw St.",
    "Tennessee State": "Tennessee St.",
    "Norfolk State": "Norfolk St.",
    "Wright State": "Wright St.",
    "Colorado State": "Colorado St.",
    "North Dakota State": "North Dakota St.",
    "San Diego State": "San Diego St.",
    "Alabama State": "Alabama St.",
    # Other spelling differences
    "Cal Baptist": "California Baptist",
    "Hawaii": "Hawai'i",
    "NC State": "North Carolina St.",
    "Connecticut": "UConn",
    "SIU Edwardsville": "SIU Edwardsville",
    # Names that match exactly but included for documentation
    "Saint Mary's": "Saint Mary's",
    "St. John's": "St. John's",
    "Prairie View A&M": "Prairie View A&M",
    "South Florida": "South Florida",
    "North Carolina": "North Carolina",
    "Miami (FL)": "Miami (FL)",
    "Texas A&M": "Texas A&M",
    "Texas Tech": "Texas Tech",
}

# Floor probability for teams with no Kalshi market or zero liquidity
FLOOR_PROB = 0.003


def load_kalshi_odds() -> dict[str, float]:
    """Parse kalshi_markets.json into {team_name: championship_implied_prob}."""
    with open(KALSHI_FILE) as f:
        data = json.load(f)

    odds = {}
    for m in data["KXMARMAD"]:
        title = m.get("title", "")
        team = title.replace("Will ", "").replace(
            " win the College Basketball National Championship?", ""
        )
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        lp = float(m.get("last_price_dollars", "0") or "0")

        if yb > 0 and ya > 0:
            odds[team] = (yb + ya) / 2
        elif lp > 0:
            odds[team] = lp
        else:
            odds[team] = FLOOR_PROB

    return odds


def lookup(team: str, odds: dict[str, float]) -> float:
    """Find a team's championship probability with fuzzy name matching."""
    if team in odds:
        return odds[team]
    alias = TEAM_ALIASES.get(team)
    if alias and alias in odds:
        return odds[alias]
    for kalshi_name, prob in odds.items():
        if team.lower() in kalshi_name.lower() or kalshi_name.lower() in team.lower():
            return prob
    return FLOOR_PROB


def derive_head_to_head(prob_a: float, prob_b: float) -> float:
    """Normalize two championship probabilities into a head-to-head win prob for team A."""
    total = prob_a + prob_b
    if total == 0:
        return 0.5
    return prob_a / total


def main():
    kalshi = load_kalshi_odds()
    print(f"Loaded {len(kalshi)} teams from Kalshi championship markets\n")

    with open(MATCHUPS_FILE) as f:
        data = json.load(f)

    enriched = []
    unmatched = []

    print(f"{'Game':<5} {'Matchup':<50} {'Champ A':>8} {'Champ B':>8} {'H2H':>8}")
    print("-" * 85)

    for matchup in data["matchups"]:
        higher = matchup["higher_seed"]
        lower = matchup["lower_seed"]

        champ_h = lookup(higher["team"], kalshi)
        champ_l = lookup(lower["team"], kalshi)
        market_prob = derive_head_to_head(champ_h, champ_l)

        label = f"({higher['seed']}) {higher['team']} vs ({lower['seed']}) {lower['team']}"
        print(
            f"{matchup['game']:<5} {label:<50} "
            f"{champ_h:>7.2%} {champ_l:>7.2%} {market_prob:>7.1%}"
        )

        if champ_h <= FLOOR_PROB:
            unmatched.append(higher["team"])
        if champ_l <= FLOOR_PROB:
            unmatched.append(lower["team"])

        enriched.append({
            **matchup,
            "higher_seed": {
                **higher,
                "kalshi_champ_prob": round(champ_h, 4),
                "market_prob": round(market_prob, 4),
            },
            "lower_seed": {
                **lower,
                "kalshi_champ_prob": round(champ_l, 4),
                "market_prob": round(1 - market_prob, 4),
            },
            "market_prob": round(market_prob, 4),
        })

    output = {**data, "matchups": enriched}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nSaved {len(enriched)} matchups to {OUTPUT_FILE}")

    if unmatched:
        print(f"\nWarning: {len(unmatched)} teams had no Kalshi market (used floor {FLOOR_PROB}):")
        for t in sorted(set(unmatched)):
            print(f"  - {t}")


if __name__ == "__main__":
    main()
