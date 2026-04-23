# OPTIONS.md — options analysis methodology

Load this when the user is analyzing an option chain, evaluating an
option structure, or sizing/timing an option trade. Options carry
specialized mental models (greeks, IV rank, assignment, pin risk)
that recall-from-training gets wrong easily — the rules below are
the anchor.

`RISK.md` still governs sizing and portfolio-level risk once the
trade is defined; this file is the options-specific layer on top.
If the user states a different framework (their own IV thresholds,
their own allowed structures), use theirs and note the swap.

## Verify the chain before citing anything

`AGENTS.md` flags option marks as model prices; this is the expanded
rule. Before quoting any option P&L, fill price, or greek-derived
inference, verify:

- **Bid-ask spread width.** A spread wider than ~10% of the mark on
  a single-name OTM option is a yellow flag; wider than 20% and the
  mark is fiction. Index options (SPX, SPY, QQQ) normally trade at
  1–3% spreads; anything wider on those is a data or session issue.
- **Bid/ask sizes.** Single-digit contracts on either side means
  the top of book is a stub — a real trader can't transact at that
  price. Watch for 1×1 on OTM single-names.
- **Recent trade + volume.** A mark with zero volume today and no
  recent print has no real-world anchor. Prefer strikes with
  confirmed volume when presenting levels.
- **Open interest.** Low OI (< 100) means even if the user enters,
  the exit may be illiquid. Complex structures on low-OI chains are
  a setup for slippage.
- **Session.** Options do not trade in extended hours. Any chain
  pulled before 9:30 ET or after 16:00 ET has stale quotes — bids
  routinely drop to stubs post-close. Say so before citing numbers.

When the spread is wide or the bid is a stub, the user's realistic
exit is closer to the bid (closing longs) or ask (closing shorts),
not the mark. Cite *both* the mark and the likely fillable level.

## IV context: rank, percentile, term, skew

Implied vol gives dimension to a chain that raw price can't. Before
recommending a long-premium or short-premium structure, establish
the IV context.

- **IV vs HV.** Compare 30d implied to 30d realized. Rich IV (IV >
  HV by a meaningful margin) favors selling premium; cheap IV
  (IV < HV) favors buying.
- **IV rank** (current IV vs its 52w range, 0–100): simple and
  robust. Rank > 50 → premium selling has historical tailwind;
  rank < 30 → premium buying is relatively cheap.
- **IV percentile** (share of days in the past year IV was below
  current): less sensitive to a single spike than rank. Useful when
  rank looks extreme because of one outlier.
- **Term structure.** Normal market = contango (further-dated IV >
  near-dated). Backwardation flags event risk or stress; favor
  calendars selling the front in that regime.
- **Skew.** Put skew is normal in equity (crash fear priced in).
  Extreme single-name put skew suggests hedging flow or a catalyst
  the options market sees that the user may not — flag it.

Don't cite "IV is high/low" without grounding. Always name rank,
percentile, or a HV comparison.

## Greeks: what each is for

- **Delta** — directional exposure. Rough rule: delta ≈ probability
  of finishing ITM at expiry, *but only roughly* (ignores skew,
  biased under high vol). For sizing a hedge, use delta directly;
  for probability claims, caveat it.
- **Gamma** — delta's rate of change. Peaks ATM near expiry. Short-
  gamma positions (short options, iron condors) lose fast when
  price runs through strikes late in the cycle — pin risk.
- **Theta** — daily decay. Accelerates inside 30–45 DTE for ATM
  options. Long premium pays theta; short premium collects it.
- **Vega** — IV sensitivity. Long premium = long vega. Vega shrinks
  into expiry — a 7-DTE option barely reacts to IV moves.
- Higher-order greeks (charm, vanna, volga): mostly ignore unless
  the user asks specifically.

Greek values from the chain are model-derived (Black-Scholes
variants); treat them as approximations, not truths.

## Structure selection

Match the structure to the view, not the other way around.

