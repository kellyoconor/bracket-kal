# Bracket Divergence

Find where prediction markets and AI disagree on March Madness — then pick from the gap.

Bracket Divergence pulls live Kalshi odds, runs a KenPom-powered ensemble model with Claude's contextual adjustments, and surfaces every game where the two signals diverge. You get three things: which games have edge, which direction the edge points, and why.

---

## Quick start

```bash
git clone https://github.com/kellyoconor/bracket-kal.git
cd bracket-kal

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your ANTHROPIC_API_KEY to .env

python kalshi_odds.py          # Pull 11K+ live Kalshi markets
python bracket_divergence.py   # Run full 63-game bracket
```

That's it. Results land in `results.json`. Every game includes the Kalshi price, the ensemble probability, each model component, and Claude's reasoning.

---

## How it works

Two independent signals. One divergence calculation.

### Signal 1: Kalshi

Live prediction market odds from seven Kalshi series:

| Series | What it prices |
|--------|---------------|
| `KXNCAAMBGAME` | Per-game winner — direct H2H contracts |
| `KXMARMAD` | Championship winner — "Will Duke win it all?" |
| `KXMARMADSEEDWIN` | Seed upset props — "Will a 16 seed win?" |
| `KXMARMADSEED` | Seed advancement — "Highest seed in the Final Four?" |
| `KXMARMADUPSET` | Upset totals — "7+ upsets in Round of 64?" |
| `KXMARMADPTS` | Player points — "Will anyone score 40+?" |
| `KXMARMAD1SEED` | 1-seed props |

The engine uses per-game H2H contracts (`KXNCAAMBGAME`) as the primary signal. When a game doesn't have a direct market, it falls back to derived odds from championship prices. Props and futures are displayed as cross-validation context.

No API key required. All Kalshi market data is public.

### Signal 2: Ensemble model

Three quantitative models, weighted by Claude's contextual assessment:

| Model | Base weight | What it captures |
|-------|------------|-----------------|
| **KenPom logistic** | 60% | Win probability from offensive/defensive efficiency differential. A 10-point efficiency margin ≈ 86% win probability. |
| **Log5 formula** | 25% | Head-to-head probability derived from each team's season win percentage. `P(A) = pA(1-pB) / [pA(1-pB) + pB(1-pA)]` |
| **Seed historical** | 15% | 1985–2025 tournament seed matchup win rates. 1-seeds beat 16-seeds 99.3% of the time. 5-seeds beat 12-seeds 64.5%. |

**Claude's role is not to guess.** Claude reads the base ensemble output, then evaluates contextual factors the models can't capture:

- Team momentum and recent form
- Style matchup advantages (tempo, size, shooting)
- Venue and travel factors
- Classic upset indicators

Based on this assessment, Claude adjusts the model weights. If a game has a classic upset profile (experienced mid-major vs young blue blood), Claude might shift seed historical weight up and KenPom weight down. The ensemble is recomputed with Claude's adjusted weights.

Output: `{ winner, ensemble_prob, reasoning, upset_flag, weights_used }`

### Divergence

For every game, the engine computes: `divergence = ensemble_prob - kalshi_prob`

| Divergence | What happens |
|-----------|-------------|
| **< 8 percentage points** | Kalshi and ensemble agree. Take the favorite. **Kalshi pick.** |
| **≥ 8 pp** | Meaningful disagreement. Take the ensemble's side. **Claude pick.** |
| **≥ 15 pp** | Strong disagreement. Flagged as high-signal divergence. |

The bracket cascades — winners from each round feed into the next. Round of 64 through the Championship, all 63 games.

---

## Commands

### Generate a bracket

```bash
# One-shot: run with existing Kalshi data
python bracket_divergence.py

# Pull fresh odds first, then run
python bracket_divergence.py --refresh

# Watch mode: re-run every 60 minutes, track changes between runs
python bracket_divergence.py --watch
```

