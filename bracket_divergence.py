#!/usr/bin/env python3
"""
Bracket Divergence: Derive win probabilities from Kalshi championship odds,
run Claude's blind assessment, surface divergence, make picks — ALL ROUNDS.

Two pick modes:
  MARKET SIGNAL — Kalshi has meaningful spread between teams. Divergence logic applies.
  CLAUDE ONLY  — Both teams at Kalshi floor (no market differentiation). Claude's
                 assessment IS the pick.

Round of 64 -> Round of 32 -> Sweet 16 -> Elite 8 -> Final Four -> Championship
"""

import json
import sys
import time
from pathlib import Path

import truststore
truststore.inject_into_ssl()

import anthropic

ROOT = Path(__file__).parent
KALSHI_FILE = ROOT / "kalshi_markets.json"
MODEL = "claude-sonnet-4-6"

# Divergence thresholds (percentage points) — only apply to MARKET SIGNAL games
SIGNIFICANT_DIVERGENCE = 0.08  # 8pp
STRONG_DIVERGENCE = 0.15       # 15pp

# Championship odds at or below this are considered "floor" — no real market signal
FLOOR_THRESHOLD = 0.012  # ~1.2% — Kalshi's minimum tick is $0.01

ROUND_NAMES = {
    64: "Round of 64",
    32: "Round of 32",
    16: "Sweet 16",
    8: "Elite 8",
    4: "Final Four",
    2: "Championship",
}

# Historical seed win rates — Bayesian prior for MARKET SIGNAL games
SEED_WIN_RATES = {
    1: 0.993, 2: 0.943, 3: 0.855, 4: 0.800,
    5: 0.645, 6: 0.625, 7: 0.605, 8: 0.500,
    9: 0.500, 10: 0.395, 11: 0.375, 12: 0.355,
    13: 0.200, 14: 0.145, 15: 0.057, 16: 0.007,
}

