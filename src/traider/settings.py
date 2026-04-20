"""Runtime settings shared across the hub and per-provider modules.

Settings carry the *parsed* shape of the environment so individual
provider ``register()`` functions don't each re-parse env vars.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TraiderSettings:
    """Shared settings passed to every provider's ``register()``.

    Attributes:
        providers: Ordered tuple of enabled provider names (e.g.
            ``("schwab", "fred", "news")``). Driven by
            ``TRAIDER_PROVIDERS`` (comma-separated).
        log_dir: Base directory for per-provider log files. Each
            provider writes to ``<log_dir>/<name>.log``. Override
            with ``TRAIDER_LOG_DIR`` (default: ``logs/`` in cwd).
        extra: Opaque pass-through map of the process env, so
            provider-specific vars (``FRED_API_KEY``,
            ``SCHWAB_TOKEN_FILE``, …) remain readable without
            re-reading ``os.environ`` in every module.
    """

    providers: tuple[str, ...]
    log_dir: Path
    extra: dict[str, str] = field(default_factory=dict)

    def log_file(self, provider: str) -> Path:
        """Path to the log file for one provider."""
        return self.log_dir / f"{provider}.log"


def _parse_providers(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    seen: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def load_settings() -> TraiderSettings:
    """Build a ``TraiderSettings`` from the current process env."""
    providers = _parse_providers(os.environ.get("TRAIDER_PROVIDERS"))
    log_dir = Path(os.environ.get("TRAIDER_LOG_DIR", "logs")).resolve()
    return TraiderSettings(
        providers=providers,
        log_dir=log_dir,
        extra=dict(os.environ),
    )
