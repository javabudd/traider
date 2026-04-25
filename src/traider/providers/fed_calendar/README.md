# fed-calendar provider

Read-only Federal Reserve **FOMC meeting calendar** scraped from the
Fed's own page at
<https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm>.
One of the provider modules bundled in the unified
[`traider`](../../../../README.md) MCP server. See the root
[AGENTS.md](../../../../AGENTS.md) for hub-wide analyst rules and
[DEVELOPING.md § fed-calendar](../../../../DEVELOPING.md#fed-calendar)
for dev internals.

The Fed publishes no JSON or ICS feed for this calendar; the scraper
returns structured records and fails loudly rather than guess if the
markup changes.

## Scope

Calendar dates and per-meeting flags only — no statement bodies, no
projections content. For statement / minutes / presser **content**,
follow the URLs returned in each meeting's record (or use the `fred`
provider's release-101 series for publication timing). For market
reaction, pair with `schwab` / `yahoo`.

## Tools

### `get_fomc_meetings(year=None, upcoming_only=False)`

Every FOMC meeting listed on the Fed's calendar page. Each meeting:

```json
{
  "year": 2026,
  "month": "January",
  "day_range": "27-28",
  "start_date": "2026-01-27",
  "end_date": "2026-01-28",
  "is_sep": true,
  "has_press_conference": true,
  "note": null,
  "statement_url": "https://www.federalreserve.gov/newsevents/...",
  "minutes_url": "https://www.federalreserve.gov/monetarypolicy/...",
  "press_conference_url": "https://www.federalreserve.gov/monetarypolicy/fomcpressconf20260128.htm"
}
```

- `is_sep` — Summary of Economic Projections (dot plot) released
  with this meeting.
- `has_press_conference` / `press_conference_url` — set when the Fed
  has posted the press-conference permalink (happens a few days
  before the meeting). Absence on a future meeting doesn't mean no
  presser — every FOMC meeting since 2019 has had one; the flag just
  tracks when the URL lands on the page.
- `note` — parenthetical on the date cell, if any (e.g.
  `"notation vote"`, `"unscheduled"`, `"conference call"`).
- `upcoming_only=True` drops meetings whose `end_date` is in the
  past.

Returns a `source` / `fetched_at` envelope plus `count` and a
`meetings` list.

### `get_next_fomc_meeting()`

Convenience wrapper — returns the first meeting on or after today
(UTC), with `days_until_start`. `meeting` is `null` if the Fed page
doesn't list a future meeting yet.

## Setup

No credentials required.

1. Add `fed-calendar` to `TRAIDER_PROVIDERS`.
2. Start the hub as normal — no separate port. Tools are exposed on
   the shared endpoint at `http://localhost:8765/mcp`.

## Coverage and limits

- **Primary source, HTML scrape.** When federalreserve.gov reshapes
  its markup (rare but possible), the scraper raises rather than
  returning a guess — update the scraper, don't paper over it.
- **Two-month meetings.** Meetings sometimes span April/May or
  October/November. `start_date` anchors to the first month and
  `end_date` to the second.
- **Unscheduled / notation-vote rows** are surfaced with a non-null
  `note`. Rows that don't carry a date at all (rare, purely
  parenthetical "unscheduled" placeholders) are skipped — they have
  no date to anchor to.
- **Timezone.** "Today" and `days_until_start` are computed in UTC.
  FOMC decisions are released in ET; on the edges the two can differ
  by a few hours. The response includes `fetched_at` in UTC so the
  model can reason about it explicitly.
- **No silent cache.** Every tool call refetches the page. If that
  becomes a rate-limit concern, the tool will grow an explicit TTL
  field in the response — but it won't lie about freshness.

## Prompts that put this tool to work

- **"When's the next FOMC meeting and is it a dot-plot meeting?"** —
  `get_next_fomc_meeting()`, check `is_sep`.
- **"List all 2026 FOMC meetings."** — `get_fomc_meetings(year=2026)`.
- **"Anything happening in the next two weeks on the Fed side?"** —
  `get_fomc_meetings(upcoming_only=True)` and filter by
  `start_date`.

Pair with the `fred` provider for *content* (statement text timing
via release `101`, rate-decision series like `FEDFUNDS`) and with
`schwab` / `yahoo` for market reaction around the meeting window.
