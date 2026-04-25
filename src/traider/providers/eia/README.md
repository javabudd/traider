# eia provider

Read-only [US Energy Information Administration](https://www.eia.gov)
v2 API bridge. One of the provider modules bundled in the unified
[`traider`](../../../../README.md) MCP server. See the root
[AGENTS.md](../../../../AGENTS.md) for hub-wide analyst rules and
[DEVELOPING.md § eia](../../../../DEVELOPING.md#eia) for dev internals.

## Scope

Three curated routes — the ones a trader actually reaches for — plus
a generic escape hatch:

- **Weekly Petroleum Status Report** (`/petroleum/stoc/wstk/`) —
  crude / gasoline / distillate ending stocks. Released Wednesdays
  at 10:30 ET; the headline print drives WTI, Brent, and energy-
  name equities.
- **Weekly Natural Gas Storage** (`/natural-gas/stor/wkly/`) —
  EIA-912 working gas in underground storage. Released Thursdays at
  10:30 ET; drives Henry Hub futures and utility names.
- **Electric Power Operational Data** (`/electricity/electric-power-
  operational-data/`) — monthly net generation by state, sector,
  and fuel type. Slower-moving but the canonical reference for
  utility fuel-mix analysis.
- **Generic EIA v2** — `get_eia_series` against any route on
  https://www.eia.gov/opendata/browser/ for retail gasoline prices,
  crude imports by origin, hourly grid data, etc.

## Tools

All tools return EIA's JSON essentially unchanged inside a `source`
/ `fetched_at` envelope. EIA wraps results under `response.data[]`
plus paging metadata (`response.total`, `response.dateFormat`).

### `get_petroleum_weekly_stocks(...)`

WPSR ending stocks. Default series projection: total crude
(ex-SPR), SPR, Cushing OK, total motor gasoline, distillate fuel
oil. Pass `series=[...]` to widen the projection.

- `series` — EIA series IDs (e.g. `WCESTUS1`). Catalog at
  https://www.eia.gov/opendata/browser/petroleum/stoc/wstk.
- `start_date` / `end_date` — ISO `YYYY-MM-DD` bounds on `period`.
- `limit` — page size, max 5000.
- `offset` — 0-indexed paging offset.

Stocks are reported in **thousand barrels** (`MBBL`).

### `get_natural_gas_storage(...)`

EIA-912 working gas in underground storage. Default projection:
Lower 48 total plus the five regional splits (East / Midwest /
South Central / Mountain / Pacific).

- `series` — EIA series IDs (e.g. `NW2_EPG0_SWO_R48_BCF`). For
  salt vs non-salt South Central splits, use the catalog at
  https://www.eia.gov/opendata/browser/natural-gas/stor/wkly.
- `start_date` / `end_date`, `limit`, `offset` — as above.

Values in **billion cubic feet** (`BCF`).

### `get_electricity_generation(...)`

Net generation by state, sector, and fuel type.

- `location` — 2-letter state code or `US`.
- `sectorid` — `99` (all), `1` (electric utility), `2` (IPP non-cogen),
  `3` (IPP cogen), ...
- `fueltypeid` — `ALL`, `COW` (coal), `NG` (natural gas), `NUC`
  (nuclear), `HYC` (conventional hydro), `WND` (wind), `SUN`
  (solar), `PEL` (petroleum liquids), `BIO` (biomass).
- `frequency` — `monthly` *(default)*, `quarterly`, or `annual`.
- `start_date` / `end_date` — ISO `YYYY-MM` (monthly) or `YYYY`
  (annual) bounds on `period`.
- `limit`, `offset` — paging.

Generation reported in **thousand megawatt-hours** (`MWh × 1000`).

For hourly grid data (demand / generation / interchange by
balancing authority), use `get_eia_series` against
`/electricity/rto/region-data/data/`.

### `get_eia_series(...)`

Generic escape hatch for any EIA v2 route.

- `route` — EIA v2 path including trailing `/data/`
  (e.g. `/petroleum/pri/spt/data/`).
- `data` — column projection (most routes use `["value"]`; some
  named columns).
- `facets` — `{facet_name: [values]}` map of categorical filters.
- `frequency` — frequency code if the route supports multiple.
- `start_date` / `end_date` — ISO bounds on `period`.
- `sort_column` / `sort_direction` — sort key (default
  `period desc`).
- `limit`, `offset` — paging.

## Setup

1. Register at https://www.eia.gov/opendata/register.php and copy
   the API key (free, email-issued, no rate-tier required).
2. In `.env`: `EIA_API_KEY=...`
3. Add `eia` to `TRAIDER_PROVIDERS`.
4. Start the hub as normal — no separate port. Tools are exposed on
   the shared endpoint at `http://localhost:8765/mcp`.

## Coverage and limits

- **Rate limit.** EIA documents 5,000 requests per hour per API key.
  429s propagate as `EiaError`; no silent retries.
- **Page size cap is 5000.** EIA v2 caps `length` at 5000 rows.
  Large windows need pagination via `offset`.
- **Series IDs change rarely.** EIA series naming
  (`WCESTUS1`, `NW2_EPG0_SWO_R48_BCF`, …) is stable; if a curated
  series stops returning data, verify against the EIA Open Data
  Browser before assuming the API broke.
- **Units vary by route.** Always check the `units` field on each
  row. Petroleum stocks are `MBBL` (thousand barrels), gas storage
  is `BCF` (billion cubic feet), electricity generation is
  thousand-MWh — but other EIA routes report different units even
  for the same physical quantity.
- **`period` granularity matches frequency.** Weekly = `YYYY-MM-DD`
  (Friday-ending). Monthly = `YYYY-MM`. Annual = `YYYY`. Filter
  bounds need to match the route's frequency.
- **No fallback if upstream is down.** Errors raise `EiaError`.
  This provider does not silently serve stale data or substitute a
  different source.

## Prompts that put these tools to work

- **"What did the petroleum status report show this week?"** —
  `get_petroleum_weekly_stocks(limit=10)` to compare the most-recent
  print against the prior weeks across the headline series.
- **"How does natgas storage compare to the 5-year average right
  now?"** —
  `get_natural_gas_storage(start_date="<5y ago>")`, then aggregate
  the Lower-48 series by week-of-year.
- **"What share of US generation came from coal vs natural gas in
  the last year?"** — `get_electricity_generation(location=["US"],
  fueltypeid=["COW", "NG"], start_date="<13mo ago>")`.
- **"Pull WTI and Brent spot prices for the last quarter."** —
  `get_eia_series(route="/petroleum/pri/spt/data/",
  facets={"product": ["EPCWTI", "EPCBRENT"]},
  frequency="daily", start_date="<90d ago>")`.
- **"Hourly demand on ERCOT yesterday."** —
  `get_eia_series(route="/electricity/rto/region-data/data/",
  facets={"respondent": ["ERCO"], "type": ["D"]},
  frequency="hourly", start_date="<yesterday>", end_date="<today>")`.

Pair these with `fred` for headline-CPI / GDP context, with
`schwab` / `yahoo` for the energy-name price action that catalysts
move, and with `news` to anchor the move to a specific headline.