- **Directional, defined risk:**
  - *Long option* — uncapped upside, pays theta, needs a decent
    move and/or IV expansion. Best when IV is cheap and the move
    is expected soon.
  - *Debit spread* — capped upside, lower theta and vega. Best when
    IV is rich and the move is expected within a defined window.
- **Income / range-bound:**
  - *Credit spread* — defined risk, positive theta, short vega.
    Sized off `(width − credit) × 100`, not off the credit.
  - *Iron condor* — credit spreads on both sides; profits if the
    underlying stays in a range and IV doesn't spike.
- **Volatility:**
  - *Long straddle/strangle* — event bet; needs move > implied.
  - *Short straddle/strangle* — range bet with undefined risk;
    avoid recommending.
  - *Calendar spread* — short front, long back; bet on term-
    structure normalization after an event.
- **Avoid recommending:** naked short options, ratios without an
  explicit reason, and any structure the user can't describe the
  max-loss profile of in their own words.

## Earnings and event trades

- **Implied move.** `(ATM straddle price) / underlying` ≈ 1σ move
  priced by options. This is the benchmark for sizing and target
  selection around events, not traditional R/R math.
- **IV crush.** Near-dated IV collapses immediately after the
  event. Long premium through earnings loses on IV even if the
  stock moves — a long straddle needs a move > the implied move to
  profit.
- **Structure choice around events:** short premium (credit spread,
  iron condor) monetizes the crush if the move stays inside the
  implied range; long premium needs a beat of the implied move plus
  a directional view; calendars monetize term-structure normalization.

## Assignment and early-exercise risk

- **American-style** (US single-name equity options, most ETFs):
  early exercise is possible at any time. Short positions carry
  assignment risk.
- **Short calls near ex-dividend.** If a short call is ITM and
  extrinsic < dividend, early assignment is likely the day before
  ex-div. Pull the ex-div date before recommending short calls.
- **Short puts deep ITM with little extrinsic.** Assignment risk
  rises as extrinsic approaches zero.
- **Pin risk at expiry.** ATM strikes at expiry have uncertain
  settlement. Close or roll ATM shorts before expiry day rather
  than letting them settle.
- **European-style** (cash-settled index options: SPX, NDX, RUT,
  VIX): no early exercise, no assignment risk. Cash-settled at
  expiry on a settlement print, which can differ from the closing
  tape — flag this if the user assumes close-price settlement.

## Liquidity rules of thumb

- Index options and mega-cap single names (AAPL, NVDA, TSLA, etc.):
  liquid across most strikes and expiries.
- Single-name OTM far-dated: often illiquid; treat spreads wider
  than 15% of mark as uninvestable without limit orders.
- Weekly expiries on low-volume names: often thin; prefer monthlies.
- Complex multi-leg (butterflies, condors, ratios): only on chains
  where *every* leg has confirmed volume — a tight combo mark can
  hide one leg with a wide spread.

## Multi-leg mechanics

- Price the package as a single net debit/credit; submit as one
  combo order (the user's broker handles this). Don't recommend
  legging in unless the user explicitly wants to take execution
  risk for a specific reason.
- Max loss: `debit paid` for long premium structures; `(width −
  credit) × 100` for vertical credit spreads. State both the
  dollar figure and the percent-of-max when presenting.
- Check each leg's bid-ask individually before trusting a combo
  mark.

## What still applies from RISK.md

Sizing, stop reasoning, and portfolio-level checks in `RISK.md`
apply to options the same way they apply to shares. The max-loss
formulas above feed directly into the `risk_per_unit` input of the
sizing equation.

## What you still don't do

- Place orders, or recommend the user place one without the chain-
  quality, IV-context, and structure-choice work above.
- Quote greeks from training-data recall — always pull from the
  chain.
- Recommend undefined-risk structures (naked short options) as part
  of normal analysis. If the user insists, flag the tail profile
  explicitly and size conservatively.
- Assume European-style behavior on American-style options (or vice
  versa). Check the underlying's option style before reasoning
  about early exercise.
