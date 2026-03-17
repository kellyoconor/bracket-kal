# ESPN API Research: NCAA Men's Basketball Live Scores

## 1. Endpoint URL

```
https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard
```

Confirmed working as of 2026-03-16. Returns JSON.

## 2. Authentication

**None required.** No API key, no OAuth, no tokens. Plain HTTP GET requests work.
This is an unofficial/undocumented ("hidden") API that powers ESPN's own website and apps.

**Warning:** Because it is unofficial, ESPN can change or remove it at any time without notice.

## 3. Response Format

### Top-level structure

```json
{
  "leagues": [...],
  "groups": {...},
  "day": {...},
  "events": [...],      // <-- array of games
  "provider": {...},
  "eventsDate": {...}
}
```

### Per-game structure (each item in `events[]`)

```
events[i].id                                        -> "401856435" (game ID)
events[i].name                                      -> "Purdue Boilermakers at Michigan Wolverines"
events[i].date                                      -> "2026-03-15T20:00Z" (ISO 8601)
events[i].status.type.name                          -> "STATUS_FINAL" | "STATUS_IN_PROGRESS" | "STATUS_SCHEDULED" | "STATUS_HALFTIME"
events[i].status.type.description                   -> "Final" | "In Progress" | "Scheduled" | "Halftime"
events[i].status.type.state                         -> "post" | "in" | "pre"
events[i].status.displayClock                       -> "12:34" (formatted clock string)
events[i].status.period                             -> 1 | 2 (current half for college basketball)

events[i].competitions[0].competitors[0]            -> one team (check .homeAway)
events[i].competitions[0].competitors[1]            -> other team (check .homeAway)

events[i].competitions[0].competitors[n].homeAway   -> "home" | "away"
events[i].competitions[0].competitors[n].score       -> "72" (string)
events[i].competitions[0].competitors[n].team.id             -> "2509"
events[i].competitions[0].competitors[n].team.displayName    -> "Purdue Boilermakers"
events[i].competitions[0].competitors[n].team.shortDisplayName -> "Purdue"
events[i].competitions[0].competitors[n].team.abbreviation   -> "PUR"
events[i].competitions[0].competitors[n].team.logo           -> URL to team logo

events[i].competitions[0].venue.fullName            -> "UD Arena"
events[i].competitions[0].status.period             -> 2
events[i].competitions[0].status.displayClock       -> "0:00"
```

### Game status values

| status.type.state | status.type.name        | status.type.description | Meaning          |
|-------------------|-------------------------|-------------------------|------------------|
| `"pre"`           | `STATUS_SCHEDULED`      | `"Scheduled"`           | Not started      |
| `"in"`            | `STATUS_IN_PROGRESS`    | `"In Progress"`         | Game is live     |
| `"in"`            | `STATUS_HALFTIME`       | `"Halftime"`            | Halftime break   |
| `"post"`          | `STATUS_FINAL`          | `"Final"`               | Game over        |

### Additional data available per game

- `events[i].odds[0].spread` -> point spread (e.g., 1.5)
- `events[i].odds[0].overUnder` -> over/under line (e.g., 139.5)
- Linescores (period-by-period scoring) nested within competitors
- Venue information
- Season type info (`events[i].season.type.name`)

## 4. Update Frequency

**Not officially documented.** Based on community reports:
- The endpoint reflects score changes with approximately **~200ms latency** once polled.
- The API itself does not push updates; you must poll it.
- Recommended polling interval: **every 15-30 seconds** for live games. More frequent is possible but risks rate limiting.
- For pre-game or post-game states, polling every 1-5 minutes is sufficient.

## 5. Filtering Options

### By date
```
?dates=20260315
```
Format: `YYYYMMDD`. Omit the parameter to get today's games.

### Get all Division I games (not just featured)
```
?groups=50&limit=365
```
- `groups=50` includes all D1 conferences
- `limit=365` ensures you get every game (default limit is lower)

### By season type
```
?seasontype=3
```
- `1` = preseason
- `2` = regular season
- `3` = postseason (March Madness)

### Combined example
```
https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?dates=20260316&groups=50&limit=365
```

### Filter by specific game
There is no direct "game ID" filter on the scoreboard endpoint. Instead, use the event endpoint:
```
https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event=401856435
```
This returns full detail for a single game including play-by-play and boxscore.

## 6. Rate Limits

**No official rate limits are published.** Practical guidance:
- No published throttle numbers exist.
- Excessive automated requests may be blocked by IP.
- Community consensus: keep polling to a reasonable interval (10-30 seconds for live, minutes for idle).
- Implement caching and exponential backoff on errors.
- ESPN may block or throttle without warning.

## Quick Start: Fetch Today's Scores

```bash
curl -s "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard" | jq '.events[] | {name: .name, status: .status.type.description, clock: .status.displayClock, period: .status.period}'
```

## Related Endpoints

| Endpoint | URL |
|----------|-----|
| Scoreboard (today) | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard` |
| Scoreboard (by date) | `...scoreboard?dates=YYYYMMDD` |
| Game summary | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary?event={id}` |
| Teams list | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams` |
| Team detail | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{id}` |
| Rankings | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/rankings` |
| News | `site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/news` |
