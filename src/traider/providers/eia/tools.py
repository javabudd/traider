"""EIA v2 tools registered on the shared FastMCP.

Tool surface is deliberately narrow — three curated routes plus a
generic escape hatch:

- **Weekly petroleum stocks** (Weekly Petroleum Status Report) —
  crude / gasoline / distillate inventories. The headline release
  drives energy-name moves on Wednesdays at 10:30 ET.
- **Weekly natural gas storage** (EIA-912) — working gas in
  underground storage by region. Released Thursdays at 10:30 ET; the
  print drives natgas futures and utility names.
- **Monthly electricity generation** (Electric Power Operational
  Data) — net generation by state, sector, and fuel type. Slower-
  moving, but the canonical reference for utility-name fuel-mix
  analysis and renewable-energy policy questions.
- **Generic EIA series** — any other EIA v2 route via
  ``get_eia_series``. Use when the curated tools don't cover the
  question (e.g. retail gasoline prices, crude imports by country,
  hourly grid demand).

All responses are EIA's JSON essentially unchanged inside a
``source`` / ``fetched_at`` envelope.
"""
from __future__ import annotations

import atexit
import datetime as _dt
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from ...logging_utils import attach_provider_logger
from ...settings import TraiderSettings
from .eia_client import (
    ELECTRICITY_GENERATION_PATH,
    NATURAL_GAS_STORAGE_PATH,
    PETROLEUM_WEEKLY_STOCKS_PATH,
    EiaClient,
)

_EIA_BASE = "https://api.eia.gov/v2"


def _src(path: str) -> str:
    return f"{_EIA_BASE}{path}"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


# Trader-relevant Weekly Petroleum Status Report series. Names follow
# the EIA series-id convention (W = weekly, then product / area /
# units). See https://www.eia.gov/petroleum/supply/weekly/ for the
# full set; users can pass their own list to widen the projection.
PETROLEUM_DEFAULT_SERIES = [
    "WCESTUS1",   # Weekly U.S. Ending Stocks of Crude Oil (excluding SPR)
    "WCSSTUS1",   # Weekly U.S. Ending Stocks in the SPR
    "W_EPC0_SAX_YCUOK_MBBL",  # Cushing, OK Ending Stocks of Crude Oil
    "WGTSTUS1",   # Weekly U.S. Ending Stocks of Total Gasoline
    "WDISTUS1",   # Weekly U.S. Ending Stocks of Distillate Fuel Oil
]

# EIA-912 working-gas-in-storage series. Lower 48 total is the
# headline; the five region splits are the standard secondary read.
NATURAL_GAS_DEFAULT_SERIES = [
    "NW2_EPG0_SWO_R48_BCF",   # Lower 48 working gas (headline)
    "NW2_EPG0_SWO_R31_BCF",   # East
    "NW2_EPG0_SWO_R32_BCF",   # Midwest
    "NW2_EPG0_SWO_R33_BCF",   # South Central
    "NW2_EPG0_SWO_R34_BCF",   # Mountain
    "NW2_EPG0_SWO_R35_BCF",   # Pacific
]

_VALID_FREQUENCY = frozenset({
    "hourly", "daily", "weekly", "monthly", "quarterly", "annual",
})

_VALID_SORT_DIRECTION = frozenset({"asc", "desc"})

logger = logging.getLogger("traider.eia")
_client: EiaClient | None = None


def _get_client() -> EiaClient:
    global _client
    if _client is None:
        logger.info("initializing EIA client")
        _client = EiaClient.from_env()
        atexit.register(_client.close)
        logger.info("EIA client ready")
    return _client