# Full 2026 first-round bracket (from Selection Sunday)
# Adjacent pairs play each other in the next round.
BRACKET = [
    # EAST (games 0-7)
    {"region": "East", "higher_seed": {"seed": 1, "team": "Duke"}, "lower_seed": {"seed": 16, "team": "Siena"}},
    {"region": "East", "higher_seed": {"seed": 8, "team": "Ohio State"}, "lower_seed": {"seed": 9, "team": "TCU"}},
    {"region": "East", "higher_seed": {"seed": 5, "team": "St. John's"}, "lower_seed": {"seed": 12, "team": "Northern Iowa"}},
    {"region": "East", "higher_seed": {"seed": 4, "team": "Kansas"}, "lower_seed": {"seed": 13, "team": "Cal Baptist"}},
    {"region": "East", "higher_seed": {"seed": 6, "team": "Louisville"}, "lower_seed": {"seed": 11, "team": "South Florida"}},
    {"region": "East", "higher_seed": {"seed": 3, "team": "Michigan State"}, "lower_seed": {"seed": 14, "team": "North Dakota State"}},
    {"region": "East", "higher_seed": {"seed": 7, "team": "UCLA"}, "lower_seed": {"seed": 10, "team": "UCF"}},
    {"region": "East", "higher_seed": {"seed": 2, "team": "UConn"}, "lower_seed": {"seed": 15, "team": "Furman"}},
    # WEST (games 8-15)
    {"region": "West", "higher_seed": {"seed": 1, "team": "Arizona"}, "lower_seed": {"seed": 16, "team": "LIU"}},
    {"region": "West", "higher_seed": {"seed": 8, "team": "Villanova"}, "lower_seed": {"seed": 9, "team": "Utah State"}},
    {"region": "West", "higher_seed": {"seed": 5, "team": "Wisconsin"}, "lower_seed": {"seed": 12, "team": "High Point"}},
    {"region": "West", "higher_seed": {"seed": 4, "team": "Arkansas"}, "lower_seed": {"seed": 13, "team": "Hawaii"}},
    {"region": "West", "higher_seed": {"seed": 6, "team": "BYU"}, "lower_seed": {"seed": 11, "team": "Texas"}},
    {"region": "West", "higher_seed": {"seed": 3, "team": "Gonzaga"}, "lower_seed": {"seed": 14, "team": "Kennesaw State"}},
    {"region": "West", "higher_seed": {"seed": 7, "team": "Miami (FL)"}, "lower_seed": {"seed": 10, "team": "Missouri"}},
    {"region": "West", "higher_seed": {"seed": 2, "team": "Purdue"}, "lower_seed": {"seed": 15, "team": "Queens"}},
    # SOUTH (games 16-23)
    {"region": "South", "higher_seed": {"seed": 1, "team": "Florida"}, "lower_seed": {"seed": 16, "team": "Prairie View A&M"}},
    {"region": "South", "higher_seed": {"seed": 8, "team": "Clemson"}, "lower_seed": {"seed": 9, "team": "Iowa"}},
    {"region": "South", "higher_seed": {"seed": 5, "team": "Vanderbilt"}, "lower_seed": {"seed": 12, "team": "McNeese"}},
    {"region": "South", "higher_seed": {"seed": 4, "team": "Nebraska"}, "lower_seed": {"seed": 13, "team": "Troy"}},
    {"region": "South", "higher_seed": {"seed": 6, "team": "North Carolina"}, "lower_seed": {"seed": 11, "team": "VCU"}},
    {"region": "South", "higher_seed": {"seed": 3, "team": "Illinois"}, "lower_seed": {"seed": 14, "team": "Penn"}},
    {"region": "South", "higher_seed": {"seed": 7, "team": "Saint Mary's"}, "lower_seed": {"seed": 10, "team": "Texas A&M"}},
    {"region": "South", "higher_seed": {"seed": 2, "team": "Houston"}, "lower_seed": {"seed": 15, "team": "Idaho"}},
    # MIDWEST (games 24-31)
    {"region": "Midwest", "higher_seed": {"seed": 1, "team": "Michigan"}, "lower_seed": {"seed": 16, "team": "UMBC"}},
    {"region": "Midwest", "higher_seed": {"seed": 8, "team": "Georgia"}, "lower_seed": {"seed": 9, "team": "Saint Louis"}},
    {"region": "Midwest", "higher_seed": {"seed": 5, "team": "Texas Tech"}, "lower_seed": {"seed": 12, "team": "Akron"}},
    {"region": "Midwest", "higher_seed": {"seed": 4, "team": "Alabama"}, "lower_seed": {"seed": 13, "team": "Hofstra"}},
    {"region": "Midwest", "higher_seed": {"seed": 6, "team": "Tennessee"}, "lower_seed": {"seed": 11, "team": "SMU"}},
    {"region": "Midwest", "higher_seed": {"seed": 3, "team": "Virginia"}, "lower_seed": {"seed": 14, "team": "Wright State"}},
    {"region": "Midwest", "higher_seed": {"seed": 7, "team": "Kentucky"}, "lower_seed": {"seed": 10, "team": "Santa Clara"}},
    {"region": "Midwest", "higher_seed": {"seed": 2, "team": "Iowa State"}, "lower_seed": {"seed": 15, "team": "Tennessee State"}},
]

FINAL_FOUR_PAIRS = [("East", "West"), ("South", "Midwest")]

TEAM_ALIASES = {
    "Cal Baptist": "California Baptist",
    "North Dakota State": "North Dakota St.",
    "Michigan State": "Michigan St.",
    "Ohio State": "Ohio St.",
    "Utah State": "Utah St.",
    "Iowa State": "Iowa St.",
    "Kennesaw State": "Kennesaw St.",
    "Tennessee State": "Tennessee St.",
    "Wright State": "Wright St.",
    "Hawaii": "Hawai'i",
    "NC State": "North Carolina St.",
}


