# How BelowTheFloorBot Got Built
### March 16, 2026 — A conversation that started with a bracket challenge and ended with a product

---

## Where We Started

A Slack message from Ryan Piscitelli. Mosaic March Madness bracket challenge. Use AI, submit by Thursday noon, maybe win VIP seats to an AI NOW event featuring Brett Taylor, Chairman of OpenAI.

The question: *"knowing me... how can we kill this challenge in a new and creative way?"*

What followed was about four hours of building — interspersed with idea rejection, course correction, commitment anxiety, and one accidentally posted Telegram token (twice).

---

## The First Pass: Too Basic

The obvious moves came out first. Multi-model panel. Multimodal bracket upload. Comcast-flavored rationales for every pick. Each one got shot down immediately.

*"Those still feel pretty basic. Like you know I am like power user building agentic workspaces and systems... what is the holy shit this is how this works moment?"*

The four-agent architecture came next — Stats Agent, Chaos Agent, Narrative Agent, Meta Agent — with a conflict resolver. It got a diagram. It got rejected just as fast.

*"Hmm does that seem like agents for agents sake?"*

Yes. Honestly yes.

---

## The Autoresearch Tangent

Karpathy had just dropped [autoresearch](https://github.com/karpathy/autoresearch) the week before — a system where AI agents run ML experiments autonomously overnight, iterating on a training script with a fixed 5-minute compute budget. The feedback signal is validation loss. The human writes `program.md`. The machine runs 100 experiments while you sleep.

The idea: apply the same pattern to bracket picking. Not a prompt. A self-improving loop.

The problem: autoresearch works because it has a real metric that returns immediately. Bracket picks don't have that. You'd be borrowing the aesthetic of the methodology without the loop actually closing.

*"Is that what autoresearch is for?"*

No. Honestly no. Called it.

---

## The Pivot That Mattered: Kalshi

The conversation shifted. Someone mentioned Kalshi — the CFTC-regulated prediction market where real money trades on event outcomes. March Madness championship markets were live. Duke at 21.5%. Michigan at 19%. Real crowd-sourced probability signals.

The question that clicked: *"Where does Claude's confidence diverge from the market?"*

Not "who wins." Not "fill out my bracket." **Where does AI reasoning disagree with real money?**

That's the signal. Those gaps are the picks.

The form answer: *"I used real-money prediction market odds as my baseline and built a bracket from the gaps between market consensus and AI reasoning."*

This was the idea worth building.

---

## The Detours (There Were Several)

Before committing, a lot of other ideas got explored:

- **Transfer portal disruption scores** — teams with high roster turnover are volatile. Interesting until it wasn't: "Is this a little bit of a duh? Like teams with transfers and NIL... duh." Yes. Conventional wisdom, already priced in.
- **NBA player prop lines as team health signals** — prop movement reveals injury info. Genuinely interesting, not built.
- **Coach press conference language** — scrape for hedging language and confidence markers. Also not built.
- **The Welly angle** — pick the bracket based on your own Oura HRV data. High HRV day = take chalk. Low HRV = take the upset. The bracket as a biometric artifact. Completely unreplicable by anyone else. Rejected because it's a bit too much.
- **The anti-bracket** — optimize deliberately to lose. Document it like research. Show up to the April event with findings on AI overconfidence. Genuinely considered. Eventually set aside because the Kalshi idea was more interesting.
- **The "point of view" submission** — write a one-pager on why every approach in the challenge is wrong. Rejected: *"that's not exciting."*

---

## The Commitment Problem

*"Yeah I guess the Kalshi thing would be the coolest?"* — said twice, with a question mark.

The pattern: every time a good idea landed, the instinct was to keep looking. More options. More angles. More ideas. Each one evaluated and found wanting.

Eventually called directly: *"You've been doing this the whole conversation. Every time we land on something good you go 'but what else?' Kalshi divergence is the idea. Let's just build it right now."*

The bracket challenge had a Thursday noon deadline. The April event was the real prize. And the idea that would win the room at April wasn't going to come from more deliberation — it was going to come from having actually built something.

---

## The Build: What Actually Got Made

### Step 1: The Data

Started with `matchups.json` — the 32 first-round games from Selection Sunday. Then `kalshi_odds.py` hit the public Kalshi API (no auth required) and pulled championship markets for all 68 teams. Duke at 21.5%. The floor teams at $0.01.

The first problem: Kalshi doesn't differentiate mid-seed teams. Both teams in a 8-9 matchup at the floor means a 50/50 derived H2H probability. No signal.

This became a feature not a bug: **two modes emerged.**
- **MARKET SIGNAL** — at least one team above the floor. Real Kalshi opinion. Divergence math applies.
- **CLAUDE ONLY** — both teams at floor. Market has no opinion. Claude's assessment is the only input.

### Step 2: The Divergence Engine

`bracket_divergence.py` — the core. For every game:

1. Resolve market signal (three-tier priority: GAME_MARKET > DERIVED > NONE)
2. Claude assesses the matchup blind — no peeking at the Kalshi price
3. Compare. Calculate divergence.
4. Pick logic: < 8pp gap → take the market favorite (chalk). ≥ 8pp → take Claude's side.

First run: 63 games, Tennessee as champion (6-seed), no 1-seeds in the Final Four. The methodology ran out of signal after the Sweet 16 and kept going anyway.

*"Haha no there is NO way this is all true."*

Right. The fix: trust the engine through Round of 32. Override manually from Sweet 16 forward. Keep what's real, acknowledge where it breaks.

### Step 3: Real Game Markets

Individual game markets started opening Tuesday as First Four tipped off. `kalshi_odds.py` got upgraded to pull `KXNCAAMBGAME` — direct H2H winner contracts.

Rerun with real per-game odds: 61 of 63 games with direct Kalshi signal. Zero blind picks. 39 divergence picks with an average 22.6% gap.

**New champion: BYU (6-seed) — 29% divergence over Florida.**
**Final Four: Ohio State (8), BYU (6), Florida (1), Michigan (1).**

### Step 4: The Ensemble Upgrade

The ensemble module (`ensemble.py`) replaced Claude's blind assessment with a three-model blend:

- **KenPom logistic** (60% base weight) — win probability from offensive/defensive efficiency differential
- **Log5 formula** (25%) — Bill James head-to-head probability from season win rates
- **Seed historical** (15%) — 1985–2025 tournament seed matchup records

Claude's role shifted: not picking winners, but reading five contextual factors per game (momentum, matchup dynamics, venue, upset indicators, weight adjustment) and shifting the ensemble weights accordingly. The picks come from the math. Claude adjusts how much to trust each component.

### Step 5: Three Brackets

`split_brackets.py` generates three complete independent brackets from the same data:

| Bracket | Logic |
|---------|-------|
| Kalshi bracket | Pure market. Always takes the Kalshi favorite. |
| Claude bracket | Pure ensemble. Always follows the ensemble probability. |
| Divergence bracket | The hybrid. Agree within 8pp = take market. Diverge >8pp = take Claude. |

The comparison table shows every game where Kalshi and Claude picked differently. That's the experiment. After the tournament plays out, one bracket will have won. That's the finding.

### Step 6: The Live System

Three more files built on top of the engine:

**`monitor.py`** — live tournament tracker. Polls Kalshi every 10 minutes. Sends Telegram alerts when:
- A picked team's odds drop >5%
- A game resolves (correct or busted)
- Running divergence vs. chalk hit rate updates

Alert style is human: *"We nailed it. The market had them lower but Claude saw the edge."* / *"Sometimes the madness wins."*

**`kalshi_trader.py`** — automated trade execution. Reads `trade_rules.json`, proposes trades via Telegram, waits 60 seconds for a STOP reply, then executes against the Kalshi authenticated API. Hard limits from environment variables. Never trades within 30 minutes of tip-off.

**`bracket_divergence.py --watch`** — reprices the full bracket every 60 minutes as Kalshi odds move. Diffs picks against the previous run. Logs every change to `bracket_history.json`. The living bracket.

### Step 7: The Public Bot

The move that changed the category: `bot.py`.

Instead of a personal tool, this is a public Telegram bot. Any user can:
1. Send `/start`
2. Paste their ESPN bracket URL
3. Get instant divergence analysis — where their picks agree and disagree with the ensemble and Kalshi
4. Receive live game alerts during the tournament
5. Ask natural language questions: *"how's my bracket?" "what's my riskiest pick?"*

ESPN bracket parsing via the public ESPN Tournament Challenge API. Screenshot intake via Claude Vision for users who don't have a link. This turned a personal analysis tool into something anyone in the Mosaic challenge could use.

---

## The Naming Process

The personal monitoring bot needed a name. A full naming process happened.

Rejected: `KalshiBracketBot` (too basic), `ChalkOrChaosBot` (good but not quite), `FadeTheMarketBot` (great name, wrong vibe), `OddsyBot` (cute but not specific), `BracketBeeBot` (too cute), `TheFloorBot` (already taken on Telegram).

Landed on: **`BelowTheFloorBot`**.

Named after the Kalshi floor — the $0.01 minimum contract price where the market has no signal. Below the floor is where the most interesting picks live. The CLAUDE ONLY games. Flying blind. No market opinion. Claude conviction is the only input.

It's specific, trading-flavored, and names the most interesting part of the methodology.

---

## The Security Incidents

The Telegram bot token was accidentally posted publicly. Twice. Both times immediately revoked and regenerated. The second time was in a screenshot showing the browser URL bar.

Lesson: tokens go in `.env` files. Never in chat. Never in screenshots. Never anywhere else.

---

## The Deployment

Railway. Four services from one repo:

| Service | Command | What it does |
|---------|---------|-------------|
| bot | `python bot.py` | Public multi-user Telegram bot |
| monitor | `python monitor.py` | Personal pick tracker |
| watch | `python bracket_divergence.py --watch` | Hourly repricing |
| trader | `python kalshi_trader.py` | Automated trading |

The system runs continuously from Thursday submission through April 7. By the time the AI NOW event happens, there will be three weeks of live data.

---

## The Story for April

Brett Taylor is Chairman of OpenAI. He's going to be in a room full of people who did bracket challenges with AI.

Most of them will say: *"I asked Claude to act like a basketball expert."*

The answer here is different:

*"I built a system that pulls live Kalshi prediction market odds across 8 market series, computes an independent win probability using a KenPom efficiency logistic model, Log5 formula, and 40 years of seed history — with Claude Sonnet dynamically reweighting the ensemble based on matchup context. Any game where the math disagrees with the market by more than 8 percentage points becomes a divergence pick. 39 of 63 games hit that threshold. Then I deployed it on Railway and let it run for three weeks. Here's what the data shows."*

The bracket is the proof of work. The three weeks of live data is the finding. The three-bracket comparison — Kalshi vs. Claude vs. Divergence — is the experiment.

One of them won. That's the conversation.

---

## The Key Decisions

**Kalshi over manual odds** — public API, no auth required, real money signal, updates continuously. Better than any manually curated dataset.

**Derived H2H over championship-only** — back-calculating game probabilities from championship futures isn't perfect, but it's better than guessing. And when real per-game markets opened, the engine upgraded automatically.

**Two modes over one** — acknowledging that the market has no signal on mid-seed matchups made the methodology more honest, not weaker. CLAUDE ONLY picks have conviction scores. You know what you're working with.

**Three brackets over one** — the comparison is the point. One bracket is a submission. Three brackets is an experiment with a result.

**Public bot over personal tool** — the moment `bot.py` was added, this stopped being a bracket challenge entry and started being a product. Anyone can analyze their bracket. That's a different category.

**Railway deployment** — the monitor needed to run 24/7 without a laptop open. This was the right call from the start.

**Accuracy pass on the README** — Claude Code rewrote the documentation from the actual codebase, not from memory. The result was a README that accurately reflects what's built. That matters. The story only lands if it's true.

---

## What Got Named

- **The project**: `bracket-divergence` (repo) / `Mispriced` (best name, not used yet)
- **The bot**: `BelowTheFloorBot`
- **The methodology**: divergence picking — take the upset where the math disagrees with the market
- **The experiment**: three brackets, one winner, three weeks of live data

---

## Files Committed

```
bracket_divergence.py   — Core engine. All 63 games, 6 rounds.
ensemble.py             — Three-model ensemble with Claude weight adjustment.
kalshi_odds.py          — Pulls 8 Kalshi NCAA market series.
derive_odds.py          — Back-calculates H2H from championship futures.
split_brackets.py       — Generates 3 independent brackets + comparison table.
bot.py                  — Public multi-user Telegram bot.
espn_scraper.py         — ESPN Tournament Challenge API client.
monitor.py              — Personal pick tracker with live alerts.
kalshi_trader.py        — Automated trading with safety rails.
matchups.json           — 32 first-round games from Selection Sunday.
kenpom_ratings.json     — KenPom efficiency ratings, all 64 teams.
kalshi_markets.json     — Raw Kalshi data across all 8 series.
results.json            — Full 63-game results with ensemble breakdown.
bracket_picks.json      — Submitted ESPN picks for the monitor.
trade_rules.json        — Trading rules for the automated layer.
BelowTheFloorBot.md     — Reference guide. What it is, how to explain it.
Procfile                — Railway deployment config.
railway.toml            — Railway service config.
.env.example            — Environment variable template.
```

---

## The Bracket

_(Run-specific — reflects the last execution before Thursday submission.)_

**Champion: BYU (6-seed)**
**Final Four: Ohio State (8), BYU (6), Florida (1), Michigan (1)**

39 divergence picks. 24 chalk. Average divergence gap: 22.6%. Biggest single gap: Virginia vs Tennessee at 35%.

Submitted to ESPN Tournament Challenge, Mosaic group, password: `mosaic`. Thursday March 19, before noon.

---

## The Actual Build: Git History

25 commits. 12:10pm to 9:09pm. One session.

---

### 12:10pm — Initial commit
`a18af57` — Empty project scaffold. The starting gun.

### 12:10pm – 1:13pm — The Core Engine (Hour 1)
`cbadfa8` — Dual-mode divergence engine, real 2026 bracket, derived odds, and README. This was the big first commit: `bracket_divergence.py`, `derive_odds.py`, `matchups.json`, and `results.json` all land at once. 6 files, ~1,400 lines added. The two-mode system (MARKET SIGNAL vs CLAUDE ONLY) is already in this commit.

### 1:19pm — Split Brackets
`87b99f5` — `split_brackets.py` and the three output files: `kalshi_bracket.json`, `claude_bracket.json`, `divergence_bracket.json`, plus the comparison table. The "three brackets = one experiment" idea ships within 10 minutes of the core engine.

### 1:19pm – 2:04pm — Kalshi Goes Deep (Hour 2)
`efba549` — Wire all 7 Kalshi series into the engine with live game market odds. This is the commit where `kalshi_odds.py` gets real — pulls 11K+ markets across every series. `kalshi_markets.json` balloons to 618K+ lines. Per-game H2H contracts (`KXNCAAMBGAME`) become the primary signal. The engine upgrades from derived-only to real market data.

### 2:39pm — README v1
`c33d5ea` — Full 7-series architecture documented, live game market coverage, current results. The story starts getting written.

### 2:59pm — Live Infrastructure
`0249719` — `monitor.py`, `kalshi_trader.py`, `--watch` mode, `trade_rules.json`, `.env.example`. The system goes from "run once" to "run continuously." Personal pick tracking. Automated trading with safety rails. Hourly repricing. This is the commit that makes it a live system, not a script.

### 3:03pm — Railway
`320145b` — `Procfile` and `railway.toml`. Deployment config. Four services from one repo.

### 3:39pm — Bracket Picks
`17f6923` — Populate `bracket_picks.json` with all 63 divergence engine picks. The monitor now has something to track.

### 4:21pm – 4:38pm — Polish Sprint (Hour 4-5)
Four commits in 17 minutes:
- `caac274` — Fix monitor: filter to tournament games only, prevent regular season score collisions
- `06170e1` — Add `--reset` flag to monitor for clean deploys
- `570f925` — Rewrite Telegram messages to be human-readable (the messages were too robotic)
- `eaf4d94` / `0d848c4` — Rename "contrarian" → "Claude pick" and "chalk" → "Kalshi pick" everywhere. Language matters. "Contrarian" sounds like you're being edgy. "Claude pick" says what it is.

### 4:59pm — The Ensemble Upgrade
`3ad7642` — Replace blind Claude assessment with the context-weighted ensemble model. `ensemble.py` and `kenpom_ratings.json` arrive. This is the architectural pivot: Claude stops guessing winners and starts adjusting weights on three quantitative models. KenPom logistic (60%), Log5 formula (25%), seed historical (15%). The picks come from math now.

### 5:07pm — KenPom Data
`c392e0d` — Update KenPom ratings with confirmed 2026 tournament data. Real numbers for all 64 teams.

### 5:10pm — README v2
`0074696` — Full rewrite in Stripe documentation style. The README goes from developer notes to product documentation.

### 5:10pm – 7:11pm — Dinner Break
Two-hour gap. First break of the day.

### 7:11pm — Ensemble Run
`0e63921` — Run the full ensemble bracket: 63 games, 27 Kalshi picks / 36 Claude picks, BYU champion. This is the bracket that gets submitted. The final numbers land.

### 7:17pm — Conversational Q&A
`f60703a` — Add natural language Q&A to the Telegram bot. Users can ask "how's my bracket?" or "what's my riskiest pick?" and get real answers with bracket context.

### 7:37pm — ESPN Live Scores
`bfa8753` — ESPN scoreboard API integration into the monitor. 30-second polling. Halftime alerts, crunch time alerts (under 5 min, margin ≤ 8), upset alerts ("It's working."), game resolution. The monitor becomes a live companion, not just a tracker.

### 8:04pm — README v3
`23311e6` — Update to 8 series, add ESPN API research docs. Documentation keeps pace with the build.

### 8:42pm — The Public Bot
`1f3a3bf` — `bot.py` and `espn_scraper.py`. This is the commit that changes the category. Multi-user Telegram bot. ESPN bracket intake (paste your link, get instant analysis). Screenshot intake via Claude Vision. Per-user state. This stopped being a personal tool and became a product.

### 8:44pm – 9:00pm — Hardening
Three commits in 16 minutes:
- `2ff6c97` — Separate `TELEGRAM_BOT_TOKEN_PUBLIC` from the personal bot token
- `a65bd2c` — Add entertainment disclaimer, strip any trading language from the public bot. The public bot is for analysis, not financial advice.
- `366c879` — Fix Railway service configs so each service sets its own start command

### 9:09pm — Final Commit
`247d994` — Update README with public bot documentation, user journey, ESPN intake flow, and deploy guide. The last commit is documentation. The story is complete because the README matches what's built.

---

## The Shape of the Day

| Time Block | What Happened | Key Commits |
|-----------|--------------|-------------|
| 12:10pm – 1:20pm | Core engine + split brackets | 3 commits |
| 1:20pm – 3:00pm | Kalshi deep integration + live infra | 3 commits |
| 3:00pm – 3:40pm | Deploy config + bracket data | 2 commits |
| 4:20pm – 4:40pm | Polish sprint — messages, naming, bugs | 5 commits |
| 4:59pm – 5:10pm | Ensemble upgrade + KenPom + README v2 | 3 commits |
| 5:10pm – 7:10pm | Break | — |
| 7:11pm – 7:37pm | Final bracket run + Q&A + live scores | 3 commits |
| 8:04pm – 9:09pm | Public bot + hardening + final docs | 6 commits |

**Total: 25 commits, ~9 hours (with a 2-hour break), ~8,500 lines of code.**

The pattern: build the engine first, then the infrastructure around it, then the user-facing product, then harden. Each layer assumed the previous one worked. Nothing got rewritten — it got extended.

---

*Built in one day. Deployed by Thursday. Running through April 7.*

*Come back with the data.*
