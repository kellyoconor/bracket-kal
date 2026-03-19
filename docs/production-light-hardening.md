# Production-Light Hardening Plan

**Status:** Implemented (2026-03-17)

## Implementation notes

All 6 fixes landed in commit `fc70774`, touching three files:
- **bot.py** — rate limiting (Fix 1), eval replacement wired through bot commands, error sanitization (Fix 3), chat_id validation (Fix 4), image size cap (Fix 5), Q&A guardrails (Fix 6)
- **kalshi_trader.py** — safe rule evaluation replacing eval() (Fix 2), error sanitization (Fix 3)
- **monitor.py** — error sanitization (Fix 3), Q&A guardrails (Fix 6)

---

## Fix 1: Per-user rate limiting on public bot

**File:** `bot.py`
**Problem:** No rate limiting. Anyone can spam screenshots or Q&A and run up Anthropic API costs unchecked.

**What to build:**
- Add a `user_rate_limits` dict tracking `{chat_id: [timestamps]}` with a sliding window
- 10 requests per minute per user, 50 per hour
- Screenshot/Q&A requests count. `/start` and simple commands don't
- When rate limited, reply "Too many requests. Please wait a minute." and skip processing
- Add a global daily budget cap: if total API calls exceed 500/day across all users, pause expensive operations (screenshots, Q&A) and reply with "Bot is at capacity for today"

**Where to add it:**
- New function `is_rate_limited(chat_id: str) -> bool` near the top of bot.py
- Call it at the start of `handle_message()` before any API-calling code path
- Use `collections.defaultdict` and `time.time()` — no external dependencies

---

## Fix 2: Replace eval() in trade rule evaluation

**File:** `kalshi_trader.py` (around line 248)
**Problem:** `eval(condition, {"__builtins__": {}}, ctx)` can be escaped via `().__class__.__bases__` chain. Classic Python sandbox escape.

**What to build:**
- Replace `eval()` with structured rule evaluation
- Rules in `trade_rules.json` should be compared as simple conditions, not arbitrary Python expressions
- Parse conditions as a list of comparisons joined by `and`/`or`:
  ```
  "divergence >= 0.15 and market_price <= 0.70"
  ```
- Use a simple tokenizer: split on `and`/`or`, parse each clause as `variable op value`
- Only allow: `>`, `<`, `>=`, `<=`, `==`, `!=` operators
- Only allow known variable names: `divergence`, `market_price`, `claude_prob`, `kalshi_prob`
- Reject anything else

**Do not:**
- Use `ast.literal_eval` (doesn't help here — these aren't literals)
- Add a dependency for this — keep it self-contained
- Change the `trade_rules.json` format unless necessary (prefer parsing the existing string format safely)

---

## Fix 3: Sanitize error messages sent to users

**Files:** `bot.py` (~line 570), `monitor.py` (~line 548), `kalshi_trader.py` (~line 424)
**Problem:** Raw `Exception` strings sent to Telegram. Could leak file paths, API details, internal structure.

**What to change:**
- Every `except Exception as e` block that calls `tg_send` or `telegram_send` with `str(e)`:
  - Log the full error to stdout/stderr with `print(f"Error: {e}")` or `traceback.print_exc()` (keep this for Railway logs)
  - Send a generic message to the user: `"Something went wrong. Please try again."`
- In `kalshi_trader.py`, keep the error in `trade_record["error"]` for local logging but sanitize what goes to Telegram

**Grep for these patterns to find all instances:**
```
tg_send.*{e}
telegram_send.*{e}
```

---

## Fix 4: Validate chat_id in user_dir()

**File:** `bot.py` (~line 122)
**Problem:** `chat_id` used directly in filesystem path with no validation. Path traversal possible if a non-numeric value gets through.

**What to change:**
```python
def user_dir(chat_id: str) -> Path:
    sanitized = str(int(chat_id))  # Force numeric, raises ValueError if not
    d = USERS_DIR / sanitized
    d.mkdir(parents=True, exist_ok=True)
    return d
```

- Telegram chat IDs are always integers (positive for users, negative for groups)
- `str(int(chat_id))` handles both and rejects anything non-numeric
- Wrap the caller in a try/except so a bad chat_id doesn't crash the bot

---

## Fix 5: Image size cap on screenshot intake

**File:** `bot.py` (in `handle_screenshot` or wherever photo data is received)
**Problem:** No size limit on uploaded images. A malicious user could send huge files, each costing API credits.

