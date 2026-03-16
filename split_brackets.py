#!/usr/bin/env python3
"""
Generate three separate bracket files + a comparison table from results.json.

1. kalshi_bracket.json   — picks driven purely by Kalshi championship odds
2. claude_bracket.json   — picks driven purely by Claude's blind assessment
3. divergence_bracket.json — hybrid: agree within 8% = take favorite,
                              disagree >8% = take Claude, flag >15% as HIGH SIGNAL
4. comparison_table.json — every game where Kalshi and Claude picked different winners
"""

import json
from pathlib import Path

ROOT = Path(__file__).parent
RESULTS_FILE = ROOT / "results.json"

SIGNIFICANT = 0.08  # 8pp
STRONG = 0.15       # 15pp

# Bracket pairing structure — maps round of 64 game indices to bracket paths
# Adjacent games feed into next round: game 0+1 winner play, 2+3, etc.
# Final Four: East vs West, South vs Midwest
FINAL_FOUR_PAIRS = [("East", "West"), ("South", "Midwest")]

ROUND_NAMES = {
    64: "Round of 64",
    32: "Round of 32",
    16: "Sweet 16",
    8: "Elite 8",
    4: "Final Four",
    2: "Championship",
}


def load_results() -> dict:
    with open(RESULTS_FILE) as f:
        return json.load(f)


def pick_kalshi(game: dict) -> dict:
    """Pick based purely on Kalshi-derived market probability."""
    mp = game["market_prob"]
    team_a = game["team_a"]
    team_b = game["team_b"]

    if mp is None:
        # CLAUDE ONLY game — no market signal. Fall back to higher seed.
        if team_a["seed"] <= team_b["seed"]:
            pick, seed = team_a["team"], team_a["seed"]
            prob = None
        else:
            pick, seed = team_b["team"], team_b["seed"]
            prob = None
        return {"pick": pick, "seed": seed, "market_prob": prob, "source": "SEED_DEFAULT"}

    if mp >= 0.50:
        return {"pick": team_a["team"], "seed": team_a["seed"], "market_prob": round(mp, 3), "source": "KALSHI"}
    else:
        return {"pick": team_b["team"], "seed": team_b["seed"], "market_prob": round(1 - mp, 3), "source": "KALSHI"}


def pick_claude(game: dict) -> dict:
    """Pick based purely on Claude's blind assessment."""
    cp = game["claude_prob"]
    team_a = game["team_a"]
    team_b = game["team_b"]

    if cp >= 0.50:
        return {
            "pick": team_a["team"], "seed": team_a["seed"],
            "claude_prob": round(cp, 3), "source": "CLAUDE",
            "rationale": game["claude_rationale"],
        }
    else:
        return {
            "pick": team_b["team"], "seed": team_b["seed"],
            "claude_prob": round(1 - cp, 3), "source": "CLAUDE",
            "rationale": game["claude_rationale"],
        }


def pick_divergence(game: dict) -> dict:
    """Hybrid divergence pick."""
    mp = game["market_prob"]
    cp = game["claude_prob"]
    team_a = game["team_a"]
    team_b = game["team_b"]

    if mp is None:
        # No market signal — Claude is the pick
        if cp >= 0.50:
            pick, seed = team_a["team"], team_a["seed"]
        else:
            pick, seed = team_b["team"], team_b["seed"]
        conviction = abs(cp - 0.50)
        return {
            "pick": pick, "seed": seed,
            "claude_prob": round(cp, 3),
            "source": "CLAUDE_ONLY",
            "conviction": round(conviction, 3),
            "rationale": game["claude_rationale"],
        }

    divergence = cp - mp
    abs_div = abs(divergence)

    if abs_div >= SIGNIFICANT:
        # Disagreement — take Claude's pick
        if cp >= 0.50:
            pick, seed = team_a["team"], team_a["seed"]
        else:
            pick, seed = team_b["team"], team_b["seed"]

        signal = "HIGH_SIGNAL" if abs_div >= STRONG else "SIGNAL"
        return {
            "pick": pick, "seed": seed,
            "market_prob": round(mp, 3), "claude_prob": round(cp, 3),
            "divergence": round(divergence, 3),
            "source": signal,
            "rationale": game["claude_rationale"],
        }
    else:
        # Agreement — take the favorite
        if mp >= 0.50:
            pick, seed = team_a["team"], team_a["seed"]
        else:
            pick, seed = team_b["team"], team_b["seed"]
        return {
            "pick": pick, "seed": seed,
            "market_prob": round(mp, 3), "claude_prob": round(cp, 3),
            "divergence": round(divergence, 3),
            "source": "ALIGNED",
        }