Watch mode pulls fresh Kalshi odds each cycle, recomputes the full bracket, and logs pick changes to `bracket_history.json`.

### Pull market data

```bash
# Pull all 7 Kalshi series (~11K markets)
python kalshi_odds.py
```

### Generate comparison brackets

```bash
# Create pure-Kalshi, pure-Claude, and hybrid brackets + comparison table
python split_brackets.py
```

### Derive odds from championship prices

```bash
# Standalone: normalize championship odds into H2H game probabilities
python derive_odds.py
```

---

## Live monitoring

### Monitor your picks

```bash
python monitor.py           # Start tracking
python monitor.py --reset   # Reset score and start fresh
```

Polls Kalshi every 10 minutes. Sends Telegram alerts when:

- **A picked team's odds drop >5%** — "Heads up — Ohio State is sliding. Was 56%, now 48%. This is a Claude pick — we overrode the market. It's moving against us."
- **A game resolves** — "We nailed it. Ohio State wins. This was a Claude pick — the market had them lower but Claude saw the edge."
- **A pick busts** — "Ohio State is out. Claude pick missed (we saw a 28% gap). Duke advances."

Every message tells you the source (**Claude pick** or **Kalshi pick**) and running record.

### Automated trading

```bash
python kalshi_trader.py
```

Reads `trade_rules.json`, evaluates divergence games against your rules, and executes trades via Kalshi's authenticated API.

Safety rails:
- Hard limits from `.env`: `MAX_TRADE` and `MAX_EXPOSURE`
- Telegrams the trade proposal and waits 60 seconds for `STOP`
- Never trades within 30 minutes of tip-off
- Logs every trade to `trades.json` with timestamp and reasoning

---

## Configuration

### Environment variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Telegram alerts (monitor + trader)
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# Kalshi trading (trader only)
KALSHI_API_KEY=your-kalshi-api-key
KALSHI_PRIVATE_KEY_PATH=./kalshi_private.pem

# Trading limits
MAX_TRADE=25
MAX_EXPOSURE=200
```

### Engine parameters

Top of `bracket_divergence.py`:

| Parameter | Default | What it does |
|-----------|---------|-------------|
| `SIGNIFICANT_DIVERGENCE` | `0.08` | Minimum gap to override Kalshi (8 pp) |
| `STRONG_DIVERGENCE` | `0.15` | High-signal divergence flag (15 pp) |
| `FLOOR_THRESHOLD` | `0.012` | Championship odds below this = no derived signal |
| `MODEL` | `claude-sonnet-4-6` | Claude model for contextual assessment |

### Ensemble weights

Top of `ensemble.py`:

| Model | Default weight | Adjust when... |
|-------|---------------|----------------|
| KenPom logistic | 0.60 | Efficiency numbers are misleading for this matchup |
| Log5 formula | 0.25 | Win percentages are inflated by weak schedules |
| Seed historical | 0.15 | Classic upset profile or Cinderella matchup |

Claude shifts these per-game based on contextual assessment. The defaults are starting points, not fixed.

### KenPom ratings

`kenpom_ratings.json` contains efficiency ratings for all 64 tournament teams. Update before each run for best results. A [kenpom.com](https://kenpom.com) subscription ($25/yr) provides exact values. The included ratings use confirmed rankings from public sources with estimated efficiency values.

### Trade rules

`trade_rules.json` defines when the trader acts:

```json
{
  "name": "strong_divergence_buy",
  "condition": "divergence >= 0.15 and market_price <= 0.70",
  "action": "buy_yes",
  "target": "claude_pick",
  "size_dollars": 10,
  "enabled": true
}
```

---

## Files

### Scripts

| File | What it does |
|------|-------------|
| `bracket_divergence.py` | Main engine. Ensemble model + Kalshi odds + divergence. All 63 games. |
| `kalshi_odds.py` | Pulls all 7 Kalshi NCAA tournament series. No auth required. |
| `ensemble.py` | KenPom logistic, Log5, seed historical. Computes blended probability. |
| `derive_odds.py` | Derives H2H probabilities from championship odds alone. |
| `split_brackets.py` | Generates three independent bracket files + comparison table. |
| `monitor.py` | Live pick tracking with Telegram alerts. Polls Kalshi every 10 min. |
| `kalshi_trader.py` | Automated trading with safety rails. Kalshi authenticated API. |

### Data

| File | What it contains |
|------|-----------------|
| `matchups.json` | 2026 first-round bracket. 32 games, real Selection Sunday data. |
| `kenpom_ratings.json` | KenPom efficiency ratings for all 64 tournament teams. |
| `kalshi_markets.json` | Raw Kalshi market data across all series. Auto-generated. |
| `results.json` | Full 63-game tournament results with ensemble components. Auto-generated. |
| `bracket_picks.json` | Your submitted picks for the monitor to track. |
| `trade_rules.json` | Trading rules for the automated trader. |
| `.env` | API keys and limits. Not committed. |

### Generated outputs

| File | What it contains |
|------|-----------------|
| `kalshi_bracket.json` | Pure Kalshi market bracket. |
| `claude_bracket.json` | Pure ensemble bracket. |
| `divergence_bracket.json` | Hybrid bracket — Kalshi picks where aligned, Claude picks where diverged. |
| `comparison_table.json` | Every game where Kalshi and the ensemble disagree. |
| `bracket_history.json` | Watch mode history — how the bracket changed over time. |
| `trades.json` | Trade execution log with timestamps and reasoning. |
| `monitor_score.json` | Running score — Claude picks vs Kalshi picks hit rate. |

---

## Deploy

The monitor and watch mode are long-running processes. Deploy to Railway for always-on tracking.

```bash
# Railway auto-deploys from GitHub
# Connect repo → set env vars → deploy

