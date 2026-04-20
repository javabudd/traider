"""Macro analytics over FRED observation series.

Pure numpy + stdlib. Raw FRED observations are parsed into ``[(date_str,
float), ...]`` lists (missing ``"."`` observations dropped, sorted
ascending) and summarised into latest-level, trailing deltas, and a
rolling-window z-score. Regime classifiers (curve shape, credit, Fed-
target breakeven alignment, NFCI, aggregate macro) turn those numbers
into the labels a trading analyst actually reads.

Thresholds are named kwargs so the boundaries are visible at the call
site rather than hidden in magic numbers.
"""
from __future__ import annotations

import math
from datetime import date as _date, datetime, timedelta
from typing import Any

import numpy as np


def parse_observations(payload: dict[str, Any]) -> list[tuple[str, float]]:
    """FRED ``/series/observations`` → ``[(date_str, value), ...]`` ascending.

    Missing values (``"."``) and non-parseable rows are dropped so
    downstream math doesn't need to guard.
    """
    rows: list[tuple[str, float]] = []
    for obs in payload.get("observations", []):
        v = obs.get("value", ".")
        if v in (".", "", None):
            continue
        try:
            rows.append((obs["date"], float(v)))
        except (ValueError, TypeError):
            continue
    rows.sort(key=lambda r: r[0])
    return rows


def _to_date(d: str) -> _date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def _jsonify(x: Any) -> Any:
    if isinstance(x, (list, tuple)):
        return [_jsonify(v) for v in x]
    if isinstance(x, dict):
        return {k: _jsonify(v) for k, v in x.items()}
    if isinstance(x, float) and not math.isfinite(x):
        return None
    if isinstance(x, np.floating):
        v = float(x)
        return v if math.isfinite(v) else None
    if isinstance(x, np.ndarray):
        return _jsonify(x.tolist())
    return x


def _delta(series: list[tuple[str, float]], days_back: int) -> dict[str, Any] | None:
    """Change from the observation nearest (but not after) ``days_back``
    calendar days before the latest observation, to the latest."""
    if not series:
        return None
    latest_date_s, latest_v = series[-1]
    target = _to_date(latest_date_s) - timedelta(days=days_back)
    best: tuple[str, float] | None = None
    for d_s, v in series:
        if _to_date(d_s) <= target:
            best = (d_s, v)
        else:
            break
    if best is None:
        return None
    return {
        "from_date": best[0],
        "from_value": best[1],
        "absolute_change": latest_v - best[1],
    }


def _zscore(series: list[tuple[str, float]], window: int) -> dict[str, Any] | None:
    if len(series) < window:
        return None
    values = np.array([v for _, v in series[-window:]], dtype=float)
    mu = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    current = float(values[-1])
    z = (current - mu) / sd if sd > 0 else None
    pct = float((values <= current).sum()) / values.size
    return {"window": window, "mean": mu, "std": sd, "z_score": z, "percentile": pct}


def summarize_series(
    series: list[tuple[str, float]],
    zscore_window: int = 504,
) -> dict[str, Any]:
    """Latest value + 1m/3m/6m/1y absolute change + rolling z-score.

    ``zscore_window`` is in *observations*, not calendar days — so 504
    is roughly 2y of a daily series and ~10y of a weekly one. When
    fewer than ``window`` observations are available the z-score block
    comes back ``None``; other fields still populate.
    """
    if not series:
        return {"latest": None, "error": "no observations"}
    latest_d, latest_v = series[-1]
    return _jsonify({
        "latest": {"date": latest_d, "value": float(latest_v)},
        "delta_1m": _delta(series, 30),
        "delta_3m": _delta(series, 90),
        "delta_6m": _delta(series, 180),
        "delta_1y": _delta(series, 365),
        "zscore": _zscore(series, zscore_window),
        "n_observations": len(series),
    })


