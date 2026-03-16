# Kalshi API Research: NCAA March Madness Prediction Market Data

**Date:** 2026-03-16
**Purpose:** Technical reference for pulling NCAA tournament prediction market odds

---

## 1. Base URL

**Production (all markets, not just elections despite the subdomain):**
```
https://api.elections.kalshi.com/trade-api/v2
```

**WebSocket:**
```
wss://api.kalshi.com/trade-api/ws/v2
```

**Demo/Sandbox (more generous rate limits for development):**
```
https://demo-api.kalshi.co/trade-api/v2
```

> IMPORTANT: The `elections` subdomain is misleading -- it provides access to ALL
> Kalshi markets including sports, weather, economics, etc. This is the canonical
> production base URL per their official docs.

---

## 2. Authentication Requirements

### Public (No Auth) Endpoints -- READ-ONLY MARKET DATA

The following endpoints require NO authentication headers:

- `GET /markets` -- list/filter markets
- `GET /markets/{ticker}` -- single market details
- `GET /markets/{ticker}/orderbook` -- orderbook depth
- `GET /events/{event_ticker}` -- event details with nested markets
- `GET /series/{series_ticker}` -- series info

This is explicitly stated in their "Quick Start: Market Data (No SDK)" guide:
*"No authentication headers are required for the endpoints in this guide."*

### Authenticated Endpoints -- TRADING

Trading endpoints (orders, portfolio, etc.) require RSA-PSS signed headers:

```
KALSHI-ACCESS-KEY: <your Key ID>
KALSHI-ACCESS-TIMESTAMP: <request timestamp in milliseconds>
KALSHI-ACCESS-SIGNATURE: <RSA-PSS SHA256 signature of: timestamp + method + path>
```

Key generation: https://kalshi.com/account/profile -> "API Keys" section.
Private key is shown once and never stored by Kalshi.

### Multivariate Lookup Endpoint

`PUT /multivariate_event_collections/{collection_ticker}/lookup` -- this one
DOES require authentication (all three signed headers).

---

## 3. Endpoints for NCAA Tournament / March Madness Markets

### Strategy: Series -> Events -> Markets hierarchy

Kalshi organizes data in a three-level hierarchy:
- **Series** = broad category (e.g., March Madness championship)
- **Event** = specific occurrence within a series (e.g., 2026 championship)
- **Market** = individual tradeable contract (e.g., "Duke wins championship")

### Key Endpoints

#### A. List all open markets for a series
```
GET /markets?series_ticker=KXMARMAD&status=open
```

#### B. Get a specific event with all its nested markets
```
GET /events/{event_ticker}?with_nested_markets=true
```

#### C. Get a single market by ticker
```
GET /markets/{ticker}
```

#### D. Get orderbook for a market (bid/ask depth)
```
GET /markets/{ticker}/orderbook
```

#### E. Get series metadata
```
GET /series/KXMARMAD
```

### Known NCAA March Madness Series/Event Tickers

From the Kalshi website URLs observed:

| Ticker | Description | URL Pattern |
|--------|-------------|-------------|
| `KXMARMAD` | March Madness Championship (who wins it all) | `/markets/kxmarmad/march-madness` |
| `KXMARMAD-26` | 2026 Championship event | `/markets/kxmarmad/.../kxmarmad-26` |
| `KXMARMAD1SEED` | March Madness 1-seeds prop markets | `/markets/kxmarmad1seed/march-madness-1-seeds` |
| `KXMARMAD1SEED-26` | 2026 1-seeds event | `/markets/kxmarmad1seed/.../kxmarmad1seed-26` |

The ticker convention appears to be:
- Series: `KX` prefix + abbreviated name (e.g., `KXMARMAD`)
- Event: Series ticker + `-YY` year suffix (e.g., `KXMARMAD-26`)
- Market: Event ticker + team/outcome suffix (exact format TBD, needs live API call)

### Query Parameters for GET /markets

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_ticker` | string | Filter by single event |
| `series_ticker` | string | Filter by series |
| `tickers` | string | Comma-separated market tickers |
| `status` | enum | `unopened`, `open`, `paused`, `closed`, `settled` |
| `limit` | int | 1-1000 (default 100) |
| `cursor` | string | Pagination cursor |
| `min_close_ts` | int | Min close timestamp |
| `max_close_ts` | int | Max close timestamp |

---

## 4. Response Format -- Win Probabilities

### Prices ARE Probabilities

Kalshi contracts pay $1.00 if the outcome occurs, $0.00 if it does not.
Therefore, all dollar prices directly represent implied probabilities.

**A price of `"0.2100"` for yes_bid_dollars means a 21% implied probability.**

### Market Object Fields (key fields for our use case)

```json
{
  "market": {
    "ticker": "KXMARMAD-26-DUKE",
    "event_ticker": "KXMARMAD-26",
    "market_type": "binary",
    "title": "Duke wins NCAA Championship",

    "yes_bid_dollars": "0.2100",
    "yes_ask_dollars": "0.2200",
    "no_bid_dollars": "0.7800",
    "no_ask_dollars": "0.7900",
    "last_price_dollars": "0.2100",

    "previous_yes_bid_dollars": "0.1900",
    "previous_yes_ask_dollars": "0.2000",
    "previous_price_dollars": "0.1900",

    "volume_fp": "15000.00",
    "volume_24h_fp": "2500.00",
    "open_interest_fp": "8000.00",

    "yes_bid_size_fp": "100.00",
    "yes_ask_size_fp": "150.00",

    "status": "active",
    "result": "",
    "settlement_value_dollars": "",

    "open_time": "2025-11-01T00:00:00Z",
    "close_time": "2026-04-08T00:00:00Z",
    "created_time": "2025-10-15T00:00:00Z",

    "rules_primary": "This market resolves Yes if Duke wins...",
    "rules_secondary": ""
  }
}
```

> NOTE: The ticker `KXMARMAD-26-DUKE` above is illustrative. Actual individual
> market tickers need to be discovered via API calls. The exact team-level suffix
> format is not documented -- you must call GET /markets?event_ticker=KXMARMAD-26
> to discover all available market tickers.

### Price Format Details

- All prices are `FixedPointDollars` -- string representation with up to 6 decimal places
- Example: `"0.210000"` or `"0.21"`
- To convert to probability percentage: parse as float, multiply by 100
- Volume uses `FixedPointCount` with 2 decimal places (e.g., `"10.00"`)

### Orderbook Response

```json
{
  "orderbook_fp": {
    "yes_dollars": [
      ["0.2100", "50.00"],
      ["0.2000", "100.00"]
    ],
    "no_dollars": [
      ["0.7800", "75.00"],
      ["0.7700", "120.00"]
    ]
  }
}
```

Each entry is `[price_dollars, count_fp]`.

---

## 5. Market Identification -- Ticker Format

### Hierarchy

```
Series (KXMARMAD)
  -> Event (KXMARMAD-26)
    -> Market (individual contract per team/outcome)
