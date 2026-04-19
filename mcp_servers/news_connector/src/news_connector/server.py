"""MCP server exposing read-only Massive news lookups.

Single tool surface: ``get_news`` wraps the ``/v2/reference/news``
endpoint. The response is returned as-is so the model can introspect
raw fields (``insights[].sentiment``, ``publisher.name``, ``tickers``,
``published_utc``) rather than trust a translation layer.
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .massive_client import MassiveClient

_VALID_ORDER = frozenset({"asc", "desc"})

logger = logging.getLogger("news_connector")

mcp = FastMCP(
    "news-connector",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)
_client: MassiveClient | None = None


def _get_client() -> MassiveClient:
    global _client
    if _client is None:
        logger.info("initializing Massive news client")
        _client = MassiveClient.from_env()
        atexit.register(_client.close)
        logger.info("Massive news client ready")
    return _client


@mcp.tool()
def get_news(
    ticker: str | None = None,
    published_after: str | None = None,
    published_before: str | None = None,
    limit: int = 10,
    order: str = "desc",
    sort: str = "published_utc",
) -> dict[str, Any]:
    """Recent news articles from Massive (``/v2/reference/news``).

    Each article carries title, description, publisher, article URL,
    the tickers it references, and a per-ticker ``insights`` array with
    Massive's sentiment label and reasoning. Use this for catalyst
    tracking and to explain intraday moves.

    Pair with other hub tools for context — recent 8-K filings
    (``sec_edgar``), upcoming macro releases (``fred``), price action
    around the article timestamp (market-data backend).

    Args:
        ticker: Case-sensitive ticker to filter by (e.g. ``AAPL``).
            Omit to pull the cross-market feed.
        published_after: ISO date or RFC3339 timestamp; only articles
            with ``published_utc`` at or after this are returned. Maps
            to Massive's ``published_utc.gte``.
        published_before: ISO date or RFC3339 timestamp; maps to
            Massive's ``published_utc.lte``.
        limit: Page size. Massive allows 1–1000; default 10.
        order: ``asc`` or ``desc``. Defaults to ``desc`` (newest
            first).
        sort: Field to sort by. Defaults to ``published_utc``.

    Returns:
        Massive's response JSON unchanged — ``status``, ``count``,
        ``results`` (article list), ``next_url`` (pagination cursor
        when more rows are available), ``request_id``.
    """
    if order not in _VALID_ORDER:
        raise ValueError(
            f"order must be one of {sorted(_VALID_ORDER)}; got {order!r}"
        )
    if limit < 1 or limit > 1000:
        raise ValueError(f"limit must be 1..1000; got {limit}")

    logger.info(
        "get_news ticker=%s after=%s before=%s limit=%d order=%s sort=%s",
        ticker, published_after, published_before, limit, order, sort,
    )
    try:
        return _get_client().news(
            ticker=ticker,
            published_utc_gte=published_after,
            published_utc_lte=published_before,
            order=order,
            sort=sort,
            limit=limit,
        )
    except Exception:
        logger.exception("get_news failed")
        raise


def _configure_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    for name in (
        "",
        "news_connector",
        "mcp",
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
    ):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)


def main() -> None:
    parser = argparse.ArgumentParser(prog="news-connector")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="stdio",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--log-file",
        default=os.environ.get("NEWS_CONNECTOR_LOG", "logs/server.log"),
        help="Path to server log file (default: logs/server.log in cwd).",
    )
    args = parser.parse_args()

    _configure_logging(Path(args.log_file).resolve())
    logger.info(
        "news-connector starting transport=%s host=%s port=%s log=%s",
        args.transport, args.host, args.port, args.log_file,
    )

    if args.transport in ("streamable-http", "sse"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
