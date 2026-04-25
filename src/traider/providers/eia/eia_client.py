"""Thin HTTP client around the EIA v2 API.

The US Energy Information Administration (https://www.eia.gov) publishes
the headline weekly inventory and generation series traders watch for
energy-name positioning: the Weekly Petroleum Status Report (crude /
gasoline / distillate stocks), the EIA-912 weekly natural-gas storage
report, and monthly electric-power operational data.

Auth is an ``api_key`` query param — register at
https://www.eia.gov/opendata/register.php and drop the key in ``.env``
as ``EIA_API_KEY``.

Like the other read-only hub clients, this one is deliberately thin:
each curated method maps to one EIA v2 route and returns the provider's
JSON essentially unchanged. Rate-limit / HTTP errors propagate as
:class:`EiaError` — no retries, no silent fallbacks (per hub
AGENTS.md).
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("traider.eia.client")

_BASE_URL = "https://api.eia.gov/v2"

# Curated route paths. EIA v2 versions endpoints in the URL — these are
# stable but new datasets will get added; expose the generic `query`
# method on the client for routes outside the curated set.
PETROLEUM_WEEKLY_STOCKS_PATH = "/petroleum/stoc/wstk/data/"
NATURAL_GAS_STORAGE_PATH = "/natural-gas/stor/wkly/data/"
ELECTRICITY_GENERATION_PATH = "/electricity/electric-power-operational-data/data/"


class EiaError(RuntimeError):
    """Raised when the EIA v2 API returns a non-2xx response."""


class EiaClient:
    """EIA v2 REST client.

    EIA's v2 query dialect is consistent across routes:

    - ``frequency`` — ``hourly`` / ``daily`` / ``weekly`` / ``monthly`` /
      ``quarterly`` / ``annual``. Each route advertises which it supports.
    - ``data[]`` — column projection. ``value`` is the numeric series;
      most routes also expose ``units`` and a series description.
    - ``facets[<name>][]`` — categorical filters. The available facets
      vary per route; the route's metadata endpoint
      (``/v2/<route>``, no ``/data/`` suffix) lists them.
    - ``start`` / ``end`` — ISO bounds on ``period``.
    - ``sort[0][column]`` / ``sort[0][direction]`` — sort key.
    - ``offset`` / ``length`` — paging (max ``length`` is 5000).

    Responses wrap data under ``response.data[]`` plus ``response.total``
    and a ``request`` echo. The client returns the full envelope so the
    model can read paging metadata.
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise EiaError(
                "EIA_API_KEY is not set. Register at "
                "https://www.eia.gov/opendata/register.php and put the "
                "key in .env."
            )
        self._api_key = api_key
        self._http = httpx.Client(
            base_url=_BASE_URL,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    @classmethod
    def from_env(cls) -> "EiaClient":
        return cls(api_key=os.environ.get("EIA_API_KEY", ""))

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {"api_key": self._api_key}
        for k, v in params.items():
            if v is None:
                continue
            merged[k] = v
        try:
            resp = self._http.get(path, params=merged)
        except httpx.HTTPError as exc:
            raise EiaError(f"EIA request failed: {exc}") from exc
        if resp.status_code >= 400:
            body = resp.text[:500]
            raise EiaError(f"EIA {resp.status_code} on {path}: {body}")
        return resp.json()

    def query(
        self,
        path: str,
        *,
        frequency: str | None = None,
        data: list[str] | None = None,
        facets: dict[str, list[str]] | None = None,
        start: str | None = None,
        end: str | None = None,
        sort_column: str | None = "period",
        sort_direction: str | None = "desc",
        offset: int | None = 0,
        length: int | None = 100,
    ) -> dict[str, Any]:
        """Generic EIA v2 query. All curated methods funnel through here.

        ``path`` is the EIA v2 route including ``/data/`` (e.g.
        ``/petroleum/stoc/wstk/data/``). For routes outside the curated
        set, look up the path on https://www.eia.gov/opendata/browser/.
        """
        params: dict[str, Any] = {
            "frequency": frequency,
            "start": start,
            "end": end,
            "offset": offset,
            "length": length,
        }
        if data:
            for i, col in enumerate(data):
                params[f"data[{i}]"] = col
        if facets:
            for facet_name, values in facets.items():
                if not values:
                    continue
                params[f"facets[{facet_name}][]"] = list(values)
        if sort_column:
            params["sort[0][column]"] = sort_column
            params["sort[0][direction]"] = sort_direction or "desc"
        return self._get(path, params)

    def petroleum_weekly_stocks(
        self,
        *,
        series: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        offset: int | None = 0,
        length: int | None = 100,
    ) -> dict[str, Any]:
        """Weekly Petroleum Status Report — ending stocks (crude, gasoline, distillate)."""
        return self.query(
            PETROLEUM_WEEKLY_STOCKS_PATH,
            frequency="weekly",
            data=["value"],
            facets={"series": series} if series else None,
            start=start,
            end=end,
            offset=offset,
            length=length,
        )

    def natural_gas_storage(
        self,
        *,
        series: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
        offset: int | None = 0,
        length: int | None = 100,
    ) -> dict[str, Any]:
        """EIA-912 weekly working gas in underground storage."""
        return self.query(
            NATURAL_GAS_STORAGE_PATH,
            frequency="weekly",
            data=["value"],
            facets={"series": series} if series else None,
            start=start,
            end=end,
            offset=offset,
            length=length,
        )

    def electricity_generation(
        self,
        *,
        location: list[str] | None = None,
        sectorid: list[str] | None = None,
        fueltypeid: list[str] | None = None,
        frequency: str = "monthly",
        start: str | None = None,
        end: str | None = None,
        offset: int | None = 0,
        length: int | None = 100,
    ) -> dict[str, Any]:
        """Electric Power Operational Data — net generation by location/sector/fuel."""
        facets: dict[str, list[str]] = {}
        if location:
            facets["location"] = location
        if sectorid:
            facets["sectorid"] = sectorid
        if fueltypeid:
            facets["fueltypeid"] = fueltypeid
        return self.query(
            ELECTRICITY_GENERATION_PATH,
            frequency=frequency,
            data=["generation"],
            facets=facets or None,
            start=start,
            end=end,
            offset=offset,
            length=length,
        )