```

### Observed Patterns

- Series tickers: `KX` + category abbreviation (e.g., `KXMARMAD`, `KXCBB`)
- Event tickers: series + `-YY` for year
- Market tickers: varies, must be discovered via API

### Discovery Workflow

1. Call `GET /series/KXMARMAD` to confirm the series exists
2. Call `GET /markets?series_ticker=KXMARMAD&status=open` to get all active markets
3. Each market in the response will have its `ticker`, `event_ticker`, and `title`
4. Use `GET /events/{event_ticker}?with_nested_markets=true` for grouped view

### Event Fields

- `event_ticker`, `series_ticker`
- `title`, `sub_title`
- `category`
- `mutually_exclusive` (boolean -- important for championship markets)
- `strike_date` or `strike_period`
- `markets` array (when `with_nested_markets=true`)

---

## 6. Rate Limits

### Tiers

| Tier | Read Limit | Write Limit | Qualification |
|------|-----------|-------------|---------------|
| Basic | 20 req/sec | 10 req/sec | Account signup |
| Advanced | 30 req/sec | 30 req/sec | Application form |
| Premier | 100 req/sec | 100 req/sec | 3.75% volume threshold |
| Prime | 400 req/sec | 400 req/sec | 7.5% volume threshold |

- All market data reads (GET endpoints) count toward the **read** limit
- Only 6 trading endpoints count toward **write** limit
- Basic tier (20 reads/sec) is sufficient for our use case
- Demo environment at `demo-api.kalshi.co` has more generous limits for testing

### API Key Requirements Summary

- **Reading market data: NO API KEY NEEDED**
- Trading (placing orders): RSA-PSS signed authentication required
- Multivariate lookup: Authentication required

---

## Quick Start: Fetching March Madness Odds

### Minimal curl examples (no auth required):

```bash
# 1. Get series info
curl -s "https://api.elections.kalshi.com/trade-api/v2/series/KXMARMAD"

# 2. Get all open March Madness markets
curl -s "https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker=KXMARMAD&status=open&limit=200"

# 3. Get a specific event with nested markets
curl -s "https://api.elections.kalshi.com/trade-api/v2/events/KXMARMAD-26?with_nested_markets=true"

# 4. Get orderbook for a specific market (replace ticker)
curl -s "https://api.elections.kalshi.com/trade-api/v2/markets/KXMARMAD-26-DUKE/orderbook"
```

### Converting response to probability:

```python
import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"

resp = requests.get(f"{BASE}/markets", params={
    "series_ticker": "KXMARMAD",
    "status": "open",
    "limit": 200
})

for market in resp.json()["markets"]:
    title = market["title"]
    prob = float(market["last_price_dollars"]) * 100
    print(f"{title}: {prob:.1f}%")
```

---

## Known March Madness Market Types on Kalshi (2026)

1. **Championship Winner** (`KXMARMAD`) -- Who wins the national title
2. **1-Seed Props** (`KXMARMAD1SEED`) -- Will a 1-seed win, etc.
3. **Individual Game Matchups** -- Likely under different series tickers (check `KXCBB` or similar)
4. **Conference Champions** -- Pre-tournament conference winner markets
5. **Bracket Props** -- First-round upsets, Final Four seed sums, etc.

### Important Note on Individual Game Markets

Championship futures are well-documented, but individual game-by-game matchup
markets may use different series tickers. You will need to explore the API or
the Kalshi website to discover the exact tickers for round-by-round game markets.
The tag page at kalshi.com/tag/march-madness may help identify all related series.

---

## Sources

- Official Docs: https://docs.kalshi.com/welcome
- Quick Start (Market Data): https://docs.kalshi.com/getting_started/quick_start_market_data
- API Reference (Markets): https://docs.kalshi.com/api-reference/market/get-markets
- API Reference (Events): https://docs.kalshi.com/api-reference/events/get-event
- Rate Limits: https://docs.kalshi.com/getting_started/rate_limits
- API Keys: https://docs.kalshi.com/getting_started/api_keys