def difference_series(
    long_leg: list[tuple[str, float]],
    short_leg: list[tuple[str, float]],
) -> list[tuple[str, float]]:
    """Inner-joined spread series: ``long - short`` on shared dates."""
    ma = dict(long_leg)
    mb = dict(short_leg)
    shared = sorted(set(ma) & set(mb))
    return [(d, ma[d] - mb[d]) for d in shared]


# ---------- regime classifiers ----------------------------------------


def curve_shape(
    slope_2s10s: float | None,
    slope_3m10y: float | None,
    flat_threshold: float = 0.5,
) -> str:
    """Label from the two benchmark slopes (values in percentage points).

    - Both negative → ``inverted``
    - One negative → ``partially_inverted``
    - Both positive but under ``flat_threshold`` → ``flat``
    - Otherwise → ``normal``
    """
    if slope_2s10s is None or slope_3m10y is None:
        return "unknown"
    if slope_2s10s < 0 and slope_3m10y < 0:
        return "inverted"
    if slope_2s10s < 0 or slope_3m10y < 0:
        return "partially_inverted"
    if slope_2s10s < flat_threshold and slope_3m10y < flat_threshold:
        return "flat"
    return "normal"


def credit_regime(hy_z: float | None, ig_z: float | None) -> str:
    """Credit regime from HY/IG OAS z-scores. The wider (higher z) of
    the two wins — we'd rather over-flag stress than under-flag it."""
    vals = [z for z in (hy_z, ig_z) if z is not None and math.isfinite(z)]
    if not vals:
        return "unknown"
    z = max(vals)
    if z < -1.0:
        return "tight"
    if z < 1.0:
        return "normal"
    if z < 2.0:
        return "wide"
    return "stressed"


def breakeven_alignment(
    latest: float | None,
    target: float = 2.0,
    band: float = 0.25,
) -> str:
    """Breakeven vs. the Fed's 2% target.

    The Fed's 2% target is technically PCE, not breakevens — breakevens
    include an inflation risk premium and typically run 20-50bp above
    expected inflation. ``band`` widens the "near target" zone to
    absorb that premium."""
    if latest is None or not math.isfinite(latest):
        return "unknown"
    if latest < target - band:
        return "below_target"
    if latest < target + band:
        return "near_target"
    return "above_target"


def nfci_regime(latest: float | None) -> str:
    """Chicago Fed NFCI label.

    NFCI is constructed to be centered at 0 = average financial
    conditions since 1971. Positive = tighter than average; negative =
    looser. Raw levels, not z-scored — it's already in z-like units.
    """
    if latest is None or not math.isfinite(latest):
        return "unknown"
    if latest < -0.5:
        return "loose"
    if latest < 0.5:
        return "normal"
    if latest < 1.5:
        return "tight"
    return "stressed"


def aggregate_regime(
    curve: str,
    credit: str,
    breakevens: str,
    nfci: str,
) -> str:
    """One-word macro readout from the four components.

    Risk-off wins tiebreaks: any single ``stressed`` component forces a
    ``stressed`` aggregate. Otherwise components accrue ±1 / ±2 to a
    score that buckets into ``risk_on`` / ``neutral`` / ``risk_off``.

    This is a coarse summary — read the per-component labels in the
    tool response for the real signal.
    """
    if "stressed" in (credit, nfci):
        return "stressed"
    score = 0
    if curve == "inverted":
        score -= 2
    elif curve in ("partially_inverted", "flat"):
        score -= 1
    elif curve == "normal":
        score += 1
    if credit == "tight":
        score += 1
    elif credit == "wide":
        score -= 2
    if nfci == "loose":
        score += 1
    elif nfci == "tight":
        score -= 2
    if breakevens in ("below_target", "above_target"):
        score -= 1
    if score >= 2:
        return "risk_on"
    if score >= 0:
        return "neutral"
    return "risk_off"


__all__ = [
    "parse_observations",
    "summarize_series",
    "difference_series",
    "curve_shape",
    "credit_regime",
    "breakeven_alignment",
    "nfci_regime",
    "aggregate_regime",
]