**What to add:**
- Before sending to Claude Vision, check `len(photo_data)`
- Max 5MB (`5 * 1024 * 1024` bytes)
- If over limit, return a message: "Image too large. Please send a screenshot under 5MB."
- Also cap the number of screenshots per user per hour (covered by Fix 1's rate limiter)

---

## Fix 6: Strengthen hallucination guardrails in Q&A

**Files:** `bot.py` (in `answer_user_question`), `monitor.py` (in `answer_question`)
**Problem:** Claude gets bracket data + user question with a light disclaimer. Could invent stats, cite fake odds, or suggest betting strategies.

**What to change in the system prompt / context preamble:**

Add these rules before the bracket data in both functions:

```
RULES:
1. Only cite facts from the BRACKET DATA below. Do not invent statistics.
2. If the user asks something not covered by the data, say "I don't have that information in the bracket data."
3. Do not cite win percentages, historical records, or KenPom numbers unless they appear in the data below.
4. Never suggest placing bets, trades, or wagers. This is for bracket pool entertainment only.
5. Keep answers concise and grounded in the provided data.
```

**Do not:**
- Add post-response validation or filtering (overkill for production-light)
- Remove the existing entertainment disclaimer — keep it and add these rules alongside it

---

## Fix 7: Thread-safe file I/O for multi-user live alerts

**Status:** Implemented (2026-03-18)

**Files:** `bot.py`, `live_alerts.py`
**Problem:** The live alert background thread reads/writes `user.json` concurrently with the main message handler thread. Two risks: (1) read-modify-write race condition silently clobbers user data, (2) concurrent writes corrupt JSON files.

**What was built:**

- **Atomic file writes** — `save_user()` now writes to a temp file then uses `os.replace()` (POSIX atomic) to swap it in. No partial writes possible.
- **Per-user threading locks** — `_get_user_lock(chat_id)` returns a `threading.Lock` per user. The alert loop uses `update_user_score()` which acquires the lock, re-reads from disk, updates only the score field, and writes back. Prevents clobbering picks/state written by the message handler.
- **Per-user error isolation** — each user's alert processing is wrapped in try/except. One corrupted user doesn't skip alerts for everyone else.
- **`any_live` initialized** — prevents `UnboundLocalError` crash on first-iteration failure.
- **Safe ESPN score parsing** — handles non-numeric score values from ESPN API.

**Test coverage:** 9 tests in `test_live_alerts.py` covering all 6 alert types + dedup + rate limiting. 10 tests in `test_rewind.py` covering the guided builder undo/rewind state machine.

---

## What we're NOT fixing (and why)

| Issue | Why it's fine |
|-------|--------------|
| Telegram token in URLs | That's how the Telegram Bot API works — no alternative |
| User data not encrypted at rest | It's bracket picks on Railway's isolated disk, not PII |
| ESPN URL hostname validation | Bad UUIDs return empty results from ESPN, no harm |
| Trade confirmation 60-sec window | Only you use the trader, and you have STOP |
| Monitor/trader state sync | Both are personal tools, not public-facing |

---

## Fix 8: Persist alert state to disk

**Status:** Implemented (2026-03-19)

**File:** `live_alerts.py`
**Problem:** `UserAlertState` (prev_odds, alerted_keys) was in-memory only. Every Railway deploy wiped it, causing: (1) odds movement detection needed 20-minute warmup (two Kalshi polls), (2) duplicate alerts for already-alerted game moments.

**What was built:**

- **`UserAlertState.save()`** — persists `alerted_keys` and `prev_odds` to `users/{chat_id}/alert_state.json` using atomic temp-file + `os.replace()` writes
- **`UserAlertState.load()`** — restores state from disk on startup. Falls back to fresh state if file missing or corrupt
- **Save trigger** — state writes to disk after processing each user when there are new alerts or fresh odds data (not every 30s loop iteration)
- **`alert_timestamps` stays in-memory** — rate limit state is short-lived, safe to reset on deploy

**Infrastructure:** Requires Railway persistent volume mounted at `/app/users`.

## Fix 9: Enrich user-facing alert messages with pick source context

**Status:** Implemented (2026-03-19)

**File:** `live_alerts.py`
**Problem:** User-facing alerts were bare ("odds are sliding") while the personal monitor had rich context about pick source. Users couldn't tell if a sliding pick was a bold model call or safe chalk.

**What was built:**

- **Odds movement** — messages now explain: model pick ("we overrode the market — worth watching"), user pick ("your pick differs from the model — market moving against it"), or chalk ("both liked them, market is softening")
- **Game resolution** — win/loss messages include source context: model pick wins ("our model saw the edge"), model pick losses ("model pick missed with X% gap"), user picks ("your pick paid off" / "tough break"), chalk ("no surprises" / "sometimes the madness wins")

