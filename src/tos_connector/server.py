"""MCP server exposing read-only Schwab quote lookups to Claude."""
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

from .schwab_client import SchwabClient

logger = logging.getLogger("tos_connector")

mcp = FastMCP(
    "tos-connector",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)
_client: SchwabClient | None = None


def _get_client() -> SchwabClient:
    global _client
    if _client is None:
        logger.info("initializing Schwab client")
        _client = SchwabClient.from_env()
        atexit.register(_client.close)
        logger.info("Schwab client ready")
    return _client


@mcp.tool()
def get_quote(symbol: str, field: str = "LAST") -> str:
    """Return a single field for one symbol.

    Args:
        symbol: Ticker (e.g. ``"SPY"``, ``"AAPL"``, ``"/ES"``).
        field: Either a friendly alias (``LAST``, ``BID``, ``ASK``,
            ``VOLUME``, ``MARK``, ``OPEN``, ``HIGH``, ``LOW``, ``CLOSE``,
            ``NET_CHANGE``, ``PERCENT_CHANGE``, ``BID_SIZE``,
            ``ASK_SIZE``) or a native Schwab quote key (e.g.
            ``lastPrice``).
    """
    logger.info("get_quote symbol=%s field=%s", symbol, field)
    try:
        value = _get_client().get_quote(symbol, field)
    except Exception:
        logger.exception("get_quote failed symbol=%s field=%s", symbol, field)
        raise
    logger.info("get_quote result symbol=%s field=%s value=%r", symbol, field, value)
    return "" if value is None else str(value)


@mcp.tool()
def get_quotes(
    symbols: list[str],
    fields: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return many fields for many symbols in one call.

    Returns a nested mapping ``{symbol: {field: value}}``. If ``fields``
    is omitted, each symbol's entry is the full Schwab ``quote`` object.
    """
    logger.info("get_quotes symbols=%s fields=%s", symbols, fields)
    try:
        results = _get_client().get_quotes(symbols, fields)
    except Exception:
        logger.exception("get_quotes failed symbols=%s fields=%s", symbols, fields)
        raise
    logger.info("get_quotes result=%r", results)
    return results


@mcp.tool()
def get_price_history(
    symbol: str,
    period_type: str = "year",
    period: int = 1,
    frequency_type: str = "daily",
    frequency: int = 1,
    start_date: int | None = None,
    end_date: int | None = None,
    need_extended_hours_data: bool = False,
    need_previous_close: bool = False,
) -> dict[str, Any]:
    """Return OHLCV candles for one symbol.

    Defaults give one year of daily bars — the "daily bars on the
    yearly chart" case. Response is Schwab's native shape:
    ``{"symbol": ..., "empty": bool, "candles": [{open, high, low,
    close, volume, datetime}, ...]}``. ``datetime`` is epoch ms.

    Args:
        symbol: Ticker (e.g. ``"SPY"``, ``"/ES"``, or a 21-char OSI
            option symbol).
        period_type: ``day``, ``month``, ``year``, or ``ytd``.
        period: How many ``period_type`` units back from today. Valid
            values depend on ``period_type``:
            day=1/2/3/4/5/10, month=1/2/3/6,
            year=1/2/3/5/10/15/20, ytd=1. Ignored if
            ``start_date``/``end_date`` are set.
        frequency_type: ``minute``, ``daily``, ``weekly``, ``monthly``.
            Must be compatible with ``period_type``: day→minute,
            month→daily|weekly, year→daily|weekly|monthly,
            ytd→daily|weekly.
        frequency: Candle size within ``frequency_type``.
            minute=1/5/10/15/30, daily/weekly/monthly=1.
        start_date: Optional epoch ms. If set (with or without
            ``end_date``), overrides ``period``.
        end_date: Optional epoch ms. Defaults to now when only
            ``start_date`` is given.
        need_extended_hours_data: Include pre/post-market candles.
        need_previous_close: Include the prior session's close in the
            response.
    """
    logger.info(
        "get_price_history symbol=%s period=%s%s frequency=%s%s",
        symbol, period, period_type, frequency, frequency_type,
    )
    try:
        result = _get_client().get_price_history(
            symbol,
            period_type=period_type,
            period=period,
            frequency_type=frequency_type,
            frequency=frequency,
            start_date=start_date,
            end_date=end_date,
            need_extended_hours_data=need_extended_hours_data,
            need_previous_close=need_previous_close,
        )
    except Exception:
        logger.exception("get_price_history failed symbol=%s", symbol)
        raise
    candles = result.get("candles", [])
    logger.info(
        "get_price_history result symbol=%s candles=%d empty=%s",
        symbol, len(candles), result.get("empty"),
    )
    return result


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
        "tos_connector",
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
    parser = argparse.ArgumentParser(prog="tos-connector")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="stdio",
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--log-file",
        default=os.environ.get("TOS_CONNECTOR_LOG", "logs/server.log"),
        help="Path to server log file (default: logs/server.log in cwd).",
    )
    args = parser.parse_args()

    _configure_logging(Path(args.log_file).resolve())
    logger.info(
        "tos-connector starting transport=%s host=%s port=%s log=%s",
        args.transport, args.host, args.port, args.log_file,
    )

    if args.transport in ("streamable-http", "sse"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