def register(mcp: FastMCP, settings: TraiderSettings) -> None:
    attach_provider_logger("traider.eia", settings.log_file("eia"))

    @mcp.tool()
    def get_petroleum_weekly_stocks(
        series: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Weekly Petroleum Status Report — ending stocks.

        EIA publishes weekly inventories every Wednesday at 10:30 ET
        (Thursday on holiday weeks). The release moves energy-name
        equities, WTI/Brent futures, and the crack spreads. The
        default series projection covers the headline reads:

        - ``WCESTUS1`` — total crude oil stocks (ex-SPR)
        - ``WCSSTUS1`` — Strategic Petroleum Reserve
        - ``W_EPC0_SAX_YCUOK_MBBL`` — Cushing, OK stocks
        - ``WGTSTUS1`` — total motor gasoline
        - ``WDISTUS1`` — distillate fuel oil

        Pass your own ``series=[...]`` to pull other WPSR series.
        Browse the full series catalog at
        https://www.eia.gov/opendata/browser/petroleum/stoc/wstk.

        Args:
            series: EIA series IDs to filter on. Omit for the curated
                default list above.
            start_date: ISO ``YYYY-MM-DD`` lower bound on ``period``.
                Omit for EIA's default (full history).
            end_date: ISO ``YYYY-MM-DD`` upper bound on ``period``.
            limit: Page size (EIA caps at 5000).
            offset: 0-indexed offset for paging.

        Returns:
            ``{"source", "fetched_at", **eia_response}`` envelope. EIA's
            ``response.data[]`` carries one row per (period, series,
            duoarea) with ``period``, ``value``, ``units``,
            ``series-description``. Stocks are reported in **thousand
            barrels** (units field will say ``"MBBL"``).
        """
        chosen = series if series else PETROLEUM_DEFAULT_SERIES
        if limit < 1 or limit > 5000:
            raise ValueError(f"limit must be 1..5000; got {limit}")

        logger.info(
            "get_petroleum_weekly_stocks series=%s range=%s..%s offset=%d limit=%d",
            chosen, start_date, end_date, offset, limit,
        )
        fetched_at = _now_iso()
        try:
            payload = _get_client().petroleum_weekly_stocks(
                series=chosen,
                start=start_date,
                end=end_date,
                offset=offset,
                length=limit,
            )
        except Exception:
            logger.exception("get_petroleum_weekly_stocks failed")
            raise
        return {
            "source": _src(PETROLEUM_WEEKLY_STOCKS_PATH),
            "fetched_at": fetched_at,
            **payload,
        }

    @mcp.tool()
    def get_natural_gas_storage(
        series: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """EIA-912 weekly natural gas in underground storage.

        Released every Thursday at 10:30 ET, this is the most-watched
        inventory print after the WPSR — drives Henry Hub futures and
        utility/E&P equity moves.

        Default series projection covers Lower 48 plus the five EIA
        regional splits:

        - ``NW2_EPG0_SWO_R48_BCF`` — Lower 48 total *(headline)*
        - ``NW2_EPG0_SWO_R31_BCF`` — East
        - ``NW2_EPG0_SWO_R32_BCF`` — Midwest
        - ``NW2_EPG0_SWO_R33_BCF`` — South Central
        - ``NW2_EPG0_SWO_R34_BCF`` — Mountain
        - ``NW2_EPG0_SWO_R35_BCF`` — Pacific

        Pass your own ``series=[...]`` for salt vs. non-salt South
        Central splits or other EIA cuts. Catalog at
        https://www.eia.gov/opendata/browser/natural-gas/stor/wkly.

        Args:
            series: EIA series IDs. Omit for the curated default.
            start_date: ISO ``YYYY-MM-DD`` lower bound on ``period``.
            end_date: ISO ``YYYY-MM-DD`` upper bound on ``period``.
            limit: Page size (max 5000).
            offset: 0-indexed offset for paging.

        Returns:
            ``{"source", "fetched_at", **eia_response}``. Values are in
            **billion cubic feet** (units ``"BCF"``). Compare to
            5-year average / range for the bull/bear read.
        """
        chosen = series if series else NATURAL_GAS_DEFAULT_SERIES
        if limit < 1 or limit > 5000:
            raise ValueError(f"limit must be 1..5000; got {limit}")

        logger.info(
            "get_natural_gas_storage series=%s range=%s..%s offset=%d limit=%d",
            chosen, start_date, end_date, offset, limit,
        )
        fetched_at = _now_iso()
        try:
            payload = _get_client().natural_gas_storage(
                series=chosen,
                start=start_date,
                end=end_date,
                offset=offset,
                length=limit,
            )
        except Exception:
            logger.exception("get_natural_gas_storage failed")
            raise
        return {
            "source": _src(NATURAL_GAS_STORAGE_PATH),
            "fetched_at": fetched_at,
            **payload,
        }

    @mcp.tool()
    def get_electricity_generation(
        location: list[str] | None = None,
        sectorid: list[str] | None = None,
        fueltypeid: list[str] | None = None,
        frequency: str = "monthly",
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Electric Power Operational Data — net generation by fuel.

        Slower-moving than the weekly inventory reports, but the
        canonical reference for utility fuel-mix analysis. Useful when
        sizing positions in regulated utilities, IPPs, coal/gas E&P
        names, and renewable infrastructure.

        Default frequency is ``monthly``; ``quarterly`` and ``annual``
        are also available. Daily and hourly grid data live on a
        different EIA route — see ``get_eia_series`` with
        ``/electricity/rto/region-data/data/`` for that.

        Common facet values:

        - ``location``: 2-letter state code (e.g. ``CA``, ``TX``) or
          ``US`` for national totals.
        - ``sectorid``:  ``99`` (all sectors), ``1`` (electric utility),
          ``2`` (IPP non-cogeneration), ``3`` (IPP cogeneration), ...
        - ``fueltypeid``: ``ALL`` (all fuels), ``COW`` (coal), ``NG``
          (natural gas), ``NUC`` (nuclear), ``HYC`` (conventional
          hydro), ``WND`` (wind), ``SUN`` (solar), ``PEL`` (petroleum
          liquids), ``BIO`` (biomass).

        Browse the schema at
        https://www.eia.gov/opendata/browser/electricity/electric-power-operational-data.

        Args:
            location: State codes or ``US``. Omit for all locations.
            sectorid: Sector IDs (see above). Omit for all sectors.
            fueltypeid: Fuel-type codes. Omit for all fuel types.
            frequency: ``monthly`` (default), ``quarterly``, or
                ``annual``.
            start_date: ISO ``YYYY-MM`` (monthly) or ``YYYY`` (annual)
                lower bound on ``period``.
            end_date: ISO upper bound on ``period``.
            limit: Page size (max 5000).
            offset: 0-indexed offset for paging.

        Returns:
            ``{"source", "fetched_at", **eia_response}``. ``generation``
            values are in **thousand megawatt-hours** (``MWh`` ×
            1000). Watch the ``units`` field — EIA also exposes
            consumption / sales / fuel-cost columns on related routes.
        """
        if frequency not in _VALID_FREQUENCY:
            raise ValueError(
                f"frequency must be one of {sorted(_VALID_FREQUENCY)}; got {frequency!r}"
            )
        if limit < 1 or limit > 5000:
            raise ValueError(f"limit must be 1..5000; got {limit}")

        logger.info(
            "get_electricity_generation location=%s sector=%s fuel=%s "
            "freq=%s range=%s..%s offset=%d limit=%d",
            location, sectorid, fueltypeid,
            frequency, start_date, end_date, offset, limit,
        )
        fetched_at = _now_iso()
        try:
            payload = _get_client().electricity_generation(
                location=location,
                sectorid=sectorid,
                fueltypeid=fueltypeid,
                frequency=frequency,
                start=start_date,
                end=end_date,
                offset=offset,
                length=limit,
            )
        except Exception:
            logger.exception("get_electricity_generation failed")
            raise
        return {
            "source": _src(ELECTRICITY_GENERATION_PATH),
            "fetched_at": fetched_at,
            **payload,
        }

    @mcp.tool()
    def get_eia_series(
        route: str,
        data: list[str] | None = None,
        facets: dict[str, list[str]] | None = None,
        frequency: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        sort_column: str = "period",
        sort_direction: str = "desc",
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Generic EIA v2 query — escape hatch for routes outside the curated tools.

        Use the curated tools first (``get_petroleum_weekly_stocks``,
        ``get_natural_gas_storage``, ``get_electricity_generation``).
        Reach for this when the question needs a route they don't
        cover — e.g. retail gasoline prices, crude imports by country
        of origin, hourly grid demand by balancing authority,
        international energy data.

        Browse routes and facet schemas at
        https://www.eia.gov/opendata/browser/. Each route's metadata
        page (URL without ``/data/``) lists the supported frequencies,
        data columns, and facets. Common useful routes:

        - ``/petroleum/pri/spt/data/`` — WTI / Brent spot prices
        - ``/petroleum/pri/gnd/data/`` — retail gasoline prices
        - ``/petroleum/move/imp/data/`` — crude imports by origin
        - ``/electricity/rto/region-data/data/`` — hourly grid data
          (demand, generation, interchange) by balancing authority
        - ``/natural-gas/pri/sum/data/`` — Henry Hub & city-gate prices
        - ``/total-energy/data/`` — Monthly Energy Review aggregates

        Args:
            route: EIA v2 path including the trailing ``/data/`` (e.g.
                ``/petroleum/pri/spt/data/``).
            data: Column projection. Most routes use ``["value"]``;
                some use named columns (``["generation"]``,
                ``["consumption"]``, ...). See the route's metadata.
            facets: Map of facet name -> list of values to include
                (e.g. ``{"product": ["EPCWTI"]}`` for WTI on the
                spot-price route).
            frequency: ``hourly`` / ``daily`` / ``weekly`` / ``monthly``
                / ``quarterly`` / ``annual``. Each route advertises
                which frequencies it supports.
            start_date: ISO bound on ``period``.
            end_date: ISO bound on ``period``.
            sort_column: Column to sort on (default ``period``).
            sort_direction: ``asc`` or ``desc`` (default ``desc``).
            limit: Page size (max 5000).
            offset: 0-indexed offset for paging.

        Returns:
            ``{"source", "fetched_at", **eia_response}`` — EIA's JSON
            essentially unchanged.
        """
        if not route or not route.startswith("/"):
            raise ValueError(
                f"route must be an absolute EIA v2 path beginning with '/'; "
                f"got {route!r}"
            )
        if frequency is not None and frequency not in _VALID_FREQUENCY:
            raise ValueError(
                f"frequency must be one of {sorted(_VALID_FREQUENCY)}; got {frequency!r}"
            )
        if sort_direction not in _VALID_SORT_DIRECTION:
            raise ValueError(
                f"sort_direction must be one of {sorted(_VALID_SORT_DIRECTION)}; "
                f"got {sort_direction!r}"
            )
        if limit < 1 or limit > 5000:
            raise ValueError(f"limit must be 1..5000; got {limit}")

        logger.info(
            "get_eia_series route=%s data=%s facets=%s freq=%s range=%s..%s "
            "offset=%d limit=%d",
            route, data, facets, frequency, start_date, end_date, offset, limit,
        )
        fetched_at = _now_iso()
        try:
            payload = _get_client().query(
                route,
                frequency=frequency,
                data=data,
                facets=facets,
                start=start_date,
                end=end_date,
                sort_column=sort_column,
                sort_direction=sort_direction,
                offset=offset,
                length=limit,
            )
        except Exception:
            logger.exception("get_eia_series failed route=%s", route)
            raise
        return {
            "source": _src(route),
            "fetched_at": fetched_at,
            **payload,
        }