def load_kalshi_odds() -> dict[str, float]:
    with open(KALSHI_FILE) as f:
        data = json.load(f)
    odds = {}
    for m in data["KXMARMAD"]:
        title = m.get("title", "")
        team = title.replace("Will ", "").replace(" win the College Basketball National Championship?", "")
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        lp = float(m.get("last_price_dollars", "0") or "0")
        if yb > 0 and ya > 0:
            prob = (yb + ya) / 2
        elif lp > 0:
            prob = lp
        else:
            prob = 0.005
        odds[team] = prob
    return odds


def lookup_kalshi(team: str, odds: dict[str, float]) -> float:
    if team in odds:
        return odds[team]
    alias = TEAM_ALIASES.get(team)
    if alias and alias in odds:
        return odds[alias]
    for kalshi_name, prob in odds.items():
        if team.lower() in kalshi_name.lower() or kalshi_name.lower() in team.lower():
            return prob
    return 0.003


def has_market_signal(team_a: dict, team_b: dict, kalshi_odds: dict[str, float]) -> bool:
    """True if at least one team has championship odds above the floor threshold."""
    champ_a = lookup_kalshi(team_a["team"], kalshi_odds)
    champ_b = lookup_kalshi(team_b["team"], kalshi_odds)
    return champ_a > FLOOR_THRESHOLD or champ_b > FLOOR_THRESHOLD


def derive_game_probability(team_a: dict, team_b: dict, kalshi_odds: dict[str, float]) -> float:
    """
    Derive implied win probability for team_a using Kalshi championship odds
    + seed-based priors. Only meaningful for MARKET SIGNAL games.
    """
    champ_a = lookup_kalshi(team_a["team"], kalshi_odds)
    champ_b = lookup_kalshi(team_b["team"], kalshi_odds)

    if champ_a + champ_b > 0:
        odds_ratio = champ_a / (champ_a + champ_b)
    else:
        odds_ratio = 0.5

    seed_a = team_a["seed"]
    seed_b = team_b["seed"]
    if seed_a < seed_b:
        seed_prior = SEED_WIN_RATES.get(seed_a, 0.5)
    elif seed_b < seed_a:
        seed_prior = 1.0 - SEED_WIN_RATES.get(seed_b, 0.5)
    else:
        seed_prior = 0.5

    liquidity = champ_a + champ_b
    if liquidity >= 0.10:
        w_odds = 0.75
    elif liquidity >= 0.03:
        w_odds = 0.55
    elif liquidity >= 0.01:
        w_odds = 0.35
    else:
        w_odds = 0.15

    derived = w_odds * odds_ratio + (1.0 - w_odds) * seed_prior
    return max(0.01, min(0.99, derived))


