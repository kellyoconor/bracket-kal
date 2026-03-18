# OpenClaw Integration — Backlog

**Status:** Parked
**Priority:** Low — revisit when building a second channel (web, Discord, etc.)
**Created:** 2026-03-16

---

## What

Make Bracket Divergence available as an OpenClaw skill so anyone running OpenClaw (https://openclaw.ai) can add bracket analysis to their personal AI assistant.

OpenClaw is an open-source personal AI assistant that runs locally and connects through chat platforms (WhatsApp, Telegram, Discord, Slack, Signal, iMessage). It has a skills/plugin system with a marketplace called ClawHub.

## Why (and why not yet)

The Telegram bot already serves anyone with a phone — no setup, no self-hosting. OpenClaw users are a smaller, more technical audience who could just use the Telegram bot today.

The integration becomes worth it **when we build a second channel** (web app, Discord bot, embeddable widget, etc.). At that point, decoupling the core logic from Telegram into an API layer is necessary anyway, and the OpenClaw skill becomes a free add-on.

Don't build the API just for OpenClaw. Build it when there's a second consumer, then add OpenClaw for free.

## Architecture: Option B (External Service + Bridge)

Keep bracket-divergence running on Railway as-is. Add a public API layer. Write a thin OpenClaw skill that calls the API.

No ESPN auth needed — users just send screenshots or ESPN links. The service does the analysis.

### What the user experiences

They're chatting with their OpenClaw assistant on any channel:

> **User:** [sends bracket screenshot] "How does my bracket look?"
> **OpenClaw:** "Your bracket diverges from the field in these ways..." [formatted results]

They never see our service. It just works as part of their AI assistant.

### The pieces

**Our side — new API layer (`api.py`)**

| Endpoint | Input | What it does | Returns |
|----------|-------|-------------|---------|
| `POST /api/analyze/espn` | `{ "url": "espn.com/..." }` | ESPN scraper + divergence analysis | Picks + divergence as JSON |
| `POST /api/analyze/screenshot` | image bytes (multipart) | Claude Vision extraction + analysis | Same |
| `GET /api/results` | — | Current results.json | Full 63-game ensemble output |
| `POST /api/ask` | `{ "question": "...", "picks": [...] }` | Q&A with bracket context | Text answer |

**Their side — OpenClaw skill (ClawHub)**

Small manifest + script that tells OpenClaw:
- "I can analyze March Madness brackets"
- If user sends ESPN link → call `/api/analyze/espn`
- If user sends screenshot → call `/api/analyze/screenshot`
- If user asks a bracket question → call `/api/ask`

## Implementation Plan (when ready)

### Step 1: Extract core logic

Refactor `bot.py` — pull the analysis functions out of Telegram-specific code into a shared `core.py`:
- `handle_espn_link()` — already exists, just needs Telegram decoupling
- `handle_screenshot()` — already exists, same
- `run_analysis()` — already exists, same
- `answer_user_question()` — already exists, same

This is the heaviest step. The functions exist but are coupled to Telegram message format and user state stored on disk.

### Step 2: Build `api.py`

Thin FastAPI wrapper around `core.py`. Deploy as a 5th Railway service. Stateless — accepts input, returns results, no user session management on the API side.

### Step 3: Auth and rate limiting

Even a simple API key to prevent abuse. Each call burns Claude API credits (screenshot analysis, Q&A). Consider:
- API key per OpenClaw skill install
- Rate limit per key
- Or just a shared key baked into the skill with a global rate limit

### Step 4: Write OpenClaw skill

Depends on ClawHub's skill definition format. Likely ~50 lines — manifest + API call wrapper + response formatting.

### Step 5: Deploy

Add `api.py` as a Railway service alongside bot, monitor, watch, trader.

## Considerations

- **Cost:** Every OpenClaw user's API call burns our Anthropic credits (screenshot analysis, Q&A). Need rate limiting.
- **Multi-channel win:** The API layer unlocks not just OpenClaw but Discord, web, Slack, etc. — all become thin consumers of the same endpoints.
- **No ESPN auth:** Users send screenshots or public bracket links. No credentials to manage.
- **Stateless API:** The API doesn't need to track users. OpenClaw (or any client) manages its own session/state. The API just takes input and returns analysis.

## Trigger to revisit

When any of these happen:
- We want a Discord bot, web interface, or any second channel
- OpenClaw reaches meaningful adoption and ClawHub has a clear skill SDK
- Someone asks for API access
