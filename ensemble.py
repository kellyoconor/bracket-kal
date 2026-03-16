"""
Ensemble win probability model for NCAA Tournament matchups.

Three components:
  1. KenPom logistic model (base weight: 60%) — efficiency differential
  2. Log5 formula (base weight: 25%) — head-to-head from win rates
  3. Seed historical rates (base weight: 15%) — 1985-2025 tournament records

Claude provides contextual assessment that shifts the weights dynamically.
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).parent
KENPOM_FILE = ROOT / "kenpom_ratings.json"

# Base ensemble weights (shifted by Claude's contextual assessment)
BASE_WEIGHTS = {
    "kenpom": 0.60,
    "log5": 0.25,
    "seed": 0.15,
}

# Historical seed win rates in the tournament (1985-2025)
# Probability that the HIGHER seed (lower number) wins
SEED_MATCHUP_RATES = {
    # (higher_seed, lower_seed): win_rate_for_higher_seed
    (1, 16): 0.993, (2, 15): 0.943, (3, 14): 0.855, (4, 13): 0.800,
    (5, 12): 0.645, (6, 11): 0.625, (7, 10): 0.605, (8, 9): 0.500,
    # Later rounds — use average seed differential proxy
    (1, 8): 0.800, (1, 9): 0.830, (2, 7): 0.680, (2, 10): 0.720,
    (3, 6): 0.580, (3, 11): 0.680, (4, 5): 0.550, (4, 12): 0.720,
    (1, 4): 0.680, (1, 5): 0.720, (2, 3): 0.550, (2, 6): 0.640,
    (1, 2): 0.550, (1, 3): 0.600, (1, 6): 0.750, (1, 7): 0.780,
}


def load_kenpom() -> dict[str, dict]:
    """Load KenPom ratings: {team_name: {adj_o, adj_d, adj_t, rank, win_pct}}."""
    if not KENPOM_FILE.exists():
        return {}
    with open(KENPOM_FILE) as f:
        data = json.load(f)
    return data.get("teams", {})


def kenpom_logistic(team_a: dict, team_b: dict, kenpom: dict,
                    team_a_name: str, team_b_name: str) -> float | None:
    """
    KenPom logistic win probability for team_a.

    Uses the efficiency margin differential:
      margin_a = adj_o_a - adj_d_a (how much team_a outscores average opponent)
      margin_b = adj_o_b - adj_d_b

    Then applies logistic function:
      P(A wins) = 1 / (1 + 10^(-diff / scale))

    The scale factor (~11) is calibrated to match observed NCAA outcomes.
    """
    stats_a = kenpom.get(team_a_name)
    stats_b = kenpom.get(team_b_name)

    if not stats_a or not stats_b:
        return None

    adj_o_a = stats_a.get("adj_o", 0)
    adj_d_a = stats_a.get("adj_d", 0)
    adj_o_b = stats_b.get("adj_o", 0)
    adj_d_b = stats_b.get("adj_d", 0)

    # Efficiency margin: positive = better
    margin_a = adj_o_a - adj_d_a
    margin_b = adj_o_b - adj_d_b
    diff = margin_a - margin_b

    # Logistic function with scale factor
    # Scale of ~11 means a 10-point efficiency margin ≈ 86% win prob
    scale = 11.0
    prob = 1.0 / (1.0 + math.pow(10, -diff / scale))

    return max(0.01, min(0.99, prob))


def log5(team_a_name: str, team_b_name: str, kenpom: dict) -> float | None:
    """
    Log5 formula: P(A beats B) from each team's win percentage.

    P(A beats B) = (pA * (1 - pB)) / (pA * (1 - pB) + pB * (1 - pA))

    Where pA, pB are season win percentages.
    """
    stats_a = kenpom.get(team_a_name)
    stats_b = kenpom.get(team_b_name)

    if not stats_a or not stats_b:
        return None

    pa = stats_a.get("win_pct", 0.5)
    pb = stats_b.get("win_pct", 0.5)

    # Avoid division by zero
    if pa <= 0:
        pa = 0.01
    if pb <= 0:
        pb = 0.01
    if pa >= 1:
        pa = 0.99
    if pb >= 1:
        pb = 0.99

    numerator = pa * (1 - pb)
    denominator = pa * (1 - pb) + pb * (1 - pa)

    if denominator == 0:
        return 0.5

    return max(0.01, min(0.99, numerator / denominator))


def seed_historical(seed_a: int, seed_b: int) -> float:
    """
    Historical seed matchup win rate for the lower-numbered (higher) seed.

    Returns probability that seed_a wins, where seed_a <= seed_b.
    """
    if seed_a == seed_b:
        return 0.5

    # Ensure we look up (higher_seed, lower_seed)
    high = min(seed_a, seed_b)
    low = max(seed_a, seed_b)

    rate = SEED_MATCHUP_RATES.get((high, low))
    if rate is not None:
        return rate if seed_a == high else (1 - rate)

    # Fallback: estimate from seed differential
    # Larger gap = more likely the higher seed wins
    diff = low - high
    base = 0.5 + diff * 0.03  # Each seed gap ≈ 3% edge
    rate = max(0.01, min(0.99, base))
    return rate if seed_a == high else (1 - rate)


def compute_ensemble(team_a: dict, team_b: dict, kenpom: dict,
                     weight_overrides: dict | None = None) -> dict:
    """
    Compute ensemble win probability for team_a.

    Args:
        team_a: {"seed": int, "team": str}
        team_b: {"seed": int, "team": str}
        kenpom: KenPom ratings dict
        weight_overrides: Optional Claude-provided weight adjustments
            e.g. {"kenpom": 0.50, "log5": 0.30, "seed": 0.20}

    Returns:
        {
            "ensemble_prob": float,
            "kenpom_prob": float or None,
            "log5_prob": float or None,
            "seed_prob": float,
            "weights": {"kenpom": float, "log5": float, "seed": float},
            "components_used": int,
        }
    """
    name_a = team_a["team"]
    name_b = team_b["team"]
    seed_a = team_a["seed"]
    seed_b = team_b["seed"]

    # Compute each component
    kp = kenpom_logistic(team_a, team_b, kenpom, name_a, name_b)
    l5 = log5(name_a, name_b, kenpom)
    sh = seed_historical(seed_a, seed_b)

    # Determine weights
    if weight_overrides:
        weights = {**BASE_WEIGHTS, **weight_overrides}
        # Normalize to sum to 1
        total_w = sum(weights.values())
        weights = {k: v / total_w for k, v in weights.items()}
    else:
        weights = {**BASE_WEIGHTS}

    # If KenPom or Log5 unavailable, redistribute their weight to others
    available = {}
    if kp is not None:
        available["kenpom"] = kp
    if l5 is not None:
        available["log5"] = l5
    available["seed"] = sh

    if not available:
        return {
            "ensemble_prob": 0.5,
            "kenpom_prob": None, "log5_prob": None, "seed_prob": sh,
            "weights": weights, "components_used": 0,
        }

    # Redistribute missing weights
    active_weight = sum(weights[k] for k in available)
    if active_weight > 0:
        normalized = {k: weights[k] / active_weight for k in available}
    else:
        normalized = {k: 1.0 / len(available) for k in available}

    ensemble = sum(normalized[k] * available[k] for k in available)
    ensemble = max(0.01, min(0.99, ensemble))

    return {
        "ensemble_prob": round(ensemble, 4),
        "kenpom_prob": round(kp, 4) if kp is not None else None,
        "log5_prob": round(l5, 4) if l5 is not None else None,
        "seed_prob": round(sh, 4),
        "weights": {k: round(v, 3) for k, v in normalized.items()},
        "components_used": len(available),
    }
