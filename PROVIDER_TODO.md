# PROVIDER_TODO.md — planned additions to the traider hub

Punch list of MCP providers to add, grouped by the gap each one fills.
All entries inherit the hub-wide rules in
[AGENTS.md](AGENTS.md): read-only, primary sources preferred, secrets
out of repo/logs, surface 429s, no silent fallbacks.

Status: `[ ]` todo · `[~]` in progress · `[x]` landed.

## Tier 1 — catalysts & fundamentals depth

- [x] **sec-edgar** — shipped on port 8768. Filings
  (10-K/10-Q/8-K/20-F), Form 4 insider transactions per issuer, 13F
  institutional portfolios per manager, XBRL company facts + frames.
  Primary source: `data.sec.gov` / `efts.sec.gov`. Auth: descriptive
  `SEC_EDGAR_USER_AGENT` only. Rate limit: 10 req/sec enforced
  client-side. See
  [src/traider/providers/sec_edgar/README.md](src/traider/providers/sec_edgar/README.md).
  Deferred from v1: Form 4 insider-scoped queries, 13F reverse
  lookup (who holds X?), submissions-feed overflow fan-out for deep
  history.
- [x] **earnings** — shipped as a provider module under the unified
  server (no separate port). Wraps Finnhub's free-tier
  ``/calendar/earnings`` (forward + backward earnings calendar with
  consensus EPS / revenue) and ``/stock/earnings`` (per-ticker
  historical actual-vs-estimate surprises). Primary source:
  `finnhub.io/api/v1`. Auth: ``FINNHUB_API_KEY`` as
  ``X-Finnhub-Token`` header. Rate limit: 60 req/min, propagates as
  ``FinnhubError``. Free-tier coverage is US-only; international
  calendar is paid and deliberately not wired. Dev notes in
  [DEVELOPING.md § earnings](DEVELOPING.md#earnings).
  Deferred: consensus guidance breakouts, analyst revisions (both
  paid-tier on Finnhub), alternative sources (Zacks RSS, Nasdaq
  Data Link).
- [x] **news** — shipped on port 8770. Wraps Massive's
  `/v2/reference/news` (ticker-scoped headlines with publisher
  metadata and per-article sentiment insights). Primary source:
  `api.massive.com`. Auth: `MASSIVE_API_KEY` as `apiKey` query param.
  Rate limits propagate as `MassiveError` (no silent retries).
  Intentionally narrow: Massive's quote / aggregate endpoints are
  *not* wrapped — quotes stay on the market-data backends. See
  [src/traider/providers/news/README.md](src/traider/providers/news/README.md).
  Sentiment is Massive's model output; quote it with attribution.

## Tier 2 — macro completion

- [ ] **bls** — BLS direct (CPI, NFP, JOLTS). FRED mirrors these but
  BLS is the primary publisher and releases a few minutes earlier.
  Worth it for release-day precision.
- [ ] **bea** — BEA direct (GDP components, personal income, trade
  balance). Same rationale as BLS.
- [x] **treasury** — shipped on port 8772. Treasury Fiscal Data
  (`api.fiscaldata.treasury.gov`) auction results (bid-to-cover,
  stop-out yield, primary-dealer takedown, indirect/direct bidder
  share), Daily Treasury Statement (eight tables — operating cash
  balance / TGA, deposits+withdrawals, public-debt transactions, …),
  debt-to-the-penny. No credentials. Yield curve routes to the `fred`
  provider (H.15: DGS1MO…DGS30, DFII real yields) — not duplicated
  here. See
  [src/traider/providers/treasury/README.md](src/traider/providers/treasury/README.md).
- [ ] **eia** — US Energy Information Administration: weekly
  petroleum status, natural gas storage, electricity. Critical for
  energy-name trades.
- [ ] **global-cb** — ECB SDW, BoJ, BoE statistical releases. Per
  hub rule: land one central bank at a time, each as its own module
  with its own primary-source client.

## Tier 3 — positioning & flow

- [ ] **cboe** — put/call ratios, VIX term structure, IV surfaces,
  total options volume. Fills the gap left by static option chains in
  the market-data backends.
- [ ] **finra** — short interest (bi-monthly), short sale volume
  (daily), ATS volume.
- [ ] **etf-flows** — ETF holdings, creations/redemptions, sector
  rotation signal. Candidates: ICI, ETF.com, issuer feeds (iShares,
  SPDR, Vanguard).
- [ ] **cftc** — Commitments of Traders (futures positioning by
  trader class). Weekly release. Primary source:
  `publicreporting.cftc.gov`.

## Tier 4 — risk / factor

- [x] **factor** — shipped on port 8771. Fama-French 3/5-factor,
  momentum, short/long-term reversal, and 5/10/12/17/30/38/48/49-
  industry portfolios at monthly and (where published) daily
  frequencies. Primary source: `mba.tuck.dartmouth.edu/…/ken.french/ftp/`.
  No credentials. Disk-cached with a 24 h TTL (`refresh=True` to
  override per-call). See
  [src/traider/providers/factor/README.md](src/traider/providers/factor/README.md).
  `get_dataset(filename)` is the escape hatch for the ~300 datasets
  outside the curated catalog (sort-based portfolios, international
  regional factors, etc.).

## Tier 5 — alt data (lower priority)

- [ ] **trends** — Google Trends interest-over-time for ticker- or
  theme-level attention signals.
- [ ] **social** — Reddit (`pushshift`/`reddit.com/.json`), X
  (requires paid tier post-2023). Sentiment is downstream of the data
  fetch — keep this provider to fetching, not scoring.
- [ ] **crypto** — CoinGecko (unauthenticated) or Binance public
  endpoints. Only add if the user starts asking crypto questions.

## Port allocation

Additive providers occupy contiguous ports to keep docker-compose
simple. Current + planned assignments:

| Port | Provider                   | Status  |
|-----:|----------------------------|---------|
| 8765 | schwab / yahoo (exclusive) | shipped |
| 8766 | fred                       | shipped |
| 8767 | fed-calendar               | shipped |
| 8768 | sec-edgar                  | shipped |
| 8769 | earnings                   | shipped (in-process on 8765) |
| 8770 | news                       | shipped |
| 8771 | factor                     | shipped |
| 8772 | treasury                   | shipped |
| …    | …                          | …       |

Claim the next free port when starting a new provider. Update this
table in the same commit.