def build_bracket(results: dict, pick_fn) -> dict:
    """
    Build a full bracket by cascading picks through all rounds.
    Uses Round of 64 actual assessments, then re-pairs winners for each subsequent round
    using the original assessment data to make picks.
    """
    bracket = {}
    r64 = results["64"]

    # Round of 64 — pick from actual data
    round_results = []
    for game in r64:
        p = pick_fn(game)
        round_results.append({
            "game": game["game"],
            "region": game["region"],
            "matchup": game["matchup"],
            **p,
        })
    bracket["round_of_64"] = round_results

    # For subsequent rounds, we need the original assessment data keyed by matchup
    # But later rounds depend on who won earlier rounds in THIS bracket's logic.
    # The results.json has assessments for matchups that were generated from the
    # divergence bracket's winners. We'll reuse those assessments where the matchup
    # matches, otherwise we note it.

    # Build a lookup of all assessments across all rounds
    all_games = {}
    for round_key, games in results.items():
        for g in games:
            # Key by the two team names (sorted) so we can look up regardless of ordering
            teams_key = tuple(sorted([g["team_a"]["team"], g["team_b"]["team"]]))
            all_games[teams_key] = g

    # Cascade through rounds
    prev_results = round_results
    for round_size in [32, 16, 8, 4, 2]:
        round_name = ROUND_NAMES[round_size]
        round_key = {
            32: "round_of_32", 16: "sweet_16", 8: "elite_8",
            4: "final_four", 2: "championship",
        }[round_size]

        # Pair winners
        if round_size == 4:
            # Final Four: East champ vs West champ, South champ vs Midwest champ
            region_winners = {}
            for r in prev_results:
                region_winners[r["region"]] = r
            pairings = []
            for ra_name, rb_name in FINAL_FOUR_PAIRS:
                wa = region_winners.get(ra_name)
                wb = region_winners.get(rb_name)
                if wa and wb:
                    pairings.append((wa, wb, "Final Four"))
        elif round_size == 2:
            # Championship
            if len(prev_results) == 2:
                pairings = [(prev_results[0], prev_results[1], "Championship")]
            else:
                pairings = []
        else:
            # Standard: pair adjacent winners
            pairings = []
            for i in range(0, len(prev_results), 2):
                if i + 1 < len(prev_results):
                    pairings.append((prev_results[i], prev_results[i + 1], prev_results[i]["region"]))

        round_results = []
        game_num = sum(len(bracket[k]) for k in bracket) + 1

        for wa, wb, region in pairings:
            team_a_name = wa["pick"]
            team_b_name = wb["pick"]
            seed_a = wa["seed"]
            seed_b = wb["seed"]

            # Look up if we have an assessment for this matchup
            teams_key = tuple(sorted([team_a_name, team_b_name]))
            assessed = all_games.get(teams_key)

            if assessed:
                # We have Claude's assessment for this exact matchup
                p = pick_fn(assessed)
            else:
                # This matchup didn't occur in the divergence bracket's run.
                # We don't have assessment data — pick by seed.
                if seed_a <= seed_b:
                    p = {"pick": team_a_name, "seed": seed_a, "source": "SEED_DEFAULT"}
                else:
                    p = {"pick": team_b_name, "seed": seed_b, "source": "SEED_DEFAULT"}

            # Normalize matchup string so lower seed number is first
            if seed_a <= seed_b:
                matchup = f"({seed_a}) {team_a_name} vs ({seed_b}) {team_b_name}"
            else:
                matchup = f"({seed_b}) {team_b_name} vs ({seed_a}) {team_a_name}"

            round_results.append({
                "game": game_num,
                "region": region,
                "matchup": matchup,
                **p,
            })
            game_num += 1

        bracket[round_key] = round_results
        prev_results = round_results

    return bracket


