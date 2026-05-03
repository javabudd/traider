"""FastMCP server that lazy-loads provider modules on startup.

One server, one port, one MCP surface. Which tools are exposed is
controlled at startup by ``TRAIDER_PROVIDERS`` in the environment:

    TRAIDER_PROVIDERS=schwab,fred,sec-edgar,factor,treasury,news

Each name maps to a provider module under ``traider.providers``.
The module exposes ``register(mcp, settings)`` which installs its
tools on the shared ``FastMCP`` instance. Modules for *disabled*
providers are never imported, so their third-party dependencies
(e.g. ``yfinance``, ``TA-Lib``, ``lxml``) stay off the hot path.

``schwab`` and ``yahoo`` both provide the "market-data backend"
surface and are mutually exclusive. Enabling both at once is a
configuration error and the server refuses to start.

The ``intent`` provider (local trade-intent journal + framework
rules) is core analyst infrastructure and is **always loaded**,
regardless of ``TRAIDER_PROVIDERS``. Listing it explicitly in the
env var is harmless (deduped) but unnecessary.
"""
from __future__ import annotations

import argparse
import importlib
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .settings import TraiderSettings, load_settings

# Canonical provider→module map. New providers get one line here.
PROVIDERS: dict[str, str] = {
    "schwab":       "traider.providers.schwab.tools",
    "yahoo":        "traider.providers.yahoo.tools",
    "fred":         "traider.providers.fred.tools",
    "fed-calendar": "traider.providers.fed_calendar.tools",
    "sec-edgar":    "traider.providers.sec_edgar.tools",
    "factor":       "traider.providers.factor.tools",
    "treasury":     "traider.providers.treasury.tools",
    "news":         "traider.providers.news.tools",
    "earnings":     "traider.providers.earnings.tools",
    "estimates":    "traider.providers.estimates.tools",
    "eia":          "traider.providers.eia.tools",
    "cftc":         "traider.providers.cftc.tools",
    "intent":       "traider.providers.intent.tools",
}

# Backends that expose the same market-data surface; pick one.
MARKET_DATA_PROVIDERS: frozenset[str] = frozenset({"schwab", "yahoo"})

# Providers loaded unconditionally on every startup. The intent
# provider carries the local trade-intent journal and the framework
# rules surface (list_rules / get_rule / get_position_context /
# validate_intent_rule_refs) — it is core analyst infrastructure and
# would be silently broken if someone forgot to list it in
# TRAIDER_PROVIDERS.
ALWAYS_LOADED_PROVIDERS: frozenset[str] = frozenset({"intent"})

logger = logging.getLogger("traider")


def _build_transport_security(
    port: int,
    extra_hosts: tuple[str, ...],
    extra_origins: tuple[str, ...],
    *,
    tls: bool,
) -> TransportSecuritySettings:
    """Allowlist localhost variants at ``port`` plus operator-supplied extras.

    The MCP transport-security middleware rejects any Host header not on
    ``allowed_hosts`` when DNS-rebinding protection is enabled. Hard-coding
    only ``localhost`` would break operators fronting traider with a reverse
    proxy or exposing it on a LAN interface; ``--allow-host`` /
    ``--allow-origin`` extend the allowlists for those cases.

    When ``tls`` is true the HTTPS origin variants are added too — Claude
    Desktop and other browsers send ``Origin: https://...`` once the server
    is on TLS, and the middleware would otherwise reject them.
    """
    base_hosts = [f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"]
    schemes = ("https",) if tls else ("http",)
    base_origins = [
        f"{scheme}://{host}:{port}"
        for scheme in schemes
        for host in ("localhost", "127.0.0.1", "[::1]")
    ]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[*base_hosts, *extra_hosts],
        allowed_origins=[*base_origins, *extra_origins],
    )


def _build_mcp(transport_security: TransportSecuritySettings) -> FastMCP:
    return FastMCP("traider", transport_security=transport_security)


def _validate_providers(providers: tuple[str, ...]) -> None:
    unknown = [p for p in providers if p not in PROVIDERS]
    if unknown:
        raise SystemExit(
            f"unknown TRAIDER_PROVIDERS entries: {unknown}. "
            f"valid names: {sorted(PROVIDERS)}"
        )
    backends = [p for p in providers if p in MARKET_DATA_PROVIDERS]
    if len(backends) > 1:
        raise SystemExit(
            "schwab and yahoo are mutually exclusive market-data backends "
            f"— enable at most one, got: {backends}"
        )


def _configure_root_logging(log_file: Path) -> None:
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
    for name in ("", "traider", "mcp", "uvicorn", "uvicorn.error", "uvicorn.access", "httpx"):
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        if lg.level == logging.NOTSET or lg.level > logging.INFO:
            lg.setLevel(logging.INFO)


