# Bracket Divergence

Compare Kalshi prediction market odds against Claude's independent game assessments to find divergence — and make picks from it.

## How It Works

The tool operates in three stages:

### 1. Pull Market Data
`kalshi_odds.py` hits the Kalshi public API (no auth required) and pulls championship winner market prices for all NCAA tournament teams. Raw data is saved to `kalshi_markets.json`.

### 2. Derive Game-Level Odds
`derive_odds.py` takes those championship prices and normalizes them into head-to-head first-round win probabilities. For each matchup, if Team A has a 17.5% championship price and Team B has 1.0%, Team A's implied H2H win probability is `17.5 / (17.5 + 1.0) = 94.6%`.

Output is saved to `matchups_with_odds.json`.

### 3. Run the Divergence Engine
`bracket_divergence.py` is the main engine. It runs all 63 tournament games across 6 rounds:

- **Classifies each game** into one of two modes:
  - **MARKET SIGNAL** — At least one team has meaningful Kalshi championship odds (>1.2%). The market has an opinion. Divergence logic applies.
  - **CLAUDE ONLY** — Both teams are at the Kalshi floor price. The market has no differentiation. Claude's blind assessment is the entire pick.

- **Claude assesses each matchup blind** (no odds shown) and returns a win probability + rationale.

- **For MARKET SIGNAL games**, computes divergence:
  - `divergence >= 8pp` → take Claude's contrarian pick (DIVERGE)
  - `divergence >= 15pp` → flagged as strong divergence
  - `divergence < 8pp` → take the market favorite (CHALK)

- **For CLAUDE ONLY games**, Claude's probability IS the pick, tagged with conviction level:
  - **HIGH** — Claude is 25+ pp from 50/50
  - **MED** — Claude is 12-25 pp from 50/50
  - **LOW** — Claude is <12 pp from 50/50

Winners from each round feed into the next. The full bracket cascades through Round of 64 → Round of 32 → Sweet 16 → Elite 8 → Final Four → Championship.

## Quick Start

```bash
# Set up
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY="your-key"

# Pull fresh Kalshi odds
python kalshi_odds.py

# Derive game-level probabilities
python derive_odds.py

# Run the full tournament
python bracket_divergence.py
```

## Files

| File | Purpose |
|------|---------|
| `bracket_divergence.py` | Main engine — all 6 rounds, dual-mode picks, full output |
| `kalshi_odds.py` | Pulls championship market data from Kalshi API |
| `derive_odds.py` | Derives H2H game probabilities from championship odds |
| `matchups.json` | First-round bracket with seeds and teams |
| `kalshi_markets.json` | Raw Kalshi market data (auto-generated) |
| `matchups_with_odds.json` | Matchups enriched with derived probabilities |
| `results.json` | Full tournament results (auto-generated) |
| `requirements.txt` | Python dependencies |

## 2026 Tournament Results

**Champion: (6) Tennessee** — CLAUDE ONLY pick, MED conviction

**Final Four:**
- East: (8) Ohio State
- West: (6) BYU
- South: (6) North Carolina
- Midwest: (6) Tennessee

**Pick Distribution (63 games):**
- MARKET SIGNAL: 35 games (15 chalk, 20 divergence, avg gap 18.4%)
- CLAUDE ONLY: 28 games (1 high, 8 med, 19 low conviction)

**Biggest divergence:** (3) Virginia vs (6) Tennessee — 35% gap, Claude took Tennessee

## Configuration

Tunable constants at the top of `bracket_divergence.py`:

- `SIGNIFICANT_DIVERGENCE` — Minimum gap to override market (default: 8pp)
- `STRONG_DIVERGENCE` — Threshold for strong divergence flag (default: 15pp)
- `FLOOR_THRESHOLD` — Championship odds below this = no market signal (default: 1.2%)
- `MODEL` — Claude model for assessments (default: `claude-sonnet-4-6`)

## Notes

- Kalshi's public API requires no authentication for market data reads
- Championship odds are the only Kalshi markets available for NCAA — no individual game lines
- Many mid-to-low seed teams sit at Kalshi's $0.01 minimum, providing no spread signal
- The CLAUDE ONLY category is where the tool adds the most unique value — these are games the prediction market can't price
