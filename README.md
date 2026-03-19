# Bracket Divergence

Find where prediction markets and AI disagree on March Madness — then pick from the gap.

Bracket Divergence pulls live Kalshi odds, runs a KenPom-powered ensemble model with Claude's contextual adjustments, and surfaces every game where the two signals diverge. You get three things: which games have edge, which direction the edge points, and why.

Works as a personal tool or a multi-user Telegram bot. Users send their ESPN bracket link, the bot analyzes it against live market data, and tracks their picks through the tournament with live score updates.

For entertainment and analysis only — not financial advice.

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

Results land in `results.json`. Every game includes the Kalshi price, the ensemble probability, each model component, and Claude's reasoning.

---

## User-facing bot

The public Telegram bot — [@MarketVsMadnessBot](https://t.me/MarketVsMadnessBot) — lets anyone analyze their March Madness bracket.

### User journey

1. User messages the bot `/start`
2. Bot asks for their ESPN bracket link, a screenshot, or offers `/build`
3. User submits bracket (ESPN link, screenshot, or guided builder)
4. Bot runs divergence analysis — shows where the user's picks agree and disagree with the ensemble model and Kalshi odds
5. Bot sends visual bracket image (PNG) with picks by round
6. During games — bot sends live alerts: halftime scores, crunch time updates, upset alerts, game results, odds movement
7. After games — bot reports which picks hit and tracks running score with green/red color coding
8. User can ask questions anytime: "how's my bracket?", "what's my riskiest pick?", "who do I have in the Final Four?"

### Intake methods

| Method | How it works |
|--------|-------------|
| **ESPN link** | User pastes their bracket URL. Bot extracts UUID, hits ESPN's public API, pulls all 63 picks. Zero manual entry. |
| **Screenshot** | User sends a photo of their bracket (any source). Claude Vision reads it and extracts picks. |
| **Guided builder** (`/build`) | Bot walks through all 63 games one by one with inline buttons. Shows market odds vs model at each matchup. Supports undo. |

### Bot commands

| Command | What it does |
|---------|-------------|
| `/start` | Begin — submit your bracket |
| `/build` | Guided bracket builder — pick all 63 games with divergence data |
| `/mybracket` | View your picks as text summary + visual bracket image (PNG) |
| `/refresh` | Re-run divergence analysis with latest odds |
| `/alerts` | Toggle live game alerts on/off |
| `/score` | Your current W/L record |
| `/help` | Command list |

### Live alerts (automatic)

All users with active brackets receive alerts during games — no action needed:

| Alert | Trigger |
|-------|---------|
| **Halftime** | Your picked team's game reaches halftime |
| **Crunch time** | Under 5 min left, margin 8 or less |
| **Upset brewing** | Your bold pick is leading by 10+ |
| **Game result** | Win or loss with running W/L record |
| **Odds sliding** | 5%+ drop on one of your picks — with context on whether it's a model pick, your pick, or chalk |

Alerts include pick source context: model picks ("we overrode the market — worth watching"), user picks ("your pick — the market is moving against it"), and chalk picks ("market is softening"). Alerts are rate-limited to 20/hour per user. Toggle with `/alerts off`.

### Running the bot

```bash
python bot.py
```

Requires `TELEGRAM_BOT_TOKEN_PUBLIC` (separate from the personal monitor bot) and `ANTHROPIC_API_KEY`.

User data is stored per chat ID in `users/{chat_id}/`. Each user gets their own bracket state, score tracking, and Q&A context. Alert state (previous odds, alerted game moments) is persisted to `users/{chat_id}/alert_state.json` so odds movement detection survives restarts. The live alert system runs as a background thread, polling ESPN every 30 seconds during live games and Kalshi every 10 minutes.

**Persistent storage:** Attach a Railway volume at `/app/users` so user data and alert state survive deploys.

---

## How it works

Two independent signals. One divergence calculation.

### Signal 1: Kalshi

Live prediction market odds from eight Kalshi series:

| Series | What it prices |
|--------|---------------|
| `KXNCAAMBGAME` | Per-game winner — direct H2H contracts |
| `KXMARMAD` | Championship winner — "Will Duke win it all?" |
| `KXMARMADSEEDWIN` | Seed upset props — "Will a 16 seed win?" |
| `KXMARMADSEED` | Seed advancement — "Highest seed in the Final Four?" |
| `KXMARMADUPSET` | Upset totals — "7+ upsets in Round of 64?" |
| `KXMARMADPTS` | Player points — "Will anyone score 40+?" |
| `KXMARMAD1SEED` | 1-seed props |
| `KXMARMADCONF` | Conference props — "Will a Big 12 team win?" |

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

### Live scores

ESPN's free scoreboard API provides real-time game data. The bot polls every 30 seconds during live games and sends Telegram alerts at key moments:

- **Halftime** — score update with pick status
- **Crunch time** — under 5 minutes, margin ≤ 8
- **Upset alert** — a Claude pick is up by 10+ ("It's working.")
- **Game resolution** — win or loss with running score

---

## Commands

### Generate a bracket

```bash
python bracket_divergence.py            # Run with existing Kalshi data
python bracket_divergence.py --refresh  # Pull fresh odds first
python bracket_divergence.py --watch    # Re-run every 60 min, track changes
```

### Pull market data

```bash
python kalshi_odds.py    # Pull all 8 Kalshi series (~11K markets)
```

### Generate comparison brackets

```bash
python split_brackets.py    # Pure-Kalshi, pure-Claude, hybrid + comparison table
```

### Run the public bot

```bash
python bot.py    # Multi-user Telegram bot
```

### Monitor your personal picks

```bash
python monitor.py           # Start tracking
python monitor.py --reset   # Reset score
```

---

## Configuration

### Environment variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Personal monitor (BelowTheFloorBot)
TELEGRAM_BOT_TOKEN=your-personal-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# Public bot (separate Telegram bot)
TELEGRAM_BOT_TOKEN_PUBLIC=your-public-bot-token

# Trading — admin only, never exposed to users
KALSHI_API_KEY=your-kalshi-api-key
KALSHI_PRIVATE_KEY_PATH=./kalshi_private.pem
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

### KenPom ratings

`kenpom_ratings.json` contains efficiency ratings for all 64 tournament teams. Update before each run for best results. A [kenpom.com](https://kenpom.com) subscription ($25/yr) provides exact values.

---

## Files

### Scripts

| File | What it does |
|------|-------------|
| `bracket_divergence.py` | Main engine. Ensemble model + Kalshi odds + divergence. All 63 games. |
| `bot.py` | Multi-user Telegram bot. ESPN intake, screenshot intake, guided builder, Q&A, visual bracket, live alerts. |
| `bracket_image.py` | Renders user bracket as PNG image using Pillow. Color-coded correct/busted picks. |
| `live_alerts.py` | Multi-user live alert system. Polls ESPN + Kalshi, sends game-day notifications with pick source context. Persists alert state to disk. |
| `espn_scraper.py` | ESPN Tournament Challenge API client. Pulls bracket picks from URLs. |
| `kalshi_odds.py` | Pulls all 8 Kalshi NCAA tournament series. No auth required. |
| `ensemble.py` | KenPom logistic, Log5, seed historical. Computes blended probability. |
| `monitor.py` | Personal pick tracker with Telegram alerts and ESPN live scores (single-user). |
| `derive_odds.py` | Derives H2H probabilities from championship odds alone. |
| `split_brackets.py` | Generates three independent bracket files + comparison table. |
| `kalshi_trader.py` | Automated trading with safety rails. Admin only. |

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

---

## Deploy

Railway with four services from one repo:

| Service | Start command | What it does |
|---------|-------------|-------------|
| **bot** | `python bot.py` | Public multi-user Telegram bot |
| **monitor** | `python monitor.py` | Personal pick tracker + live scores |
| **watch** | `python bracket_divergence.py --watch` | Hourly bracket re-runs |
| **trader** | `python kalshi_trader.py` | Automated trading (admin only) |

Each service sets its own start command in the Railway dashboard. Shared variables are linked per service. The **bot** service requires a persistent volume mounted at `/app/users` to retain user data and alert state across deploys.

```bash
# Required shared variables:
ANTHROPIC_API_KEY          → bot, monitor, watch
TELEGRAM_BOT_TOKEN         → monitor
TELEGRAM_BOT_TOKEN_PUBLIC  → bot
TELEGRAM_CHAT_ID           → monitor
MAX_TRADE                  → trader
MAX_EXPOSURE               → trader
```

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

---

## Architecture

```
                          ┌─────────────────────────────────┐
                          │          USER ENTRY              │
                          │                                  │
                          │  ESPN link ──► espn_scraper.py   │
                          │  Screenshot ──► Claude Vision    │
                          │  /build ──► guided builder       │
                          └──────────┬──────────────────────┘
                                     │
                                     ▼
                               bot.py (public)
                          @MarketVsMadnessBot
                          per-user bracket tracking
                          Q&A with bracket context
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                ▼
              Live scores      Divergence       Odds tracking
              (ESPN API)       analysis         (Kalshi API)
              30s polling      vs ensemble      10min polling
                    │                │                │
                    └────────┬───────┘                │
                             ▼                        │
                    live_alerts.py                     │
                    (background thread)               │
                    ┌────────────────────┐             │
                    │  Halftime scores   │             │
                    │  Crunch time       │             │
                    │  Upset alerts      │             │
                    │  Game results      │◄────────────┘
                    │  Odds movement     │
                    └────────────────────┘
                             │
                             ▼
                    bracket_image.py
                    ┌────────────────────┐
                    │  Visual bracket    │
                    │  PNG rendering     │
                    │  Green/red coding  │
                    └────────────────────┘

  ─── ENGINE ───────────────────────────────────────────

  kalshi_odds.py                    bracket_divergence.py
       │                                    │
       ▼                                    ▼
   Kalshi API ──► kalshi_markets.json    KenPom logistic ─┐
   (8 series)                            Log5 formula ────┤──► Base ensemble
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
                                      results.json
```