def load_providers(mcp: FastMCP, settings: TraiderSettings) -> None:
    """Import each enabled provider's module and call ``register``.

    Always-on providers (see ``ALWAYS_LOADED_PROVIDERS``) are loaded
    in addition to whatever the user listed in ``TRAIDER_PROVIDERS``,
    deduped so an explicit listing of an always-on provider is a
    no-op rather than a double-register.
    """
    seen: set[str] = set()
    for name in (*settings.providers, *ALWAYS_LOADED_PROVIDERS):
        if name in seen:
            continue
        seen.add(name)
        module_path = PROVIDERS[name]
        always_on = name in ALWAYS_LOADED_PROVIDERS and name not in settings.providers
        logger.info(
            "loading provider=%s module=%s%s",
            name, module_path, " (always-on)" if always_on else "",
        )
        module = importlib.import_module(module_path)
        register = getattr(module, "register", None)
        if register is None:
            raise SystemExit(
                f"provider {name!r}: module {module_path} has no register()"
            )
        register(mcp, settings)
        logger.info("provider=%s loaded", name)


def main() -> None:
    parser = argparse.ArgumentParser(prog="traider")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http", "sse"),
        default="streamable-http",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "Interface to bind the HTTP transport on. Defaults to 127.0.0.1 "
            "(loopback only) — the unauthenticated tool surface is not safe "
            "to expose on a LAN. Pass 0.0.0.0 explicitly when running inside "
            "a container or behind a reverse proxy, and pair it with "
            "--allow-host for any non-localhost hostname clients will use."
        ),
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST:PORT",
        help=(
            "Additional Host header value to accept (repeatable). "
            "localhost / 127.0.0.1 / [::1] at --port are always allowed; "
            "use this for proxy hostnames or LAN names clients will use."
        ),
    )
    parser.add_argument(
        "--allow-origin",
        action="append",
        default=[],
        metavar="SCHEME://HOST:PORT",
        help=(
            "Additional Origin header value to accept (repeatable). "
            "{http,https}://{localhost,127.0.0.1,[::1]}:--port are always "
            "allowed (https when --ssl-certfile is set, http otherwise)."
        ),
    )
    parser.add_argument(
        "--ssl-certfile",
        default=None,
        metavar="PATH",
        help=(
            "Path to a PEM-encoded TLS certificate. When set together with "
            "--ssl-keyfile, the streamable-http / sse transport is served "
            "over HTTPS. Required for Claude Desktop's remote-MCP "
            "integration, which only connects to https:// URLs."
        ),
    )
    parser.add_argument(
        "--ssl-keyfile",
        default=None,
        metavar="PATH",
        help="Path to the PEM-encoded private key paired with --ssl-certfile.",
    )
    args = parser.parse_args()

    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        parser.error("--ssl-certfile and --ssl-keyfile must be supplied together")
    tls_enabled = bool(args.ssl_certfile)
    if tls_enabled and args.transport == "stdio":
        parser.error("--ssl-certfile / --ssl-keyfile only apply to HTTP transports")

    settings = load_settings()
    _configure_root_logging(settings.log_dir / "traider.log")
    logger.info(
        "traider starting transport=%s host=%s port=%s tls=%s providers=%s log_dir=%s",
        args.transport, args.host, args.port, tls_enabled,
        settings.providers, settings.log_dir,
    )

    if not settings.providers:
        logger.warning(
            "TRAIDER_PROVIDERS is empty — no providers will be loaded"
        )

    _validate_providers(settings.providers)

    transport_security = _build_transport_security(
        port=args.port,
        extra_hosts=tuple(args.allow_host),
        extra_origins=tuple(args.allow_origin),
        tls=tls_enabled,
    )
    mcp = _build_mcp(transport_security)
    load_providers(mcp, settings)

    if args.transport in ("streamable-http", "sse"):
        mcp.settings.host = args.host
        mcp.settings.port = args.port

    if tls_enabled:
        _run_tls(mcp, args)
    else:
        mcp.run(transport=args.transport)


def _run_tls(mcp: FastMCP, args: argparse.Namespace) -> None:
    """Serve the streamable-http / sse Starlette app over HTTPS.

    FastMCP's ``run()`` builds a uvicorn config that doesn't expose
    ``ssl_certfile`` / ``ssl_keyfile``, so when the operator wants TLS
    we bypass it: pull the same Starlette app FastMCP would have run
    and hand it to uvicorn directly with the TLS settings attached.
    Behavior for non-TLS startups is unchanged.
    """
    import asyncio

    import uvicorn

    if args.transport == "streamable-http":
        app = mcp.streamable_http_app()
    elif args.transport == "sse":
        app = mcp.sse_app()
    else:
        raise SystemExit(
            f"TLS not supported for transport={args.transport!r}"
        )
    config = uvicorn.Config(
        app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
    )
    asyncio.run(uvicorn.Server(config).serve())


if __name__ == "__main__":
    main()
