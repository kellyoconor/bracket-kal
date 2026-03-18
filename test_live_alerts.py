#!/usr/bin/env python3
"""
Standalone test script for live_alerts.check_alerts_for_user.
Exercises each alert type with mock data and verifies de-duplication + rate limiting.
"""

import time
import sys

from live_alerts import (
    check_alerts_for_user,
    UserAlertState,
    MAX_ALERTS_PER_HOUR,
    ESPN_ABBREV_MAP,
    ABBREV_MAP,
)

PASS = 0
FAIL = 0


def report(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  — {detail}")


# ─── Helpers ──────────────────────────────────────────────────────────────

def make_pick(team="Duke", round_code="R64", game=1, matchup="(1) Duke vs (16) Siena",
              region="East", pick_source="CHALK", divergence=-0.021):
    return {
        "picked_team": team,
        "round": round_code,
        "game": game,
        "matchup": matchup,
        "region": region,
        "pick_source": pick_source,
        "divergence": divergence,
        "abs_divergence": abs(divergence) if divergence else None,
    }


def make_live_scores(espn_abbrev, our_score, opp_abbrev, opp_score, opp_name,
                     state="in", description="In Progress", period=1, clock="10:00"):
    return {
        espn_abbrev: {
            "state": state,
            "description": description,
            "period": period,
            "clock": clock,
            "teams": {
                espn_abbrev: {"name": "Duke", "score": our_score},
                opp_abbrev: {"name": opp_name, "score": opp_score},
            },
        },
        opp_abbrev: {
            "state": state,
            "description": description,
            "period": period,
            "clock": clock,
            "teams": {
                espn_abbrev: {"name": "Duke", "score": our_score},
                opp_abbrev: {"name": opp_name, "score": opp_score},
            },
        },
    }


def fresh_score():
    return {"correct": 0, "busted": 0, "resolved_games": []}


# ─── Test 1: Halftime alert ──────────────────────────────────────────────

def test_halftime():
    pick = make_pick()
    espn_ab = ESPN_ABBREV_MAP["Duke"]  # DUKE
    live = make_live_scores(espn_ab, 38, "SIENA", 30, "Siena",
                            description="Halftime", period=1, clock="0:00")
    state = UserAlertState()
    score = fresh_score()

    msgs, changed = check_alerts_for_user([pick], score, live, {}, state)
    ok = len(msgs) == 1 and "Halftime" in msgs[0] and "leads by 8" in msgs[0]
    report("Halftime alert", ok, f"msgs={msgs}")


# ─── Test 2: Crunch time alert ───────────────────────────────────────────

def test_crunch_time():
    pick = make_pick()
    espn_ab = ESPN_ABBREV_MAP["Duke"]
    live = make_live_scores(espn_ab, 62, "SIENA", 58, "Siena",
                            description="In Progress", period=2, clock="3:42")
    state = UserAlertState()
    score = fresh_score()

    msgs, changed = check_alerts_for_user([pick], score, live, {}, state)
    ok = len(msgs) == 1 and "Crunch time" in msgs[0] and "3:42" in msgs[0]
    report("Crunch time alert", ok, f"msgs={msgs}")


# ─── Test 3: Upset brewing ───────────────────────────────────────────────

def test_upset_brewing():
    # Use a DIVERGE pick so the upset-brewing logic fires
    pick = make_pick(pick_source="DIVERGE", divergence=0.15)
    espn_ab = ESPN_ABBREV_MAP["Duke"]
    live = make_live_scores(espn_ab, 52, "SIENA", 40, "Siena",
                            description="In Progress", period=2, clock="8:00")
    state = UserAlertState()
    score = fresh_score()

    msgs, changed = check_alerts_for_user([pick], score, live, {}, state)
    ok = len(msgs) >= 1 and any("Upset brewing" in m for m in msgs)
    report("Upset brewing alert", ok, f"msgs={msgs}")


# ─── Test 4: Game resolution (win) ───────────────────────────────────────

def test_resolution_win():
    pick = make_pick()
    kalshi_ab = ABBREV_MAP["Duke"]  # DUKE
    odds = {kalshi_ab: {"prob": 0.95, "status": "closed", "ticker": "KXNCAAMBGAME-MAR20-DUKE"}}
    state = UserAlertState()
    score = fresh_score()

    msgs, changed = check_alerts_for_user([pick], score, {}, odds, state)
    ok = (len(msgs) == 1 and "wins" in msgs[0] and changed
          and score["correct"] == 1 and score["busted"] == 0)
    report("Game resolution (win)", ok, f"msgs={msgs}, score={score}")


# ─── Test 5: Game resolution (loss) ──────────────────────────────────────

def test_resolution_loss():
    pick = make_pick()
    kalshi_ab = ABBREV_MAP["Duke"]
    odds = {kalshi_ab: {"prob": 0.10, "status": "closed", "ticker": "KXNCAAMBGAME-MAR20-DUKE"}}
    state = UserAlertState()
    score = fresh_score()

    msgs, changed = check_alerts_for_user([pick], score, {}, odds, state)
    ok = (len(msgs) == 1 and "is out" in msgs[0] and changed
          and score["correct"] == 0 and score["busted"] == 1)
    report("Game resolution (loss)", ok, f"msgs={msgs}, score={score}")


# ─── Test 6: Odds movement (6% drop) ─────────────────────────────────────

def test_odds_movement():
    pick = make_pick()
    kalshi_ab = ABBREV_MAP["Duke"]
    state = UserAlertState()
    score = fresh_score()

    # First call: set baseline odds at 0.70
    odds_v1 = {kalshi_ab: {"prob": 0.70, "status": "active", "ticker": "KXNCAAMBGAME-MAR20-DUKE"}}
    msgs1, _ = check_alerts_for_user([pick], score, {}, odds_v1, state)

    # Second call: drop to 0.64 (6% drop)
    odds_v2 = {kalshi_ab: {"prob": 0.64, "status": "active", "ticker": "KXNCAAMBGAME-MAR20-DUKE"}}
    msgs2, _ = check_alerts_for_user([pick], score, {}, odds_v2, state)

    ok = len(msgs2) == 1 and "sliding" in msgs2[0]
    report("Odds movement (6% drop)", ok, f"msgs1={msgs1}, msgs2={msgs2}")


# ─── Test 7: De-duplication ──────────────────────────────────────────────

def test_deduplication():
    pick = make_pick()
    espn_ab = ESPN_ABBREV_MAP["Duke"]
    live = make_live_scores(espn_ab, 38, "SIENA", 30, "Siena",
                            description="Halftime", period=1, clock="0:00")
    state = UserAlertState()
    score = fresh_score()

    msgs1, _ = check_alerts_for_user([pick], score, live, {}, state)
    msgs2, _ = check_alerts_for_user([pick], score, live, {}, state)

    ok = len(msgs1) == 1 and len(msgs2) == 0
    report("De-duplication", ok, f"first={len(msgs1)}, second={len(msgs2)}")


# ─── Test 8: Rate limiting ──────────────────────────────────────────────

def test_rate_limiting():
    state = UserAlertState()
    # Fill up timestamps to MAX
    now = time.time()
    state.alert_timestamps = [now - i for i in range(MAX_ALERTS_PER_HOUR)]
    ok = not state.can_send()
    report("Rate limiting (can_send=False after max)", ok,
           f"can_send={state.can_send()}, timestamps={len(state.alert_timestamps)}")

    # Verify old timestamps are pruned
    state2 = UserAlertState()
    state2.alert_timestamps = [now - 7200 for _ in range(50)]  # all 2 hours old
    ok2 = state2.can_send()
    report("Rate limiting (expired timestamps pruned)", ok2,
           f"can_send={state2.can_send()}")


# ─── Run all ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== live_alerts.py test suite ===\n")
    test_halftime()
    test_crunch_time()
    test_upset_brewing()
    test_resolution_win()
    test_resolution_loss()
    test_odds_movement()
    test_deduplication()
    test_rate_limiting()
    print(f"\n{'='*40}")
    print(f"  {PASS} passed, {FAIL} failed")
    print(f"{'='*40}\n")
    sys.exit(1 if FAIL else 0)
