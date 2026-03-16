#!/usr/bin/env python3
"""
Bracket Divergence: Use Kalshi odds + Claude's blind assessment to find
divergence and make picks — ALL ROUNDS.

Market signal priority:
  1. KXNCAAMBGAME — direct per-game H2H winner contracts (best signal)
  2. KXMARMAD — championship odds derived into H2H (fallback)
  3. No signal — Claude's assessment is the pick

Also loads prop/futures markets (seed upset, upset totals, player points)
for cross-validation context.

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

# Divergence thresholds (percentage points)
SIGNIFICANT_DIVERGENCE = 0.08  # 8pp
STRONG_DIVERGENCE = 0.15       # 15pp

# Championship odds at or below this = no meaningful signal for derivation
FLOOR_THRESHOLD = 0.012

ROUND_NAMES = {
    64: "Round of 64",
    32: "Round of 32",
    16: "Sweet 16",
    8: "Elite 8",
    4: "Final Four",
    2: "Championship",
}

SEED_WIN_RATES = {
    1: 0.993, 2: 0.943, 3: 0.855, 4: 0.800,
    5: 0.645, 6: 0.625, 7: 0.605, 8: 0.500,
    9: 0.500, 10: 0.395, 11: 0.375, 12: 0.355,
    13: 0.200, 14: 0.145, 15: 0.057, 16: 0.007,
}

BRACKET = [
    # EAST
    {"region": "East", "higher_seed": {"seed": 1, "team": "Duke"}, "lower_seed": {"seed": 16, "team": "Siena"}},
    {"region": "East", "higher_seed": {"seed": 8, "team": "Ohio State"}, "lower_seed": {"seed": 9, "team": "TCU"}},
    {"region": "East", "higher_seed": {"seed": 5, "team": "St. John's"}, "lower_seed": {"seed": 12, "team": "Northern Iowa"}},
    {"region": "East", "higher_seed": {"seed": 4, "team": "Kansas"}, "lower_seed": {"seed": 13, "team": "Cal Baptist"}},
    {"region": "East", "higher_seed": {"seed": 6, "team": "Louisville"}, "lower_seed": {"seed": 11, "team": "South Florida"}},
    {"region": "East", "higher_seed": {"seed": 3, "team": "Michigan State"}, "lower_seed": {"seed": 14, "team": "North Dakota State"}},
    {"region": "East", "higher_seed": {"seed": 7, "team": "UCLA"}, "lower_seed": {"seed": 10, "team": "UCF"}},
    {"region": "East", "higher_seed": {"seed": 2, "team": "UConn"}, "lower_seed": {"seed": 15, "team": "Furman"}},
    # WEST
    {"region": "West", "higher_seed": {"seed": 1, "team": "Arizona"}, "lower_seed": {"seed": 16, "team": "LIU"}},
    {"region": "West", "higher_seed": {"seed": 8, "team": "Villanova"}, "lower_seed": {"seed": 9, "team": "Utah State"}},
    {"region": "West", "higher_seed": {"seed": 5, "team": "Wisconsin"}, "lower_seed": {"seed": 12, "team": "High Point"}},
    {"region": "West", "higher_seed": {"seed": 4, "team": "Arkansas"}, "lower_seed": {"seed": 13, "team": "Hawaii"}},
    {"region": "West", "higher_seed": {"seed": 6, "team": "BYU"}, "lower_seed": {"seed": 11, "team": "Texas"}},
    {"region": "West", "higher_seed": {"seed": 3, "team": "Gonzaga"}, "lower_seed": {"seed": 14, "team": "Kennesaw State"}},
    {"region": "West", "higher_seed": {"seed": 7, "team": "Miami (FL)"}, "lower_seed": {"seed": 10, "team": "Missouri"}},
    {"region": "West", "higher_seed": {"seed": 2, "team": "Purdue"}, "lower_seed": {"seed": 15, "team": "Queens"}},
    # SOUTH
    {"region": "South", "higher_seed": {"seed": 1, "team": "Florida"}, "lower_seed": {"seed": 16, "team": "Prairie View A&M"}},
    {"region": "South", "higher_seed": {"seed": 8, "team": "Clemson"}, "lower_seed": {"seed": 9, "team": "Iowa"}},
    {"region": "South", "higher_seed": {"seed": 5, "team": "Vanderbilt"}, "lower_seed": {"seed": 12, "team": "McNeese"}},
    {"region": "South", "higher_seed": {"seed": 4, "team": "Nebraska"}, "lower_seed": {"seed": 13, "team": "Troy"}},
    {"region": "South", "higher_seed": {"seed": 6, "team": "North Carolina"}, "lower_seed": {"seed": 11, "team": "VCU"}},
    {"region": "South", "higher_seed": {"seed": 3, "team": "Illinois"}, "lower_seed": {"seed": 14, "team": "Penn"}},
    {"region": "South", "higher_seed": {"seed": 7, "team": "Saint Mary's"}, "lower_seed": {"seed": 10, "team": "Texas A&M"}},
    {"region": "South", "higher_seed": {"seed": 2, "team": "Houston"}, "lower_seed": {"seed": 15, "team": "Idaho"}},
    # MIDWEST
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

# Maps bracket team names -> Kalshi abbreviations and championship names
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

# Maps bracket team names -> KXNCAAMBGAME abbreviations
GAME_ABBREV_MAP = {
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


# ─── DATA LOADING ───────────────────────────────────────────────────────────

def load_all_kalshi() -> dict:
    """Load all Kalshi data from kalshi_markets.json."""
    with open(KALSHI_FILE) as f:
        return json.load(f)


def build_game_odds(raw: dict) -> dict[str, float]:
    """Build {team_abbrev: win_prob} from KXNCAAMBGAME markets.

    Returns a dict keyed by team abbreviation (e.g. "DUKE": 0.995)
    for all active/open game winner contracts.
    """
    odds = {}
    for m in raw.get("KXNCAAMBGAME", []):
        status = m.get("status", "")
        if status not in ("active", "open"):
            continue
        ticker = m.get("ticker", "")
        abbrev = ticker.rsplit("-", 1)[-1] if "-" in ticker else ""
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        lp = float(m.get("last_price_dollars", "0") or "0")
        if yb > 0 and ya > 0:
            odds[abbrev] = (yb + ya) / 2
        elif lp > 0:
            odds[abbrev] = lp
    return odds


def build_champ_odds(raw: dict) -> dict[str, float]:
    """Build {team_name: champ_prob} from KXMARMAD markets (championship only)."""
    odds = {}
    for m in raw.get("KXMARMAD", []):
        title = m.get("title", "")
        if "National Championship" not in title:
            continue
        team = title.replace("Will ", "").replace(
            " win the College Basketball National Championship?", "")
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        lp = float(m.get("last_price_dollars", "0") or "0")
        if yb > 0 and ya > 0:
            odds[team] = (yb + ya) / 2
        elif lp > 0:
            odds[team] = lp
        else:
            odds[team] = 0.005
    return odds


def build_props_summary(raw: dict) -> dict:
    """Extract key prop signals for context display."""
    props = {}

    # Upset totals
    for m in raw.get("KXMARMADUPSET", []):
        title = m.get("title", "")
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        if yb > 0 and ya > 0:
            props[title] = round((yb + ya) / 2, 3)

    # Seed props
    for m in raw.get("KXMARMADSEEDWIN", []):
        title = m.get("title", "")
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        if yb > 0 and ya > 0:
            props[title] = round((yb + ya) / 2, 3)

    # Player points
    for m in raw.get("KXMARMADPTS", []):
        title = m.get("title", "")
        yb = float(m.get("yes_bid_dollars", "0") or "0")
        ya = float(m.get("yes_ask_dollars", "0") or "0")
        if yb > 0 and ya > 0:
            props[title] = round((yb + ya) / 2, 3)

    return props


# ─── MARKET SIGNAL RESOLUTION ───────────────────────────────────────────────

def lookup_champ(team: str, champ_odds: dict[str, float]) -> float:
    if team in champ_odds:
        return champ_odds[team]
    alias = TEAM_ALIASES.get(team)
    if alias and alias in champ_odds:
        return champ_odds[alias]
    for name, prob in champ_odds.items():
        if team.lower() in name.lower() or name.lower() in team.lower():
            return prob
    return 0.003


def get_game_market_prob(team_a: dict, team_b: dict, game_odds: dict) -> float | None:
    """Look up direct H2H probability from KXNCAAMBGAME for team_a winning.

    Returns None if no game market exists for this matchup.
    """
    abbrev_a = GAME_ABBREV_MAP.get(team_a["team"])
    abbrev_b = GAME_ABBREV_MAP.get(team_b["team"])

    if abbrev_a and abbrev_a in game_odds:
        return game_odds[abbrev_a]
    # If we found team_b but not team_a, invert
    if abbrev_b and abbrev_b in game_odds:
        return 1.0 - game_odds[abbrev_b]
    return None


def derive_from_championship(team_a: dict, team_b: dict, champ_odds: dict) -> float:
    """Derive H2H probability from championship odds + seed priors."""
    ca = lookup_champ(team_a["team"], champ_odds)
    cb = lookup_champ(team_b["team"], champ_odds)

    odds_ratio = ca / (ca + cb) if (ca + cb) > 0 else 0.5

    seed_a, seed_b = team_a["seed"], team_b["seed"]
    if seed_a < seed_b:
        seed_prior = SEED_WIN_RATES.get(seed_a, 0.5)
    elif seed_b < seed_a:
        seed_prior = 1.0 - SEED_WIN_RATES.get(seed_b, 0.5)
    else:
        seed_prior = 0.5

    liquidity = ca + cb
    if liquidity >= 0.10:
        w = 0.75
    elif liquidity >= 0.03:
        w = 0.55
    elif liquidity >= 0.01:
        w = 0.35
    else:
        w = 0.15

    return max(0.01, min(0.99, w * odds_ratio + (1.0 - w) * seed_prior))


def resolve_market_signal(team_a: dict, team_b: dict,
                          game_odds: dict, champ_odds: dict) -> tuple[float | None, str]:
    """Determine market probability and signal source for a matchup.

    Returns (market_prob_for_team_a, signal_source).
    signal_source is one of: "GAME_MARKET", "DERIVED", "NONE"
    """
    # Priority 1: Direct per-game H2H market
    game_prob = get_game_market_prob(team_a, team_b, game_odds)
    if game_prob is not None:
        return game_prob, "GAME_MARKET"

    # Priority 2: Derived from championship odds (if meaningful spread)
    ca = lookup_champ(team_a["team"], champ_odds)
    cb = lookup_champ(team_b["team"], champ_odds)
    if ca > FLOOR_THRESHOLD or cb > FLOOR_THRESHOLD:
        derived = derive_from_championship(team_a, team_b, champ_odds)
        return derived, "DERIVED"

    # No signal
    return None, "NONE"


# ─── CLAUDE ASSESSMENT ──────────────────────────────────────────────────────

def assess_game(client: anthropic.Anthropic, team_a: dict, team_b: dict,
                region: str, round_name: str) -> dict:
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


# ─── PICK RESOLUTION ────────────────────────────────────────────────────────

def resolve_matchup(team_a: dict, team_b: dict, market_prob: float | None,
                    claude_prob: float, assessment: dict, region: str,
                    game_num: int, signal_source: str) -> dict:

    if signal_source == "NONE":
        if claude_prob >= 0.50:
            pick, pick_seed = team_a["team"], team_a["seed"]
        else:
            pick, pick_seed = team_b["team"], team_b["seed"]
        conviction = abs(claude_prob - 0.50)
        conv_label = "HIGH" if conviction >= 0.25 else "MED" if conviction >= 0.12 else "LOW"
        return {
            "game": game_num, "region": region,
            "matchup": f"({team_a['seed']}) {team_a['team']} vs ({team_b['seed']}) {team_b['team']}",
            "team_a": team_a, "team_b": team_b,
            "market_prob": None, "claude_prob": round(claude_prob, 3),
            "divergence": None, "abs_divergence": None,
            "pick": pick, "pick_seed": pick_seed,
            "pick_source": "CLAUDE_ONLY", "signal_source": "NONE",
            "conviction": round(conviction, 3), "conviction_label": conv_label,
            "pick_rationale": f"No market signal — Claude conviction pick ({conv_label})",
            "claude_rationale": assessment["rationale"],
        }

    # MARKET SIGNAL (GAME_MARKET or DERIVED)
    divergence = claude_prob - market_prob
    abs_div = abs(divergence)

    if abs_div >= SIGNIFICANT_DIVERGENCE:
        if divergence > 0:
            pick, pick_seed = team_a["team"], team_a["seed"]
            prefix = f"Claude likes {team_a['team']} MORE than market"
        else:
            pick, pick_seed = team_b["team"], team_b["seed"]
            prefix = f"Claude likes {team_b['team']} MORE than market"
        pick_source = "DIVERGE"
    else:
        if market_prob >= 0.50:
            pick, pick_seed = team_a["team"], team_a["seed"]
        else:
            pick, pick_seed = team_b["team"], team_b["seed"]
        pick_source = "CHALK"
        prefix = "Market and Claude aligned"

    return {
        "game": game_num, "region": region,
        "matchup": f"({team_a['seed']}) {team_a['team']} vs ({team_b['seed']}) {team_b['team']}",
        "team_a": team_a, "team_b": team_b,
        "market_prob": round(market_prob, 3), "claude_prob": round(claude_prob, 3),
        "divergence": round(divergence, 3), "abs_divergence": round(abs_div, 3),
        "pick": pick, "pick_seed": pick_seed,
        "pick_source": pick_source, "signal_source": signal_source,
        "conviction": None, "conviction_label": None,
        "pick_rationale": prefix,
        "claude_rationale": assessment["rationale"],
    }


# ─── ROUND EXECUTION ────────────────────────────────────────────────────────

def print_round_results(results: list[dict], round_name: str):
    market_games = [r for r in results if r["pick_source"] in ("CHALK", "DIVERGE")]
    claude_games = [r for r in results if r["pick_source"] == "CLAUDE_ONLY"]

    if market_games:
        sorted_market = sorted(market_games, key=lambda r: r["abs_divergence"], reverse=True)
        print(f"\n{'=' * 125}")
        print(f" {round_name.upper()} — MARKET SIGNAL ({len(market_games)} games)")
        print(f"{'=' * 125}")
        print(f" {'#':<4} {'Region':<10} {'Matchup':<44} {'Src':<5} {'Market':>7} {'Claude':>7} {'Gap':>7}  {'Pick':<22} {'Source':<8}")
        print("-" * 125)
        for r in sorted_market:
            div_str = f"{r['divergence']:+.0%}"
            src = "GAME" if r["signal_source"] == "GAME_MARKET" else "DRVD"
            flag = ""
            if r["abs_divergence"] >= STRONG_DIVERGENCE:
                flag = " <<<"
            elif r["abs_divergence"] >= SIGNIFICANT_DIVERGENCE:
                flag = " <"
            print(
                f" {r['game']:<4} {r['region']:<10} {r['matchup']:<44} {src:<5}"
                f"{r['market_prob']:>6.0%} {r['claude_prob']:>6.0%} {div_str:>7}  "
                f"{r['pick']:<22} {r['pick_source']:<8}{flag}"
            )
        print("-" * 125)

    if claude_games:
        sorted_claude = sorted(claude_games, key=lambda r: r["conviction"], reverse=True)
        print(f"\n{'=' * 125}")
        print(f" {round_name.upper()} — CLAUDE ONLY ({len(claude_games)} games, no market signal)")
        print(f"{'=' * 125}")
        print(f" {'#':<4} {'Region':<10} {'Matchup':<44} {'Claude':>7} {'Conv':>6}  {'Pick':<22} {'Conf':<5}")
        print("-" * 125)
        for r in sorted_claude:
            print(
                f" {r['game']:<4} {r['region']:<10} {r['matchup']:<44} "
                f"{r['claude_prob']:>6.0%} {r['conviction']:>5.0%}  "
                f"{r['pick']:<22} {r['conviction_label']:<5}"
            )
        print("-" * 125)


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
            sig = r.get("signal_source", "")
            if source == "CLAUDE_ONLY":
                tag = f"[CLAUDE {r['conviction_label']}]"
            elif source == "DIVERGE":
                sig_tag = "GAME" if sig == "GAME_MARKET" else "DRVD"
                tag = f"[DIVERGE/{sig_tag}]"
            else:
                sig_tag = "GAME" if sig == "GAME_MARKET" else "DRVD"
                tag = f"[CHALK/{sig_tag}]"
            marker = " *" if source in ("DIVERGE", "CLAUDE_ONLY") else ""
            print(f"      {r['matchup']:<44} -> {r['pick']:<20} {tag}{marker}")
            if source == "DIVERGE":
                print(f"        {r['pick_rationale']} (gap: {r['abs_divergence']:.0%})")
                print(f"        Claude: {r['claude_rationale']}")
            elif source == "CLAUDE_ONLY":
                print(f"        No market signal — Claude conviction: {r['conviction']:.0%} ({r['conviction_label']})")
                print(f"        Claude: {r['claude_rationale']}")


def run_round(client: anthropic.Anthropic, matchups: list[dict],
              game_odds: dict, champ_odds: dict,
              round_name: str, game_start: int) -> list[dict]:
    print(f"\n{'#' * 125}")
    print(f"#  {round_name.upper()}")
    print(f"{'#' * 125}")

    results = []
    for i, m in enumerate(matchups):
        team_a, team_b, region = m["team_a"], m["team_b"], m["region"]

        market_prob, signal_source = resolve_market_signal(team_a, team_b, game_odds, champ_odds)
        sig_tag = {"GAME_MARKET": "GAME", "DERIVED": "DRVD", "NONE": "----"}[signal_source]
        mkt_str = f"mkt:{market_prob:.0%}" if market_prob is not None else "mkt:---"

        label = f"({team_a['seed']}) {team_a['team']} vs ({team_b['seed']}) {team_b['team']}"
        print(f"  [{i+1:>2}/{len(matchups)}] [{sig_tag}] {label:<48}", end="", flush=True)

        try:
            assessment = assess_game(client, team_a, team_b, region, round_name)
            claude_prob = assessment["team_a_win_prob"]
            winner = assessment["winner"]
            arrow = "->" if winner == team_a["team"] else "<-"
            print(f" {arrow} {winner:<20} ({mkt_str} cld:{claude_prob:.0%})")
        except Exception as e:
            print(f" ERROR: {e}")
            if market_prob is not None:
                cp = market_prob
            else:
                cp = SEED_WIN_RATES.get(team_a["seed"], 0.5)
            assessment = {
                "winner": team_a["team"] if cp >= 0.5 else team_b["team"],
                "team_a_win_prob": cp,
                "rationale": "Assessment failed; defaulting to available signal.",
            }
            claude_prob = cp

        result = resolve_matchup(
            team_a, team_b, market_prob, claude_prob, assessment,
            region, game_start + i, signal_source,
        )
        results.append(result)
        if i < len(matchups) - 1:
            time.sleep(0.3)

    print_round_results(results, round_name)
    print_round_picks(results, round_name)
    return results


# ─── BRACKET CASCADING ──────────────────────────────────────────────────────

def build_next_round(results: list[dict], round_size: int) -> list[dict]:
    next_matchups = []
    if round_size == 4:
        region_winners = {}
        for r in results:
            region_winners[r["region"]] = r
        for ra_name, rb_name in FINAL_FOUR_PAIRS:
            ra, rb = region_winners[ra_name], region_winners[rb_name]
            wa = ra["team_a"] if ra["pick"] == ra["team_a"]["team"] else ra["team_b"]
            wb = rb["team_a"] if rb["pick"] == rb["team_a"]["team"] else rb["team_b"]
            if wa["seed"] <= wb["seed"]:
                next_matchups.append({"team_a": wa, "team_b": wb, "region": "Final Four"})
            else:
                next_matchups.append({"team_a": wb, "team_b": wa, "region": "Final Four"})
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
        r1, r2 = results[i], results[i + 1]
        w1 = r1["team_a"] if r1["pick"] == r1["team_a"]["team"] else r1["team_b"]
        w2 = r2["team_a"] if r2["pick"] == r2["team_a"]["team"] else r2["team_b"]
        region = r1["region"]
        if w1["seed"] <= w2["seed"]:
            next_matchups.append({"team_a": w1, "team_b": w2, "region": region})
        else:
            next_matchups.append({"team_a": w2, "team_b": w1, "region": region})
    return next_matchups


# ─── FINAL OUTPUT ────────────────────────────────────────────────────────────

def print_final_bracket(all_results: dict, props: dict):
    print(f"\n{'=' * 125}")
    print(f"{'':>45}  FULL BRACKET PICKS")
    print(f"{'=' * 125}")

    for round_size in [64, 32, 16, 8, 4, 2]:
        round_name = ROUND_NAMES[round_size]
        results = all_results.get(round_size, [])
        if not results:
            continue
        print(f"\n  {'─' * 121}")
        print(f"  {round_name.upper()}")
        print(f"  {'─' * 121}")
        for r in results:
            source = r["pick_source"]
            sig = r.get("signal_source", "")
            if source == "CLAUDE_ONLY":
                extra = f" (Claude {r['conviction_label']}, conv:{r['conviction']:.0%})"
                marker = " ~"
            elif source == "DIVERGE":
                sig_tag = "GAME" if sig == "GAME_MARKET" else "DRVD"
                extra = f" (gap:{r['abs_divergence']:.0%}, {sig_tag})"
                marker = " *"
            else:
                sig_tag = "GAME" if sig == "GAME_MARKET" else "DRVD"
                extra = f" ({sig_tag})"
                marker = ""
            region_tag = f"[{r['region']:<10}]" if r['region'] not in ("Final Four", "Championship") else f"[{r['region']}]"
            print(f"    {region_tag} {r['matchup']:<44} -> {r['pick']:<20} [{source}]{marker}{extra}")

    # Grand summary
    all_flat = [r for rr in all_results.values() for r in rr]
    game_mkt = [r for r in all_flat if r.get("signal_source") == "GAME_MARKET"]
    derived = [r for r in all_flat if r.get("signal_source") == "DERIVED"]
    no_signal = [r for r in all_flat if r.get("signal_source") == "NONE"]
    diverge = [r for r in all_flat if r["pick_source"] == "DIVERGE"]
    chalk = [r for r in all_flat if r["pick_source"] == "CHALK"]
    claude_only = [r for r in all_flat if r["pick_source"] == "CLAUDE_ONLY"]
    champ = all_results.get(2, [{}])[0] if 2 in all_results else None

    print(f"\n{'=' * 125}")
    print(f"  TOURNAMENT SUMMARY")
    print(f"{'=' * 125}")
    print(f"   Total games:            {len(all_flat)}")
    print(f"   ─────────────────────────────────────────")
    print(f"   SIGNAL SOURCES:")
    print(f"     Game market (H2H):    {len(game_mkt)}")
    print(f"     Derived (champ odds): {len(derived)}")
    print(f"     No signal:            {len(no_signal)}")
    print(f"   ─────────────────────────────────────────")
    print(f"   PICK TYPES:")
    print(f"     Chalk:                {len(chalk)}")
    print(f"     Divergence:           {len(diverge)}")
    if diverge:
        avg = sum(r["abs_divergence"] for r in diverge) / len(diverge)
        biggest = max(diverge, key=lambda r: r["abs_divergence"])
        print(f"       Avg divergence:     {avg:.1%}")
        print(f"       Biggest gap:        {biggest['matchup']} ({biggest['abs_divergence']:.0%})")
    print(f"     Claude only:          {len(claude_only)}")
    if claude_only:
        high = sum(1 for r in claude_only if r["conviction_label"] == "HIGH")
        med = sum(1 for r in claude_only if r["conviction_label"] == "MED")
        low = sum(1 for r in claude_only if r["conviction_label"] == "LOW")
        print(f"       HIGH / MED / LOW:   {high} / {med} / {low}")

    if champ:
        print(f"\n   {'=' * 41}")
        print(f"   CHAMPION:  {champ['pick']}")
        src = champ["pick_source"]
        sig = champ.get("signal_source", "")
        if src == "CLAUDE_ONLY":
            print(f"   Source:    [CLAUDE ONLY — {champ['conviction_label']} conviction]")
        else:
            print(f"   Source:    [{src} / {sig}]")
        print(f"   Rationale: {champ['claude_rationale']}")

    e8 = all_results.get(8, [])
    if e8:
        print(f"\n   FINAL FOUR:")
        for r in e8:
            sig = r.get("signal_source", "")
            src = "~" if r["pick_source"] == "CLAUDE_ONLY" else "*" if r["pick_source"] == "DIVERGE" else " "
            sig_tag = f"[{sig}]" if sig else ""
            print(f"     {r['region']:<10} -> {r['pick']} {src} {sig_tag}")

    # Props context
    if props:
        print(f"\n   {'=' * 41}")
        print(f"   KALSHI PROPS CONTEXT:")
        # Show key upset/seed props
        for title, prob in sorted(props.items(), key=lambda x: x[1], reverse=True):
            if prob >= 0.03:
                print(f"     {prob:>5.0%}  {title}")

    print()


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    print("Loading Kalshi markets (all series)...")
    raw = load_all_kalshi()

    game_odds = build_game_odds(raw)
    champ_odds = build_champ_odds(raw)
    props = build_props_summary(raw)

    series_counts = {k: len(v) for k, v in raw.items() if v}
    for series, count in series_counts.items():
        print(f"  {series}: {count} markets")
    print(f"  Game H2H odds loaded: {len(game_odds)} teams")
    print(f"  Championship odds loaded: {len(champ_odds)} teams")
    print(f"  Props loaded: {len(props)} signals\n")

    client = anthropic.Anthropic()
    all_results = {}
    game_counter = 1

    r64_matchups = [{"team_a": m["higher_seed"], "team_b": m["lower_seed"], "region": m["region"]}
                    for m in BRACKET]

    current_matchups = r64_matchups
    for round_size in [64, 32, 16, 8, 4, 2]:
        round_name = ROUND_NAMES[round_size]
        expected = round_size // 2
        if len(current_matchups) != expected:
            print(f"\nERROR: Expected {expected} games for {round_name}, got {len(current_matchups)}")
            break

        results = run_round(client, current_matchups, game_odds, champ_odds,
                            round_name, game_counter)
        all_results[round_size] = results
        game_counter += len(results)

        if round_size > 2:
            current_matchups = build_next_round(results, round_size // 2)

    print_final_bracket(all_results, props)

    output_file = ROOT / "results.json"
    serializable = {str(k): v for k, v in all_results.items()}
    with open(output_file, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"Full results saved to {output_file}\n")


if __name__ == "__main__":
    main()
