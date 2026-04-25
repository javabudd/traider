# treasury provider

Read-only [Treasury Fiscal Data](https://fiscaldata.treasury.gov)
bridge. One of the provider modules bundled in the unified
[`traider`](../../../../README.md) MCP server. See the root
[AGENTS.md](../../../../AGENTS.md) for hub-wide analyst rules and
[DEVELOPING.md § treasury](../../../../DEVELOPING.md#treasury) for
dev internals.

## Scope — and what `fred` covers instead

This provider is the primary source for the pieces of Treasury data
that FRED does **not** carry:

- Treasury-securities auction results (bid-to-cover, bidder mix,
  stop-out yield).
- Daily Treasury Statement (operating cash balance / TGA, deposits
  and withdrawals, public-debt transactions, etc.).
- Debt to the penny (daily total public debt outstanding).

For **yield-curve queries** — the 2Y, 10Y, 30Y, TIPS real yields,
etc. — use the [`fred` provider](../fred/README.md). FRED mirrors
Treasury's H.15 Daily Treasury Yield Curve in full (`DGS1MO` …
`DGS30`, `DFII*`). Routing those through FRED keeps the mental model
simple: macro time-series via FRED, Treasury-primary-source data
(auctions, DTS, debt) via this provider.

## Tools

All tools return Fiscal Data's JSON essentially unchanged inside a
`source` / `fetched_at` envelope.

### `get_auction_results(...)`

Treasury-securities auction results. The default `fields` projection
covers what a trader actually reads when sizing demand for a
refunding: bid-to-cover, stop-out yield/rate, primary-dealer
takedown, direct vs indirect bidder share.

- `security_type` — `Bill`, `Note`, `Bond`, `CMB`, `TIPS`, or `FRN`.
  Omit for all.
- `security_term` — exact match, e.g. `4-Week`, `13-Week`, `2-Year`,
  `10-Year`, `30-Year`.
- `cusip` — exact CUSIP match.
- `start_date` / `end_date` — ISO `YYYY-MM-DD` bounds on
  `auction_date`. Default start is 90 days ago.
- `fields` — column projection. Omit for the curated default; pass
  your own list to pull any of the ~90 auctions_query columns (see
  Fiscal Data's
  [securities auctions dataset](https://fiscaldata.treasury.gov/datasets/securities-auctions-data)
  for the full schema).
- `limit`, `page`, `sort` — standard Fiscal Data paging / ordering.

### `get_daily_treasury_statement(...)`

Daily Treasury Statement. The DTS is broken into eight tables; pick
one via `table`:

| `table`                                             | What it is                                            |
|-----------------------------------------------------|-------------------------------------------------------|
| `operating_cash_balance` *(default)*                | TGA opening / closing balance, running totals         |
| `deposits_withdrawals_operating_cash`               | Line-item daily cash flows in/out of the TGA          |
| `public_debt_transactions`                          | Gross issuance / redemption by security class         |
| `adjustment_public_debt_transactions_cash_basis`    | Cash-basis adjustments to debt transactions           |
| `federal_tax_deposits`                              | Withheld taxes by category                            |
| `short_term_cash_investments`                       | Short-term investments (typically zero)               |
| `income_tax_refunds_issued`                         | Daily refund totals by refund type                    |
| `inter_agency_tax_transfers`                        | Trust-fund tax transfers                              |

Other params:

- `start_date` / `end_date` — ISO bounds on `record_date`. Default
  start is 30 days ago.
- `fields`, `limit`, `page`, `sort` — as above.

The DTS changed format in October 2022. This provider only talks to
the new-format JSON tables; queries spanning the old PDF format will
return only new-format rows.

### `get_debt_to_the_penny(...)`

Daily total public debt outstanding.

- `start_date` / `end_date` — ISO bounds on `record_date`. Default
  start is 60 days ago.
- `fields`, `limit`, `page`, `sort` — as above.

Response columns: `debt_held_public_amt` (market-held),
`intragov_hold_amt` (Social Security, Medicare trust funds, etc.),
`tot_pub_debt_out_amt` (headline total).

## Setup

No credentials required — Fiscal Data is unauthenticated.

1. Add `treasury` to `TRAIDER_PROVIDERS`.
2. Start the hub as normal — no separate port. Tools are exposed on
   the shared endpoint at `http://localhost:8765/mcp`.

## Coverage and limits

- **Unauthenticated, but still be polite.** Fiscal Data is
  rate-tolerant but not infinite. Tools paginate by default
  (`limit=100`); bump `limit` up to 10 000 if you're pulling a long
  window.
- **Amounts are strings.** Monetary fields come back as strings
  (e.g. `"847182563921.43"`) so precision isn't lost to float. Parse
  on the consumer side if you need to do arithmetic.
- **`auction_date` vs `record_date`.** Auctions are filtered on
  `auction_date` (when the sale happened). DTS and debt-to-the-penny
  are filtered on `record_date` (the date the statement covers).
- **DTS new-format only.** The 2022 format change broke the old
  tables' schema; this provider is wired to the new JSON tables. If
  you need pre-2022 DTS data, go to the PDF archive directly.
- **No fallback if upstream is down.** Fiscal Data errors raise
  `TreasuryError`. The provider does not silently serve stale data.

## Prompts that put these tools to work

- **"How was demand at yesterday's 10-year auction?"** —
  `get_auction_results(security_type="Note", security_term="10-Year",
  limit=1)` — check `bid_to_cover_ratio` and the dealer/indirect
  split.
- **"Is the TGA refilling after debt-ceiling resolution?"** —
  `get_daily_treasury_statement(table="operating_cash_balance",
  start_date="<event-date>")` — look at the balance trajectory.
- **"What's today's total public debt?"** —
  `get_debt_to_the_penny(limit=1)`.
- **"How has bill demand held up over the last quarter?"** —
  `get_auction_results(security_type="Bill",
  start_date="<90d ago>", limit=500)`, then aggregate
  `bid_to_cover_ratio` by `security_term`.
- **"What's the 10-year yield?"** — **not this provider.** Use the
  `fred` provider's `get_series("DGS10")`.

Pair these with the `fred` provider to condition on macro-release
timing, and with `schwab` / `yahoo` when you're sizing equity or
option trades around a Treasury refunding week.