def build_comparison(kalshi: dict, claude: dict) -> list[dict]:
    """Find every game where Kalshi and Claude picked different winners."""
    disagreements = []

    for round_key in kalshi:
        k_games = {g["matchup"]: g for g in kalshi[round_key]}
        c_games = {g["matchup"]: g for g in claude[round_key]}

        for matchup in k_games:
            if matchup in c_games:
                kg = k_games[matchup]
                cg = c_games[matchup]
                if kg["pick"] != cg["pick"]:
                    entry = {
                        "round": round_key,
                        "matchup": matchup,
                        "region": kg["region"],
                        "kalshi_pick": kg["pick"],
                        "kalshi_seed": kg["seed"],
                        "claude_pick": cg["pick"],
                        "claude_seed": cg["seed"],
                    }
                    if "market_prob" in kg and kg["market_prob"] is not None:
                        entry["kalshi_prob"] = kg["market_prob"]
                    if "claude_prob" in cg:
                        entry["claude_prob"] = cg["claude_prob"]
                    if "rationale" in cg:
                        entry["claude_rationale"] = cg["rationale"]
                    disagreements.append(entry)

    return disagreements


def summarize(name: str, bracket: dict):
    """Print a one-line-per-game summary of a bracket."""
    print(f"\n{'=' * 90}")
    print(f"  {name}")
    print(f"{'=' * 90}")
    for round_key, games in bracket.items():
        label = round_key.replace("_", " ").upper()
        print(f"\n  {label}:")
        for g in games:
            src = g.get("source", "")
            extra = ""
            if "divergence" in g and g["divergence"] is not None:
                extra = f" (div:{g['divergence']:+.0%})"
            elif "conviction" in g and g["conviction"] is not None:
                extra = f" (conv:{g['conviction']:.0%})"
            print(f"    {g['matchup']:<48} -> {g['pick']:<20} [{src}]{extra}")

    # Champion
    champ_games = bracket.get("championship", [])
    if champ_games:
        print(f"\n  CHAMPION: {champ_games[0]['pick']}")


def main():
    results = load_results()

    print("Building three brackets from results.json...\n")

    kalshi_bracket = build_bracket(results, pick_kalshi)
    claude_bracket = build_bracket(results, pick_claude)
    divergence_bracket = build_bracket(results, pick_divergence)

    # Save brackets
    for name, data in [
        ("kalshi_bracket.json", kalshi_bracket),
        ("claude_bracket.json", claude_bracket),
        ("divergence_bracket.json", divergence_bracket),
    ]:
        path = ROOT / name
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        print(f"  Saved {name}")

    # Build comparison
    comparison = build_comparison(kalshi_bracket, claude_bracket)
    comp_path = ROOT / "comparison_table.json"
    with open(comp_path, "w") as f:
        json.dump(comparison, f, indent=2)
    print(f"  Saved comparison_table.json ({len(comparison)} disagreements)")

    # Print summaries
    summarize("KALSHI BRACKET (pure market odds)", kalshi_bracket)
    summarize("CLAUDE BRACKET (pure blind assessment)", claude_bracket)
    summarize("DIVERGENCE BRACKET (hybrid)", divergence_bracket)

    # Print comparison table
    print(f"\n{'=' * 90}")
    print(f"  DISAGREEMENTS: Kalshi vs Claude ({len(comparison)} games)")
    print(f"{'=' * 90}")
    print(f"  {'Round':<16} {'Matchup':<44} {'Kalshi':<15} {'Claude':<15}")
    print(f"  {'-' * 86}")
    for d in comparison:
        print(f"  {d['round']:<16} {d['matchup']:<44} {d['kalshi_pick']:<15} {d['claude_pick']:<15}")

    # Summary stats
    k_champ = kalshi_bracket["championship"][0]["pick"] if kalshi_bracket["championship"] else "?"
    c_champ = claude_bracket["championship"][0]["pick"] if claude_bracket["championship"] else "?"
    d_champ = divergence_bracket["championship"][0]["pick"] if divergence_bracket["championship"] else "?"
    print(f"\n  CHAMPIONS:")
    print(f"    Kalshi:     {k_champ}")
    print(f"    Claude:     {c_champ}")
    print(f"    Divergence: {d_champ}")
    print()


if __name__ == "__main__":
    main()
