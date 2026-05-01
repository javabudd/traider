"""One-shot migration: structure the 9 v0.4 open intents in v0.5 form.

Run once, against your local intents.db, after upgrading traider to
v0.5 (rules-and-structured-fields). The script is idempotent:
already-migrated intents (those whose ``class`` column is non-null)
are skipped. Original ``thesis`` is preserved unless ``--rewrite-thesis``
is passed; ``notes`` (the journal) is never modified.

Usage:

    # Dry-run — show planned changes, write nothing
    python scripts/migrate_intents_v05.py

    # Apply — write the structured fields
    python scripts/migrate_intents_v05.py --apply

    # Apply + replace thesis prose with a tightened position-only version
    # that removes framework restatement now living in rules/
    python scripts/migrate_intents_v05.py --apply --rewrite-thesis

The mapping below is hand-curated per-intent. If your intents.db has
intent IDs different from the ones recorded here (e.g. a fresh user),
the script reports unknown intents and skips them; pull current IDs
via list_trade_intents and extend MIGRATIONS by hand.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure src/ is on sys.path when running from repo root.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from traider.providers.intent import rules as rules_mod
from traider.providers.intent.store import IntentStore

logger = logging.getLogger("migrate_intents_v05")


# ---------------------------------------------------------------------------
# Per-intent migration plan.
#
# Each entry mirrors the fields update_trade_intent would set, plus a
# tightened thesis (used only with --rewrite-thesis). Sleeve UUIDs are
# stable across reruns so the QQQ legs always group together.

QQQ_SLEEVE_ID = "a1b2c3d4-e5f6-4789-9abc-def012345678"

MIGRATIONS: dict[str, dict] = {
    # QQQ 660P
    "5468c333-f790-4196-92b5-af7f9550c1fd": {
        "class_": "hedge",
        "lifecycle": "managed-sleeve",
        "sleeve_id": QQQ_SLEEVE_ID,
        "rule_refs": ["hedge-sleeve", "concurrent-factor-cap"],
        "params": {
            "sleeve_id": QQQ_SLEEVE_ID,
            "coverage_target": -32000,
            "exit_levels": {
                "ma_level": 625,
                "vol_threshold": 16,
                "deeper_vol_threshold": 14,
                "decay_threshold_pct": 50,
            },
            "fill_context": {
                "underlying_at_fill": 663.74,
                "vix_at_fill": 17.33,
                "iv_at_fill_pct": 18.7,
                "delta_at_fill": -0.49,
                "dte_at_fill": 49,
                "theta_per_day_at_fill": 0.18,
            },
            "premium_pct_nlv": 2.1,
        },
        "catalysts_structured": [
            {"date": "2026-05-08", "type": "macro", "name": "NFP", "impact": "high"},
            {"date": "2026-05-12", "type": "macro", "name": "CPI", "impact": "high"},
            {"date": "2026-05-20", "type": "earnings", "name": "NVDA Q1 FY27", "impact": "high"},
            {"date": "2026-06-15", "type": "macro", "name": "FOMC (within expiry)", "impact": "high"},
        ],
        "thesis_tight": (
            "Layered alongside the existing 640P after the SPY 5/8 spread closed for "
            "−$163. ATM strike chosen for delta-per-dollar and faster response on a "
            "drawdown; same expiry as the 640P consolidates hedge management on one "
            "calendar with no calendar pin. Post-FOMC IV crush made entry ~3 IV "
            "points cheaper than two days earlier; vol regime normal, not stressed."
        ),
    },
    # QQQ 640P
    "033e4286-ef95-49f9-a77f-861953a52daf": {
        "class_": "hedge",
        "lifecycle": "managed-sleeve",
        "sleeve_id": QQQ_SLEEVE_ID,
        "rule_refs": ["hedge-sleeve", "concurrent-factor-cap"],
        "params": {
            "sleeve_id": QQQ_SLEEVE_ID,
            "coverage_target": -20000,
            "exit_levels": {
                "ma_level": 625,
                "vol_threshold": 16,
                "deeper_vol_threshold": 14,
                "decay_threshold_pct": 50,
            },
            "fill_context": {
                "delta_at_fill": -0.31,
                "dte_at_fill_record": 56,
            },
        },
        "catalysts_structured": [
            {"date": "2026-04-29", "type": "macro", "name": "FOMC", "impact": "high"},
            {"date": "2026-05-08", "type": "macro", "name": "NFP", "impact": "high"},
            {"date": "2026-05-12", "type": "macro", "name": "CPI", "impact": "high"},
            {"date": "2026-05-20", "type": "earnings", "name": "NVDA Q1 FY27", "impact": "high"},
        ],
        "thesis_tight": (
            "Standalone-origin macro hedge against tech concentration in the book; "
            "now managed as one leg of a two-leg sleeve with QQQ 660P. Intraday "
            "behavior on 2026-04-23 confirmed mechanics — peaked +$353 on session "
            "lows, gave back into the close, held +$165 day P&L on a −1.2% / +0.65% "
            "round-trip. Bleed on rallies is expected and not a reweighting trigger."
        ),
    },
    # NVDA equity
    "e2075990-cb3e-4e4c-8482-0ba737010727": {
        "class_": "leadership",
        "lifecycle": "core-thematic",
        "rule_refs": [
            "leadership-cap",
            "core-thematic-hold",
            "concurrent-factor-cap",
            "wash-sale-window",
            "holding-period-boundary",
            "lot-method-verification",
        ],
        "account_type": "taxable",
        "params": {
            "trim_rungs": [
                {"price": 215, "size": 7},
                {"price": 235, "size": 7},
                {"price": 250, "size": 10},
            ],
            "min_core": 50,
            "thesis_stops": [
                "Hyperscaler capex disappointment compounded across two consecutive quarters (META/MSFT/GOOGL/AMZN all cutting AI capex same cycle invalidates demand thesis)",
                "AMD or credible challenger demonstrates training-workload parity at materially lower TCO with confirmed hyperscaler design wins",
                "Loss of China export-licensing pathway not already priced in (current marks are with H20 sales paused; full mainland-China revocation would warrant reassessment)",
            ],
            "lots": [
                {"shares": 72, "basis": 102.77, "acquired_before": "2025-05-01", "ltcg_eligible": True, "note": "implied basis from kept-93 weighted avg minus in-window lots"},
                {"shares": 1, "basis": 134.345, "acquired_at": "2025-05-14", "ltcg_eligible_on": "2026-05-15"},
                {"shares": 5, "basis": 188.412, "acquired_at": "2025-10-13", "ltcg_eligible_on": "2026-10-14"},
                {"shares": 5, "basis": 188.405, "acquired_at": "2025-10-13", "ltcg_eligible_on": "2026-10-14"},
                {"shares": 5, "basis": 188.3586, "acquired_at": "2025-10-13", "ltcg_eligible_on": "2026-10-14"},
                {"shares": 5, "basis": 179.1659, "acquired_at": "2025-12-01", "ltcg_eligible_on": "2026-12-02"},
            ],
            "lot_method": "FIFO",
            "lot_method_verified_at": None,
            "lot_method_verification_todo": "Pull Realized G/L for orderId 1006155684085 (2026-04-28 -7sh trim) to verify FIFO assumption.",
        },
        "catalysts_structured": [
            {"date": "2026-04-29", "type": "macro", "name": "FOMC", "impact": "high"},
            {"date": "2026-05-08", "type": "macro", "name": "NFP", "impact": "high"},
            {"date": "2026-05-12", "type": "macro", "name": "CPI", "impact": "high"},
            {"date": "2026-05-20", "type": "earnings", "name": "NVDA Q1 FY27 ER", "impact": "high"},
        ],
        "thesis_tight": (
            "Long-term core position in the AI-infrastructure cycle's primary "
            "beneficiary. Largest single-name in the book; volatility floor of "
            "the book is set by this position. Thesis is the cycle, not a price "
            "target — managed by the leadership cap and the trim ladder. Hedges "
            "absorb earnings binaries; the equity stays through ER. ~24% NLV in "
            "a single high-beta mega-cap is acknowledged load-bearing risk; "
            "−30% NVDA print would draw down the book ~7% before hedge offset, "
            "within tolerance for a thematic core."
        ),
    },
    # IONQ equity
    "197bfe06-d037-4bf4-8907-3b470e5ee91b": {
        "class_": "thematic",
        "lifecycle": "core-thematic",
        "rule_refs": [
            "thematic-cap",
            "core-thematic-hold",
            "concurrent-factor-cap",
            "wash-sale-window",
            "holding-period-boundary",
        ],
        "account_type": "taxable",
        "params": {
            "trim_rungs": [
                {"price": 46.49, "size": 50, "note": "clean break above SMA200"},
                {"price": 60, "size": 50},
                {"price": 80, "size": 50, "note": "just below Oct '25 ATH $84.64"},
            ],
            "min_core": 50,
            "thesis_stops": [
                "Trapped-ion architecture loses scaling race to superconducting or topological in a clearly visible way (Google or IBM logical-qubit milestone IONQ can't match within 12 months)",
                "Cash runway concern emerges (current $2.4B / $510M op loss = ~4.7 years; doubled burn rate would shorten materially)",
                "Loss of DARPA HARQ or other marquee gov contracts",
            ],
            "lot_method": "FIFO",
            "lot_method_verified_at": None,
            "discretionary_target": 80,
        },
        "catalysts_structured": [
            {"date": "2026-04-29", "type": "macro", "name": "FOMC", "impact": "high"},
            {"date": "2026-05-06", "type": "earnings", "name": "IONQ Q1 ER", "impact": "high", "note": "consensus -$0.36 EPS / $50.7M rev (Finnhub)"},
            {"date": "2026-08-04", "type": "earnings", "name": "IONQ Q2 ER", "impact": "high"},
        ],
        "thesis_tight": (
            "Long-term thematic conviction in IonQ as the best-positioned pure-play "
            "in quantum computing — trapped-ion architecture (room-temperature "
            "apparatus, laser-cooled ions) avoids the cryogenic facility cost of "
            "superconducting rivals and holds the world record for highest-fidelity "
            "gate operations. DARPA HARQ selection 2026-04-15 + first remote "
            "trapped-ion entanglement demo are this year's marquee validation "
            "signals. P/S 95–106 is the loudest bear case; size sustains a 50%+ "
            "drawdown without forcing a sell. Pre-ER trim 2026-04-30 was event-risk "
            "management, not ladder-rung-1."
        ),
    },
    # SGOV
    "18bd3b19-2b5e-404f-833c-851b88b6c9e4": {
        "class_": "dry-powder",
        "lifecycle": "rolling",
        "rule_refs": ["dry-powder-band", "treasury-etf-tax"],
        "account_type": "taxable",
        "params": {
            "earmarks": [
                {"target_position": "GLD scale-in Add 2", "planned_size_usd": 5600, "trigger_price": 402},
                {"target_position": "future tactical entries", "planned_size_usd": None},
                {"target_position": "emergency margin cushion", "planned_size_usd": None},
            ],
        },
        "catalysts_structured": [],
        "thesis_tight": (
            "Dry-powder reserve — 0–3 month T-bill ETF used as the cash-equivalent "
            "parking spot for tactical entries. Mark cycles between ~$100.05 ex-div "
            "and ~$100.65 just before the next monthly distribution; do not read "
            "those swings as P&L. The 27%+ NLV allocation is intentional given the "
            "book's named-stock concentration; deployment-queue-shaped reserves "
            "beat buying-power-only liquidity for the next entry."
        ),
    },
    # VOO
    "e5ef6947-60d5-4712-a2a2-15c55412cdda": {
        "class_": "index-core",
        "lifecycle": "rolling",
        "rule_refs": ["index-core-rebalance", "qualified-dividend-tax", "concurrent-factor-cap"],
        "account_type": "taxable",
        "params": {},
        "catalysts_structured": [],
        "thesis_tight": (
            "Core S&P 500 sleeve — diversification anchor against single-name "
            "concentration in the rest of the book. Functionally identical to SPY "
            "(corr ~0.999) at lower expense ratio. Rebalanced on drift, never "
            "traded on technicals or fundamentals. Note structural overlap: the "
            "QQQ hedge sleeve is effectively also a partial VOO hedge given S&P / "
            "Nasdaq tech overlap (VOO-QQQ 1y daily corr 0.95)."
        ),
    },
    # GLD
    "2cf4d479-ecdb-43a9-a07f-ef70e486f8b2": {
        "class_": "diversifier",
        "lifecycle": "scale-in",
        "rule_refs": [
            "swing-trade",
            "sizing-from-risk",
            "entries-no-chase",
            "risk-reward-rules",
            "holding-period-boundary",
            "collectibles-tax-treatment",
        ],
        "account_type": "taxable",
        "params": {
            "entry": 423.4435,
            "stop": 396,
            "target_ladder": [
                {"price": 448, "size_pct": 33, "note": "recent swing high + SMA50 cluster"},
                {"price": 481, "size_pct": 33},
                {"price": 510, "size_pct": 34, "note": "Jan ATH"},
            ],
            "min_runner": 0,
            "scale_in_ladder": [
                {"tranche": "starter", "price_target": 430, "actual_fill": 430.44, "shares": 6, "status": "filled"},
                {"tranche": "add 1", "price_target": 418, "actual_fill": 420.445, "shares": 14, "status": "filled"},
                {"tranche": "add 2", "price_target": 402, "actual_fill": None, "shares": 14, "status": "pending", "note": "STALE — GLD broke higher; revisit anchor"},
            ],
            "thesis_stops": [
                "Gold-cycle macro setup invalidated (yield curve re-inverts, financial conditions tighten, term premium compresses to 2y lows)",
            ],
            "account_risk_pct_used": 0.67,
        },
        "catalysts_structured": [
            {"date": "2026-04-29", "type": "macro", "name": "FOMC", "impact": "high"},
            {"date": "2026-05-08", "type": "macro", "name": "NFP", "impact": "high"},
            {"date": "2026-05-12", "type": "macro", "name": "CPI", "impact": "high"},
        ],
        "thesis_tight": (
            "Portfolio diversifier — the only liquid asset screened that's "
            "near-zero-correlated to the existing tech-heavy book (1y daily corr "
            "to NVDA/IONQ/VOO/QQQ all <0.10). Macro setup supports gold over a "
            "months horizon: yield curve fully disinverted, loose financial "
            "conditions, term premium reasserting at the long end. TA at intent "
            "record showed healthy pullback in an established uptrend — RSI(14) "
            "47.5, cooled from 80+ at the Jan ATH. GLD is taxed as a collectible "
            "(28% LTCG) — known and accepted."
        ),
    },
    # GME 6/18 $15C
    "b23bffe6-395b-4435-93c7-7c47d216d394": {
        "class_": "speculative",
        "lifecycle": "swing",
        "rule_refs": ["speculative-cap", "swing-trade", "sizing-from-risk", "risk-reward-rules"],
        "params": {
            "entry": 10.7566,
            "stop": "GME underlying close < $20",
            "stop_underlying_price": 20,
            "target_ladder": [
                {"underlying_price": 28, "size_pct": 50, "note": "above 6-mo $25.93 swing high"},
                {"underlying_price": 30, "size_pct": 50, "note": "or any deal-announcement spike"},
            ],
            "min_runner": 0,
            "thesis_stops": [
                "Cohen publicly retracts or delays acquisition guidance with no replacement narrative",
            ],
            "account_risk_pct_used": 1.28,
            "deep_itm_rationale": "Strike $15 with GME ~$25 = ~$10 intrinsic vs ~$10.5 mark = ~$0.12 extrinsic; effective delta ~1.0; behaves as ~100 long-stock-equivalent shares with capped downside.",
        },
        "catalysts_structured": [
            {"date": "2026-04-29", "type": "macro", "name": "FOMC", "impact": "high"},
            {"date": "2026-05-12", "type": "macro", "name": "CPI", "impact": "high"},
            {"date": "2026-06-08", "type": "earnings", "name": "GME Q1 FY27 ER", "impact": "high", "note": "consensus EPS $0.12 / rev $774M (Finnhub); inside expiry"},
        ],
        # Discretionary (no date) catalysts kept out of catalysts_structured
        # since that field wants date-specific events; documented in thesis.
        "thesis_tight": (
            "Speculative deep-ITM long call on GME — leveraged exposure to a "
            "Cohen-driven re-rating thesis. Three pillars: (1) Cohen open-market "
            "PURCHASE of 1M sh 2026-01-20/21 at avg ~$21.36 (~$21.4M deployed "
            "personally), with directors Attal +24K sh and Cheng +5K sh same week "
            "— high-signal cluster. (2) Stated 'transformational' acquisition in "
            "the works (4/6 reporting); $9B + $368M BTC balance sheet supports "
            "it. (3) Retro-gaming nationwide rollout going live early May; ER "
            "2026-06-08 is inside the expiry window. Bear case (rev decline, "
            "dilution overhang, no analyst support) is documented and the trade "
            "explicitly does not rest on fundamentals."
        ),
    },
    # MSTR LEAP $140C 2027-03-19
    "a9df1f82-1c72-4d6b-933a-2c2f46a011a7": {
        "class_": "thematic",
        "lifecycle": "core-thematic",
        "rule_refs": ["thematic-cap", "core-thematic-hold", "concurrent-factor-cap"],
        "params": {
            "trim_rungs": [],
            "min_core": 0,
            "thesis_stops": [
                "Structural break in MSTR's BTC-treasury narrative (e.g. dilution-via-ATM at multiples that destroy mNAV premium, or BTC reserves materially impaired)",
                "Confirmed BTC bear regime (multi-quarter price action below 200WMA with macro liquidity contracting)",
            ],
            "discretionary_target_underlying": 350,
            "discretionary_target_intrinsic": 210,
        },
        "catalysts_structured": [
            {"date": "2026-04-29", "type": "macro", "name": "FOMC", "impact": "high"},
        ],
        # Recurring cycle catalysts (MSTR earnings, BTC halving, macro
        # liquidity) are not date-specific events — left in thesis.
        "thesis_tight": (
            "Long-dated bull exposure to MSTR as a leveraged BTC-cycle proxy. "
            "LEAP duration insulates from short-term FOMC vol; thesis-stop on "
            "structural break in the BTC-treasury narrative or confirmed BTC "
            "bear regime. target_exit_price = $210 is the intrinsic-only floor "
            "if MSTR reaches $350 ($350 − $140 strike) — actual contract mark "
            "will be higher by remaining extrinsic if triggered before expiry."
        ),
    },
}


# ---------------------------------------------------------------------------
# Migration runner

def _is_already_migrated(rec: dict) -> bool:
    return rec.get("class") is not None and rec.get("rule_refs") is not None


def _resolve_rule_refs(
    refs: list[str],
    *,
    intent_class: str | None,
    intent_account_type: str | None,
    intent_params: dict,
    index: rules_mod.RulesIndex,
) -> list[dict]:
    """Local copy of the resolution logic from tools.py — applied
    directly against the index without going through the MCP layer."""
    out = []
    for name in refs:
        rule = index.get(name)
        if rule is None:
            raise ValueError(f"rule {name!r} not in rules index")
        if intent_class and intent_class not in rule.applies_to_class:
            raise ValueError(
                f"intent class {intent_class!r} not in rule {name!r} "
                f"applies_to_class={list(rule.applies_to_class)}"
            )
        if (
            intent_account_type
            and rule.applies_to_account_type
            and intent_account_type not in rule.applies_to_account_type
        ):
            raise ValueError(
                f"intent account_type {intent_account_type!r} not in rule "
                f"{name!r} applies_to_account_type={list(rule.applies_to_account_type)}"
            )
        missing = [p for p in rule.requires_intent_params if p not in (intent_params or {})]
        if missing:
            raise ValueError(
                f"intent params missing keys required by rule {name!r}: {missing}"
            )
        out.append({
            "rule": name,
            "version": rule.version,
            "content_hash_at_fill": rule.content_hash,
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default: dry-run)")
    parser.add_argument("--rewrite-thesis", action="store_true",
                        help="Replace thesis prose with the tightened version")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    store = IntentStore()
    index = rules_mod.get_index()
    logger.info("loaded %d rules from rules/", len(index))

    seen_ids: set[str] = set()
    changed = 0
    skipped = 0
    unknown = 0

    for rec in store.list(status="open", limit=1000):
        seen_ids.add(rec["id"])
        plan = MIGRATIONS.get(rec["id"])
        if plan is None:
            logger.warning(
                "intent %s (%s) not in migration plan — skipping. Pull "
                "current intent shape and add to MIGRATIONS by hand.",
                rec["id"], rec["symbol"],
            )
            unknown += 1
            continue

        if _is_already_migrated(rec):
            logger.info("intent %s (%s) already migrated — skipping",
                        rec["id"][:8], rec["symbol"])
            skipped += 1
            continue

        # Resolve rule_refs to validate before writing.
        try:
            resolved = _resolve_rule_refs(
                plan["rule_refs"],
                intent_class=plan.get("class_"),
                intent_account_type=plan.get("account_type"),
                intent_params=plan.get("params", {}),
                index=index,
            )
        except ValueError as exc:
            logger.error("intent %s (%s) failed rule validation: %s",
                         rec["id"][:8], rec["symbol"], exc)
            return 2

        update_fields = {
            "class_": plan["class_"],
            "lifecycle": plan["lifecycle"],
            "sleeve_id": plan.get("sleeve_id"),
            "rule_refs": resolved,
            "params": plan.get("params"),
            "catalysts_structured": plan.get("catalysts_structured"),
        }
        if args.rewrite_thesis and plan.get("thesis_tight"):
            update_fields["thesis"] = plan["thesis_tight"]

        logger.info(
            "intent %s (%s): class=%s lifecycle=%s rules=%s%s",
            rec["id"][:8], rec["symbol"],
            plan["class_"], plan["lifecycle"],
            plan["rule_refs"],
            " [+thesis rewrite]" if args.rewrite_thesis else "",
        )

        if args.apply:
            store.update(rec["id"], **update_fields)
            changed += 1

    plan_only = set(MIGRATIONS) - seen_ids
    for missing in plan_only:
        logger.warning("intent %s in MIGRATIONS but not in DB — skipping",
                       missing[:8])

    if args.apply:
        logger.info("done — %d migrated, %d already done, %d unknown",
                    changed, skipped, unknown)
    else:
        logger.info("dry-run — %d would change, %d already done, %d unknown. "
                    "Re-run with --apply to write.",
                    sum(1 for r in store.list(status="open", limit=1000)
                        if r["id"] in MIGRATIONS and not _is_already_migrated(r)),
                    skipped, unknown)
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
