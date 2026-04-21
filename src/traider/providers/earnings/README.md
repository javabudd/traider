# earnings provider

Read-only [Finnhub](https://finnhub.io/docs/api) earnings-calendar
bridge. One of the provider modules bundled in the unified
[`traider`](../../../../README.md) MCP server. See the root
[AGENTS.md](../../../../AGENTS.md) for hub-wide analyst rules and
[DEVELOPING.md § earnings](../../../../DEVELOPING.md#earnings) for
dev internals.

## Scope

Wraps exactly two Finnhub endpoints, both on the free tier:

- `/calendar/earnings` — forward- and backward-looking earnings
  calendar with consensus EPS / revenue.
- `/stock/earnings` — per-ticker history of EPS actual vs. estimate
  (surprise %).

Quotes, fundamentals, sentiment, and recommendation trends are
intentionally out of scope — the hub already has dedicated providers
for quotes (`schwab` / `yahoo`), filings (`sec-edgar`), and news
(`news`).

## Tools

### `get_earnings_calendar(from_date=None, to_date=None, symbol=None)`

Upcoming (and recent) earnings announcements with consensus.

- `from_date` — ISO `YYYY-MM-DD`. Defaults to today (UTC).
- `to_date` — ISO `YYYY-MM-DD`. Defaults to `from_date + 14` days.
- `symbol` — ticker (e.g. `AAPL`) to narrow to one issuer. Omit for
  the cross-market calendar over the window.

Returns a `source` / `fetched_at` envelope plus Finnhub's
`earningsCalendar` list unchanged. Each entry carries `symbol`,
`date`, `hour` (`bmo`/`amc`/`dmh`/`""`), `year`, `quarter`,
`epsEstimate`, `epsActual`, `revenueEstimate`, `revenueActual`.
Actuals are `null` for future reports.

### `get_earnings_surprises(symbol, limit=None)`

Historical quarterly EPS actual vs. consensus for one ticker.

- `symbol` — ticker (required).
- `limit` — max quarters to return; omit for Finnhub's default.

Returns a `source` / `fetched_at` envelope and an `earnings` list
(newest-first). Each entry carries `actual`, `estimate`, `surprise`,
`surprisePercent`, `period`, `quarter`, `year`, `symbol`.

## Setup

1. Register at [finnhub.io](https://finnhub.io) and copy the API
   key.
2. In `.env`: `FINNHUB_API_KEY=...`
3. Add `earnings` to `TRAIDER_PROVIDERS`.
4. Start the hub as normal — no separate port. Tools are exposed on
   the shared endpoint at `http://localhost:8765/mcp`.

## Coverage and limits

- **Free tier is US issuers.** International coverage is paid and
  not wired.
- **Rate limit: 60 requests/minute.** 429s propagate as
  `FinnhubError`; no silent retries.
- **Consensus is Finnhub's aggregation** of sell-side estimates, not
  a primary source. Quote with attribution. Actuals (`epsActual` /
  `revenueActual`) come from the issuer's 8-K / earnings release and
  *are* primary.

## Prompts that put this tool to work

- **"When do my positions report?"** —
  `get_earnings_calendar(symbol="NVDA")`,
  `get_earnings_calendar(symbol="AAPL")`, etc., per ticker.
- **"Who reports this week?"** —
  `get_earnings_calendar(from_date="<Mon>", to_date="<Fri>")` for
  the full cross-market tape (can be large).
- **"Is NVDA a serial beater?"** —
  `get_earnings_surprises(symbol="NVDA")` and look at
  `surprisePercent` across the last four quarters.
- **"What's consensus for AAPL this quarter?"** —
  `get_earnings_calendar(symbol="AAPL")` and read `epsEstimate` /
  `revenueEstimate` on the next-dated row.
