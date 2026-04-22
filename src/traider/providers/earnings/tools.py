"""Finnhub earnings tools registered on the shared FastMCP instance.

Surface is deliberately narrow — the two free-tier Finnhub endpoints
that fill the "when is X reporting?" / "how did X do vs. consensus?"
gap the rest of the hub does not answer:

- ``get_earnings_calendar`` — forward-looking (and backward-looking)
  earnings announcements with consensus EPS / revenue estimates.
- ``get_earnings_surprises`` — per-ticker history of actual vs.
  estimate and the resulting surprise.

Everything else on Finnhub (quotes, fundamentals, sentiment,
recommendation trends) is intentionally out of scope — the hub
already has dedicated providers for quotes, filings, and news.
"""
from __future__ import annotations

import atexit
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...logging_utils import attach_provider_logger
from ...settings import TraiderSettings
from .finnhub_client import FinnhubClient

logger = logging.getLogger("traider.earnings")
_client: FinnhubClient | None = None


def _get_client() -> FinnhubClient:
    global _client
    if _client is None:
        logger.info("initializing Finnhub earnings client")
        _client = FinnhubClient.from_env()
        atexit.register(_client.close)
        logger.info("Finnhub earnings client ready")
    return _client


def _today_utc_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _utc_iso_plus(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def register(mcp: FastMCP, settings: TraiderSettings) -> None:
    attach_provider_logger("traider.earnings", settings.log_file("earnings"))

    @mcp.tool()
    def get_earnings_calendar(
        from_date: str | None = None,
        to_date: str | None = None,
        symbol: str | None = None,
        symbols: list[str] | None = None,
    ) -> dict[str, Any]:
        """Upcoming (and recent) earnings announcements with consensus.

        Source: Finnhub ``/calendar/earnings``. Free tier covers US
        issuers; international coverage requires a paid plan and is
        not wired here.

        Args:
            from_date: ISO ``YYYY-MM-DD``. Defaults to today (UTC).
            to_date: ISO ``YYYY-MM-DD``. Defaults to ``from_date`` +
                14 days — a sensible two-week look-ahead for a
                trading week review. Widen explicitly for longer
                horizons.
            symbol: Single ticker (e.g. ``AAPL``) to narrow to one
                issuer — sent to Finnhub as a server-side filter.
                Omit for the cross-market calendar across the
                window — response can be large.
            symbols: List of tickers to keep (e.g.
                ``["AAPL", "MSFT", "NVDA"]``). Applied as a
                post-processing filter on the cross-market calendar
                (one upstream request, then client-side narrowing),
                so it does not multiply the rate-limit cost.
                Comparison is case-insensitive. Mutually exclusive
                with ``symbol``.

        Returns:
            A dict with ``source``, ``fetched_at``, and Finnhub's
            ``earningsCalendar`` list unchanged. Each entry carries:

            - ``symbol`` — ticker.
            - ``date`` — announcement date in the issuer's local
              exchange timezone.
            - ``hour`` — ``"bmo"`` = before market open, ``"amc"`` =
              after market close, ``"dmh"`` = during market hours,
              ``""`` = unspecified.
            - ``year`` / ``quarter`` — fiscal period being reported.
            - ``epsEstimate`` / ``epsActual`` — consensus and printed
              EPS. ``epsActual`` is ``null`` for future reports.
            - ``revenueEstimate`` / ``revenueActual`` — same, for
              revenue (in USD).

            When ``symbols`` is supplied, the response also echoes
            the requested list under ``symbols`` and reports any
            tickers that had no entries in the window under
            ``symbols_missing`` — useful for spotting typos or names
            Finnhub's free tier doesn't cover.

            Consensus estimates are Finnhub's aggregate of sell-side
            analysts. Quote them with attribution; they are *not* a
            primary source like an SEC filing.
        """
        if symbol and symbols:
            raise ValueError("pass either symbol or symbols, not both")

        start = from_date or _today_utc_iso()
        end = to_date or (
            (datetime.fromisoformat(start) + timedelta(days=14)).date().isoformat()
        )

        symbols_upper = (
            [s.upper() for s in symbols if s] if symbols else None
        )

        logger.info(
            "get_earnings_calendar from=%s to=%s symbol=%s symbols=%s",
            start, end, symbol, symbols_upper,
        )
        try:
            payload = _get_client().calendar_earnings(
                from_date=start, to_date=end, symbol=symbol,
            )
        except Exception:
            logger.exception("get_earnings_calendar failed")
            raise

        entries = payload.get("earningsCalendar", []) or []
        symbols_missing: list[str] | None = None
        if symbols_upper:
            wanted = set(symbols_upper)
            entries = [
                row for row in entries
                if str(row.get("symbol", "")).upper() in wanted
            ]
            seen = {str(row.get("symbol", "")).upper() for row in entries}
            symbols_missing = sorted(wanted - seen)

        source = (
            "https://finnhub.io/api/v1/calendar/earnings"
            f"?from={start}&to={end}"
            + (f"&symbol={symbol}" if symbol else "")
        )
        response: dict[str, Any] = {
            "source": source,
            "fetched_at": _now_iso(),
            "from_date": start,
            "to_date": end,
            "symbol": symbol,
            "earningsCalendar": entries,
        }
        if symbols_upper is not None:
            response["symbols"] = symbols_upper
            response["symbols_missing"] = symbols_missing
        return response

    @mcp.tool()
    def get_earnings_surprises(
        symbol: str,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Historical quarterly EPS actual vs. consensus for one ticker.

        Source: Finnhub ``/stock/earnings``. Free tier typically
        returns the last 4 quarters.

        Args:
            symbol: Ticker (e.g. ``AAPL``). Required.
            limit: Max quarters to return. Omit for Finnhub's
                default.

        Returns:
            A dict with ``source``, ``fetched_at``, ``symbol``, and
            ``earnings`` — a list of quarters newest-first. Each
            entry carries ``actual``, ``estimate``, ``surprise``
            (absolute), ``surprisePercent``, ``period`` (report
            date), ``quarter``, ``year``, ``symbol``.

            Use this to gauge whether the next print is being
            handicapped aggressively (serial beats) vs. cautiously
            (serial misses) alongside ``get_earnings_calendar``'s
            forward consensus.
        """
        if not symbol:
            raise ValueError("symbol is required")

        logger.info(
            "get_earnings_surprises symbol=%s limit=%s", symbol, limit,
        )
        try:
            rows = _get_client().stock_earnings(symbol=symbol, limit=limit)
        except Exception:
            logger.exception("get_earnings_surprises failed symbol=%s", symbol)
            raise

        source = f"https://finnhub.io/api/v1/stock/earnings?symbol={symbol}"
        return {
            "source": source,
            "fetched_at": _now_iso(),
            "symbol": symbol,
            "earnings": rows or [],
        }
