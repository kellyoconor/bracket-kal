# Bracket Divergence

Compare Kalshi prediction market odds against Claude's independent game assessments to find divergence — and make picks from it.

Pulls 11,000+ live Kalshi markets across 7 series, has Claude blindly assess every matchup, computes the gap, and picks from it. All 63 games. All 6 rounds.

## How It Works

### 1. Pull Market Data

`kalshi_odds.py` hits the Kalshi public API (no auth required) and pulls every NCAA tournament market across 7 series:

| Series | Ticker | What it is |
|--------|--------|-----------|
| Championship Winner | `KXMARMAD` | "Will Duke win the national championship?" |
| Per-Game Winner | `KXNCAAMBGAME` | "Duke at Siena Winner?" — direct H2H odds |
| Seed Upset Props | `KXMARMADSEEDWIN` | "Will a #16 seed win in R64?" |
| Seed Advancement | `KXMARMADSEED` | "Will a #1 seed win the championship?" |
| Upset Totals | `KXMARMADUPSET` | "At least 7 upsets in R64?" |
| Player Points | `KXMARMADPTS` | "Will any player score 40+ points?" |
| 1-Seed Props | `KXMARMAD1SEED` | "Will Duke be a 1 seed?" |

### 2. Run the Divergence Engine

`bracket_divergence.py` runs all 63 tournament games across 6 rounds with a 3-tier signal priority:

**Tier 1: GAME_MARKET** — Direct per-game H2H winner contracts from `KXNCAAMBGAME`. Best signal. Currently covers 61 of 63 games.

**Tier 2: DERIVED** — Championship odds (`KXMARMAD`) normalized into H2H probabilities with seed-based Bayesian priors. Fallback when no game market exists.

**Tier 3: CLAUDE_ONLY** — Both teams at Kalshi floor with no game market. Claude's blind assessment is the entire pick. Currently 0 games (eliminated with live game data).

For each game:
- Claude assesses the matchup blind (no odds shown) and returns a win probability + rationale
- The engine computes divergence: `Claude's prob - Market's prob`
- `divergence >= 8pp` = take Claude's contrarian pick (**DIVERGE**)
- `divergence >= 15pp` = flagged as strong divergence
- `divergence < 8pp` = take the market favorite (**CHALK**)

Winners cascade through Round of 64 -> Round of 32 -> Sweet 16 -> Elite 8 -> Final Four -> Championship.

Props/futures markets (upset totals, seed advancement, player points) are displayed alongside results for cross-validation.

### 3. Generate Bracket Comparisons

`split_brackets.py` generates three independent brackets from results:
- **kalshi_bracket.json** — Pure market odds, no Claude input
- **claude_bracket.json** — Pure Claude assessment, no market input
- **divergence_bracket.json** — Hybrid: aligned = take favorite, diverge = take Claude
- **comparison_table.json** — Every game where Kalshi and Claude disagree

## Quick Start

```bash
# Set up
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key"

# Pull fresh Kalshi odds (all 7 series, ~11K markets)
python kalshi_odds.py

# Run the full 63-game tournament
python bracket_divergence.py

# Generate comparison brackets
python split_brackets.py
```

### Other tools

```bash
# Derive H2H probabilities from championship odds alone
python derive_odds.py
```

## Files

| File | Purpose |
|------|---------|
| `bracket_divergence.py` | Main engine — 3-tier signal, all 6 rounds, props context |
| `kalshi_odds.py` | Pulls all 7 Kalshi NCAA tournament series |
| `derive_odds.py` | Derives H2H game probabilities from championship odds |
| `split_brackets.py` | Generates pure-Kalshi, pure-Claude, and hybrid bracket files |
| `matchups.json` | 2026 first-round bracket (32 games, real Selection Sunday data) |
| `kalshi_markets.json` | Raw Kalshi market data across all series (auto-generated) |
| `results.json` | Full 63-game tournament results with assessments (auto-generated) |
| `kalshi_bracket.json` | Pure market bracket (auto-generated) |
| `claude_bracket.json` | Pure Claude bracket (auto-generated) |
| `divergence_bracket.json` | Hybrid divergence bracket (auto-generated) |
| `comparison_table.json` | Games where Kalshi and Claude disagree (auto-generated) |
| `requirements.txt` | Python dependencies (`anthropic`) |

## 2026 Tournament Results

**Champion: (6) BYU** — divergence pick over (1) Florida, 29% gap

**Final Four:**
| Region | Champion | Seed | Signal Source |
|--------|----------|------|---------------|
| East | Ohio State | 8 | GAME_MARKET |
| West | BYU | 6 | GAME_MARKET |
| South | Florida | 1 | GAME_MARKET |
| Midwest | Michigan | 1 | GAME_MARKET |

**Pick Distribution (63 games):**
```
Signal sources:
  Game market (H2H):    61
  Derived (champ odds):  2
  No signal:             0

Pick types:
  Chalk:                24
  Divergence:           39  (avg gap 22.6%)
  Claude only:           0
```

**Biggest divergence:** (1) Michigan vs (16) UMBC — 50% gap

## Kalshi Market Coverage

As of March 2026, Kalshi has:
- **68** championship winner markets
- **10,450+** per-game winner contracts (regular season + tournament)
- **28** live first-round tournament H2H markets
- **59** seed advancement futures
- **42** upset total props
- **8** seed upset props
- **5** player points props
- **15** 1-seed props

Per-game markets (`KXNCAAMBGAME`) are the primary signal — direct H2H winner contracts with real bid/ask spreads. Championship markets (`KXMARMAD`) serve as fallback for later rounds where game markets haven't been created yet.

Kalshi does **not** offer: player props (rebounds, assists), Most Outstanding Player, over/unders, margin of victory, or conference-level props. Those would require a sportsbook API.

## Configuration

Tunable constants at the top of `bracket_divergence.py`:

| Constant | Default | What it does |
|----------|---------|-------------|
| `SIGNIFICANT_DIVERGENCE` | 0.08 | Minimum gap to override market (8pp) |
| `STRONG_DIVERGENCE` | 0.15 | Threshold for strong divergence flag (15pp) |
| `FLOOR_THRESHOLD` | 0.012 | Championship odds below this = no signal for derivation |
| `MODEL` | `claude-sonnet-4-6` | Claude model for blind assessments |

## Architecture

```
kalshi_odds.py          bracket_divergence.py          split_brackets.py
     |                         |                              |
     v                         v                              v
 Kalshi API  ──>  kalshi_markets.json  ──>  results.json  ──>  3 bracket files
 (7 series)       (11K+ markets)            (63 games)         + comparison table
                       |
                       v
              3-tier signal resolution:
              1. KXNCAAMBGAME (H2H)
              2. KXMARMAD (derived)
              3. Claude-only (fallback)
                       |
                       v
              Claude blind assessment
              (Anthropic API)
                       |
                       v
              Divergence calculation
              + pick resolution
              + bracket cascading
```