def assess_game(client: anthropic.Anthropic, team_a: dict, team_b: dict,
                region: str, round_name: str) -> dict:
    """Ask Claude to assess a matchup WITHOUT seeing any odds."""
    prompt = f"""You are an expert college basketball analyst. Assess this 2026 NCAA Tournament matchup:

Round: {round_name}
Region: {region}
#{team_a["seed"]} {team_a["team"]} vs #{team_b["seed"]} {team_b["team"]}

Based on your knowledge of these teams' 2025-26 season performance, coaching, key players, style of play, tournament experience, and matchup dynamics:

1. Who wins this game?
2. What is your confidence that #{team_a["seed"]} {team_a["team"]} wins? Express as a probability between 0.01 and 0.99.
3. Brief rationale (2-3 sentences max).

IMPORTANT: Respond in EXACTLY this JSON format, nothing else:
{{"winner": "Team Name", "team_a_win_prob": 0.XX, "rationale": "Your reasoning here."}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    return json.loads(text)


def resolve_matchup(team_a: dict, team_b: dict, market_prob: float | None,
                    claude_prob: float, assessment: dict, region: str,
                    game_num: int, signal_mode: str) -> dict:
    """Compute pick for a single game. Handles both MARKET SIGNAL and CLAUDE ONLY modes."""

    if signal_mode == "CLAUDE_ONLY":
        # No market signal — Claude's assessment is the entire pick
        if claude_prob >= 0.50:
            pick = team_a["team"]
            pick_seed = team_a["seed"]
        else:
            pick = team_b["team"]
            pick_seed = team_b["seed"]

        # Conviction = how far from 50/50 Claude is
        conviction = abs(claude_prob - 0.50)
        if conviction >= 0.25:
            conviction_label = "HIGH"
        elif conviction >= 0.12:
            conviction_label = "MED"
        else:
            conviction_label = "LOW"

        return {
            "game": game_num,
            "region": region,
            "matchup": f"({team_a['seed']}) {team_a['team']} vs ({team_b['seed']}) {team_b['team']}",
            "team_a": team_a,
            "team_b": team_b,
            "market_prob": None,
            "claude_prob": round(claude_prob, 3),
            "divergence": None,
            "abs_divergence": None,
            "pick": pick,
            "pick_seed": pick_seed,
            "pick_source": "CLAUDE_ONLY",
            "conviction": round(conviction, 3),
            "conviction_label": conviction_label,
            "pick_rationale": f"No market signal — Claude conviction pick ({conviction_label})",
            "claude_rationale": assessment["rationale"],
        }

    # MARKET SIGNAL mode — divergence logic
    divergence = claude_prob - market_prob
    abs_div = abs(divergence)

    if abs_div >= SIGNIFICANT_DIVERGENCE:
        if divergence > 0:
            pick = team_a["team"]
            pick_seed = team_a["seed"]
            rationale_prefix = f"Claude likes {team_a['team']} MORE than market"
        else:
            pick = team_b["team"]
            pick_seed = team_b["seed"]
            rationale_prefix = f"Claude likes {team_b['team']} MORE than market"
        pick_source = "DIVERGE"
    else:
        if market_prob >= 0.50:
            pick = team_a["team"]
            pick_seed = team_a["seed"]
        else:
            pick = team_b["team"]
            pick_seed = team_b["seed"]
        pick_source = "CHALK"
        rationale_prefix = "Market and Claude aligned"

    return {
        "game": game_num,
        "region": region,
        "matchup": f"({team_a['seed']}) {team_a['team']} vs ({team_b['seed']}) {team_b['team']}",
        "team_a": team_a,
        "team_b": team_b,
        "market_prob": round(market_prob, 3),
        "claude_prob": round(claude_prob, 3),
        "divergence": round(divergence, 3),
        "abs_divergence": round(abs_div, 3),
        "pick": pick,
        "pick_seed": pick_seed,
        "pick_source": pick_source,
        "conviction": None,
        "conviction_label": None,
        "pick_rationale": rationale_prefix,
        "claude_rationale": assessment["rationale"],
    }


def print_round_results(results: list[dict], round_name: str):
    """Print round results split into MARKET SIGNAL and CLAUDE ONLY sections."""
    market_games = [r for r in results if r["pick_source"] in ("CHALK", "DIVERGE")]
    claude_games = [r for r in results if r["pick_source"] == "CLAUDE_ONLY"]

    # --- MARKET SIGNAL section ---
    if market_games:
        sorted_market = sorted(market_games, key=lambda r: r["abs_divergence"], reverse=True)
        print(f"\n{'=' * 120}")
        print(f" {round_name.upper()} — MARKET SIGNAL ({len(market_games)} games with Kalshi spread)")
        print(f"{'=' * 120}")
        print(f" {'#':<4} {'Region':<10} {'Matchup':<44} {'Market':>7} {'Claude':>7} {'Gap':>7}  {'Pick':<22} {'Source':<8}")
        print("-" * 120)
        for r in sorted_market:
            div_str = f"{r['divergence']:+.0%}"
            flag = ""
            if r["abs_divergence"] >= STRONG_DIVERGENCE:
                flag = " <<<"
            elif r["abs_divergence"] >= SIGNIFICANT_DIVERGENCE:
                flag = " <"
            print(
                f" {r['game']:<4} "
                f"{r['region']:<10} "
                f"{r['matchup']:<44} "
                f"{r['market_prob']:>6.0%} "
                f"{r['claude_prob']:>6.0%} "
                f"{div_str:>7}  "
                f"{r['pick']:<22} "
                f"{r['pick_source']:<8}"
                f"{flag}"
            )
        print("-" * 120)

    # --- CLAUDE ONLY section ---
    if claude_games:
        sorted_claude = sorted(claude_games, key=lambda r: r["conviction"], reverse=True)
        print(f"\n{'=' * 120}")
        print(f" {round_name.upper()} — CLAUDE ONLY ({len(claude_games)} games, no market signal — flying blind)")
        print(f"{'=' * 120}")
        print(f" {'#':<4} {'Region':<10} {'Matchup':<44} {'Claude':>7} {'Conv':>6}  {'Pick':<22} {'Conf':<5}")
        print("-" * 120)
        for r in sorted_claude:
            print(
                f" {r['game']:<4} "
                f"{r['region']:<10} "
                f"{r['matchup']:<44} "
                f"{r['claude_prob']:>6.0%} "
                f"{r['conviction']:>5.0%}  "
                f"{r['pick']:<22} "
                f"{r['conviction_label']:<5}"
            )
        print("-" * 120)


def print_round_picks(results: list[dict], round_name: str):
    print(f"\n  {round_name.upper()} PICKS:")

    regions = {}
    for r in results:
        regions.setdefault(r["region"], []).append(r)

    for region in ["East", "West", "South", "Midwest", "Final Four", "Championship"]:
        if region not in regions:
            continue
        if round_name not in ("Final Four", "Championship"):
            print(f"    {region}:")
        for r in sorted(regions[region], key=lambda x: x["game"]):
            source = r["pick_source"]
            if source == "CLAUDE_ONLY":
                tag = f"[CLAUDE {r['conviction_label']}]"
            elif source == "DIVERGE":
                tag = f"[DIVERGE]"
            else:
                tag = f"[CHALK]"
            marker = " *" if source in ("DIVERGE", "CLAUDE_ONLY") else ""
            print(f"      {r['matchup']:<44} -> {r['pick']:<20} {tag}{marker}")
            if source == "DIVERGE":
                print(f"        {r['pick_rationale']} (gap: {r['abs_divergence']:.0%})")
                print(f"        Claude: {r['claude_rationale']}")
            elif source == "CLAUDE_ONLY":
                print(f"        No market signal — Claude conviction: {r['conviction']:.0%} ({r['conviction_label']})")
                print(f"        Claude: {r['claude_rationale']}")


def run_round(client: anthropic.Anthropic, matchups: list[dict], kalshi_odds: dict,
              round_name: str, game_start: int) -> list[dict]:
    """Run a complete round: classify signal mode, assess with Claude, resolve picks."""
    print(f"\n{'#' * 120}")
    print(f"#  {round_name.upper()}")
    print(f"{'#' * 120}")

    results = []
    for i, m in enumerate(matchups):
        team_a = m["team_a"]
        team_b = m["team_b"]
        region = m["region"]

        signal = has_market_signal(team_a, team_b, kalshi_odds)
        market_prob = derive_game_probability(team_a, team_b, kalshi_odds) if signal else None
        signal_tag = "MKT" if signal else "CLO"

        label = f"({team_a['seed']}) {team_a['team']} vs ({team_b['seed']}) {team_b['team']}"
        mkt_str = f"mkt:{market_prob:.0%}" if market_prob is not None else "mkt:---"
        print(f"  [{i+1:>2}/{len(matchups)}] [{signal_tag}] {label:<48}", end="", flush=True)

        try:
            assessment = assess_game(client, team_a, team_b, region, round_name)
            claude_prob = assessment["team_a_win_prob"]
            winner = assessment["winner"]
            arrow = "->" if winner == team_a["team"] else "<-"
            print(f" {arrow} {winner:<20} ({mkt_str} cld:{claude_prob:.0%})")
        except Exception as e:
            print(f" ERROR: {e}")
            if signal:
                assessment = {
                    "winner": team_a["team"] if market_prob >= 0.5 else team_b["team"],
                    "team_a_win_prob": market_prob,
                    "rationale": "Assessment failed; defaulting to market.",
                }
                claude_prob = market_prob
            else:
                # No market, no Claude — fall back to seed
                seed_prior = SEED_WIN_RATES.get(team_a["seed"], 0.5)
                assessment = {
                    "winner": team_a["team"] if seed_prior >= 0.5 else team_b["team"],
                    "team_a_win_prob": seed_prior,
                    "rationale": "Assessment failed; defaulting to seed-based prior.",
                }
                claude_prob = seed_prior

        signal_mode = "MARKET_SIGNAL" if signal else "CLAUDE_ONLY"
        result = resolve_matchup(
            team_a, team_b, market_prob, claude_prob, assessment,
            region, game_start + i, signal_mode,
        )
        results.append(result)

        if i < len(matchups) - 1:
            time.sleep(0.3)

    print_round_results(results, round_name)
    print_round_picks(results, round_name)
    return results


def build_next_round(results: list[dict], round_size: int) -> list[dict]:
    next_matchups = []

    if round_size == 4:
        region_winners = {}
        for r in results:
            region_winners[r["region"]] = r
        for region_a, region_b in FINAL_FOUR_PAIRS:
            ra = region_winners[region_a]
            rb = region_winners[region_b]
            winner_a = ra["team_a"] if ra["pick"] == ra["team_a"]["team"] else ra["team_b"]
            winner_b = rb["team_a"] if rb["pick"] == rb["team_a"]["team"] else rb["team_b"]
            if winner_a["seed"] <= winner_b["seed"]:
                next_matchups.append({"team_a": winner_a, "team_b": winner_b, "region": "Final Four"})
            else:
                next_matchups.append({"team_a": winner_b, "team_b": winner_a, "region": "Final Four"})
        return next_matchups

    if round_size == 2:
        r0, r1 = results[0], results[1]
        w0 = r0["team_a"] if r0["pick"] == r0["team_a"]["team"] else r0["team_b"]
        w1 = r1["team_a"] if r1["pick"] == r1["team_a"]["team"] else r1["team_b"]
        if w0["seed"] <= w1["seed"]:
            next_matchups.append({"team_a": w0, "team_b": w1, "region": "Championship"})
        else:
            next_matchups.append({"team_a": w1, "team_b": w0, "region": "Championship"})
        return next_matchups

    for i in range(0, len(results), 2):
        r1 = results[i]
        r2 = results[i + 1]
        winner1 = r1["team_a"] if r1["pick"] == r1["team_a"]["team"] else r1["team_b"]
        winner2 = r2["team_a"] if r2["pick"] == r2["team_a"]["team"] else r2["team_b"]
        region = r1["region"]
        if winner1["seed"] <= winner2["seed"]:
            next_matchups.append({"team_a": winner1, "team_b": winner2, "region": region})
        else:
            next_matchups.append({"team_a": winner2, "team_b": winner1, "region": region})

    return next_matchups


def print_final_bracket(all_results: dict):
    print(f"\n{'=' * 120}")
    print(f"{'':>40}  FULL BRACKET PICKS")
    print(f"{'=' * 120}")

    for round_size in [64, 32, 16, 8, 4, 2]:
        round_name = ROUND_NAMES[round_size]
        results = all_results.get(round_size, [])
        if not results:
            continue

        print(f"\n  {'─' * 116}")
        print(f"  {round_name.upper()}")
        print(f"  {'─' * 116}")

        for r in results:
            source = r["pick_source"]
            region_tag = f"[{r['region']:<10}]" if r['region'] not in ("Final Four", "Championship") else f"[{r['region']}]"

            if source == "CLAUDE_ONLY":
                extra = f" (Claude {r['conviction_label']}, conv:{r['conviction']:.0%})"
                marker = " ~"
            elif source == "DIVERGE":
                extra = f" (gap:{r['abs_divergence']:.0%})"
                marker = " *"
            else:
                extra = ""
                marker = ""

            print(f"    {region_tag} {r['matchup']:<44} -> {r['pick']:<20} [{source}]{marker}{extra}")

    # Grand summary
    all_flat = [r for rr in all_results.values() for r in rr]
    market_signal = [r for r in all_flat if r["pick_source"] in ("CHALK", "DIVERGE")]
    claude_only = [r for r in all_flat if r["pick_source"] == "CLAUDE_ONLY"]
    diverge = [r for r in all_flat if r["pick_source"] == "DIVERGE"]
    chalk = [r for r in all_flat if r["pick_source"] == "CHALK"]

    champ = all_results.get(2, [{}])[0] if 2 in all_results else None

    print(f"\n{'=' * 120}")
    print(f"  TOURNAMENT SUMMARY")
    print(f"{'=' * 120}")
    print(f"   Total games:          {len(all_flat)}")
    print(f"   ─────────────────────────────────────")
    print(f"   MARKET SIGNAL games:  {len(market_signal)}")
    print(f"     Chalk picks:        {len(chalk)}")
    print(f"     Divergence picks:   {len(diverge)}")
    if diverge:
        avg = sum(r["abs_divergence"] for r in diverge) / len(diverge)
        biggest = max(diverge, key=lambda r: r["abs_divergence"])
        print(f"     Avg divergence:     {avg:.1%}")
        print(f"     Biggest gap:        {biggest['matchup']} ({biggest['abs_divergence']:.0%})")
    print(f"   ─────────────────────────────────────")
    print(f"   CLAUDE ONLY games:    {len(claude_only)}  (no market signal)")
    if claude_only:
        high = [r for r in claude_only if r["conviction_label"] == "HIGH"]
        med = [r for r in claude_only if r["conviction_label"] == "MED"]
        low = [r for r in claude_only if r["conviction_label"] == "LOW"]
        avg_conv = sum(r["conviction"] for r in claude_only) / len(claude_only)
        print(f"     HIGH conviction:    {len(high)}")
        print(f"     MED conviction:     {len(med)}")
        print(f"     LOW conviction:     {len(low)}")
        print(f"     Avg conviction:     {avg_conv:.0%}")

    if champ:
        print(f"\n   {'=' * 37}")
        print(f"   CHAMPION:  {champ['pick']}")
        source = champ["pick_source"]
        if source == "CLAUDE_ONLY":
            print(f"   Source:    [CLAUDE ONLY — {champ['conviction_label']} conviction]")
        else:
            print(f"   Source:    [{source}]")
        print(f"   Rationale: {champ['claude_rationale']}")

    e8 = all_results.get(8, [])
    if e8:
        print(f"\n   FINAL FOUR:")
        for r in e8:
            src = "~" if r["pick_source"] == "CLAUDE_ONLY" else "*" if r["pick_source"] == "DIVERGE" else " "
            print(f"     {r['region']:<10} -> {r['pick']} {src}")

    print()


def main():
    print("Loading Kalshi championship odds...")
    kalshi_odds = load_kalshi_odds()
    print(f"  Found {len(kalshi_odds)} teams with championship prices\n")

    client = anthropic.Anthropic()
    all_results = {}
    game_counter = 1

    r64_matchups = []
    for m in BRACKET:
        r64_matchups.append({
            "team_a": m["higher_seed"],
            "team_b": m["lower_seed"],
            "region": m["region"],
        })

    current_matchups = r64_matchups
    for round_size in [64, 32, 16, 8, 4, 2]:
        round_name = ROUND_NAMES[round_size]
        expected_games = round_size // 2

        if len(current_matchups) != expected_games:
            print(f"\nERROR: Expected {expected_games} games for {round_name}, got {len(current_matchups)}")
            break

        results = run_round(client, current_matchups, kalshi_odds, round_name, game_counter)
        all_results[round_size] = results
        game_counter += len(results)

        if round_size > 2:
            next_size = round_size // 2
            current_matchups = build_next_round(results, next_size)

    print_final_bracket(all_results)

    output_file = ROOT / "results.json"
    serializable = {}
    for k, v in all_results.items():
        serializable[str(k)] = v
    with open(output_file, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"Full results saved to {output_file}\n")


if __name__ == "__main__":
    main()
