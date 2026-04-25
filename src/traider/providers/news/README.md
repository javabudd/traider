# news provider

Read-only [Massive](https://massive.com) news bridge. One of the
provider modules bundled in the unified
[`traider`](../../../../README.md) MCP server. See the root
[AGENTS.md](../../../../AGENTS.md) for hub-wide analyst rules and
[DEVELOPING.md § news](../../../../DEVELOPING.md#news) for dev
internals.

## Scope

Wraps exactly one Massive endpoint — `/v2/reference/news`. The rest
of Massive's surface (quotes, aggregates, trades, fundamentals) is
intentionally out of scope because the hub already has dedicated
backends. Pull quotes and history from `schwab` / `yahoo`; use this
provider for the catalyst / narrative layer.

## Tools

### `get_news(...)`

Recent news articles. Massive's response JSON is returned essentially
unchanged so the model can introspect raw fields rather than trust a
translation layer.

- `ticker` — case-sensitive ticker filter (e.g. `AAPL`). Omit for
  the cross-market feed.
- `published_after` / `published_before` — ISO date or RFC3339
  timestamp window. Maps to Massive's `published_utc.gte` /
  `published_utc.lte`.
- `limit` — 1–1000, default 10.
- `order` — `asc` or `desc`, default `desc` (newest first).
- `sort` — field to sort by, default `published_utc`.

Returns a `source` / `fetched_at` envelope wrapping Massive's
`status`, `count`, `results[]`, `next_url` (pagination cursor when
more rows exist), and `request_id`. Each result carries `title`,
`description`, `author`, `publisher` (`name`, `logo_url`,
`homepage_url`, `favicon_url`), `article_url`, `image_url`,
`amp_url`, `tickers`, `keywords`, `published_utc`, and an `insights`
array with per-ticker `sentiment` + `sentiment_reasoning`.

**Sentiment is Massive's model output**, not a primary-source fact —
quote it with attribution, don't present it as objective.

## Setup

1. Register at [massive.com](https://massive.com) and copy the API
   key (free tier is enough to start).
2. In `.env`: `MASSIVE_API_KEY=...`
3. Add `news` to `TRAIDER_PROVIDERS`.
4. Start the hub as normal — no separate port. Tools are exposed on
   the shared endpoint at `http://localhost:8765/mcp`.

## Coverage and limits

- **Ticker is case-sensitive.** Massive matches `ticker` exactly —
  use `AAPL`, not `aapl`.
- **Timestamps are RFC3339.** `published_utc` fields and filter
  inputs use full timestamps with timezone (e.g.
  `2026-04-18T13:30:00Z`). ISO dates also work for bounds.
- **Sentiment is a model output.** `insights[].sentiment` and
  `sentiment_reasoning` are Massive's labels, not ground truth.
  Attribute them and weigh them against primary-source reading of
  the article.
- **Pagination via `next_url`.** The response carries a pre-built
  cursor URL when more rows are available. The tool does not
  aggregate pages — follow the cursor in a second call if needed.
- **Rate limits.** Massive throttles per the tier on your key. 429s
  propagate as `MassiveError`; no silent retries, no fabricated
  headlines.

## Prompts that put this tool to work

- **"Why did NVDA move after the open today?"** —
  `get_news(ticker="NVDA", published_after="<today 13:30Z>")`,
  then cross-check the headline timestamps against the price action
  (`get_price_history` on the market-data backend).
- **"What's the latest on TSLA?"** —
  `get_news(ticker="TSLA", limit=20)`.
- **"Anything notable in the cross-market tape this morning?"** —
  `get_news(published_after="<today 13:30Z>", limit=50)`.
- **"Walk me through the last week of news for AAPL."** —
  `get_news(ticker="AAPL", published_after="<7d ago>", limit=100)`.