# Default start command (from railway.toml):
python monitor.py --reset

# Override per service for multiple processes:
# Service 1: python monitor.py
# Service 2: python bracket_divergence.py --watch
# Service 3: python kalshi_trader.py
```

See `Procfile` for available process types.

---

## Results format

Every game in `results.json` includes the full signal breakdown:

```json
{
  "game": 1,
  "region": "East",
  "matchup": "(1) Duke vs (16) Siena",
  "pick": "Duke",
  "pick_source": "CHALK",
  "signal_source": "GAME_MARKET",
  "kalshi_prob": 0.995,
  "ensemble_prob": 0.962,
  "divergence": -0.033,
  "claude_rationale": "Duke's efficiency margin is historically elite...",
  "upset_flag": false,
  "ensemble": {
    "kenpom_prob": 0.99,
    "log5_prob": 0.88,
    "seed_prob": 0.993,
    "weights": {"kenpom": 0.60, "log5": 0.25, "seed": 0.15},
    "base_ensemble_prob": 0.962
  }
}
```

You see exactly why every pick was made: which model drove it, what Claude adjusted, and how it compares to Kalshi.

---

## Architecture

```
kalshi_odds.py                    bracket_divergence.py
     │                                    │
     ▼                                    ▼
 Kalshi API ──► kalshi_markets.json    KenPom logistic ─┐
 (7 series)    (11K+ markets)          Log5 formula ────┤──► Base ensemble
                    │                  Seed historical ──┘       │
                    │                                            ▼
                    │                                   Claude contextual
                    │                                   assessment adjusts
                    │                                   weights per game
                    │                                            │
                    ▼                                            ▼
              Kalshi H2H prob ◄────── divergence ──────► Ensemble prob
                                          │
                                          ▼
                                    Pick resolution
                                    (< 8pp = Kalshi)
                                    (≥ 8pp = Claude)
                                          │
                                          ▼
                                    Cascade winners
                                    through all rounds
                                          │
                              ┌───────────┼───────────┐
                              ▼           ▼           ▼
                        results.json  monitor.py  kalshi_trader.py
```
