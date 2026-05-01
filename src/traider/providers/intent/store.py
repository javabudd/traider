"""SQLite-backed store for trade-intent records.

The intent provider is local-only: the database lives on the user's
machine (default ``~/.traider/intents.db``, override with
``TRAIDER_INTENT_DB``) and is never synced to a brokerage or external
service. Writes are limited to this file. The traider read-only
constraint applies to *external* systems; a local journal of why
each position exists is the whole point of this provider.

The schema is one table with a few flexible JSON columns
(``tags``, ``option_details``) so the model can capture
strategy-specific context without a migration every time the user
trades a different structure.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Iterable

_DEFAULT_DB_PATH = Path.home() / ".traider" / "intents.db"

VALID_INSTRUMENTS = frozenset({"equity", "etf", "option", "future", "crypto"})
VALID_SIDES = frozenset({"buy", "sell", "short", "cover"})
VALID_STATUSES = frozenset({"planned", "open", "partially_filled", "closed", "canceled"})

VALID_CLASSES = frozenset({
    "leadership", "thematic", "speculative",
    "hedge", "dry-powder", "diversifier", "index-core",
})
VALID_LIFECYCLES = frozenset({
    "core-thematic", "swing", "managed-sleeve",
    "scale-in", "income-overlay", "rolling",
})

# Base table + base indexes. Older DBs are upgraded by _migrate()
# below, which ALTERs in any v0.5 columns and creates the indexes
# that depend on them. Two-phase setup is required because CREATE
# INDEX cannot reference a column that doesn't exist yet.
_SCHEMA_BASE = """
CREATE TABLE IF NOT EXISTS trade_intents (
    id                  TEXT PRIMARY KEY,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    instrument_type     TEXT NOT NULL,
    side                TEXT NOT NULL,
    quantity            REAL NOT NULL,
    target_price        REAL,
    fill_price          REAL,
    status              TEXT NOT NULL,
    thesis              TEXT NOT NULL,
    horizon             TEXT,
    stop_price          REAL,
    target_exit_price   REAL,
    catalysts           TEXT,
    tags                TEXT,
    option_details      TEXT,
    parent_intent_id    TEXT,
    account_id          TEXT,
    external_order_id   TEXT,
    notes               TEXT,
    -- v0.5 columns: class, lifecycle, sleeve_id, rule_refs, params,
    -- catalysts_structured. Listed here so a fresh DB has them
    -- without needing the migration step; on an existing DB the
    -- CREATE TABLE IF NOT EXISTS is a no-op and _migrate() ALTERs
    -- them in.
    class                  TEXT,
    lifecycle              TEXT,
    sleeve_id              TEXT,
    rule_refs              TEXT,
    params                 TEXT,
    catalysts_structured   TEXT
);
CREATE INDEX IF NOT EXISTS idx_trade_intents_symbol ON trade_intents(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_intents_status ON trade_intents(status);
CREATE INDEX IF NOT EXISTS idx_trade_intents_account ON trade_intents(account_id);
CREATE INDEX IF NOT EXISTS idx_trade_intents_created ON trade_intents(created_at);
"""

# Kept for backwards-compat in case anything imports _SCHEMA.
_SCHEMA = _SCHEMA_BASE

# Column names that are stored as JSON-encoded strings on disk and
# parsed to native Python on read.
_JSON_FIELDS = (
    "tags", "option_details",
    "rule_refs", "params", "catalysts_structured",
)

# Numeric (REAL) columns — coerce to float on write.
_NUMERIC_FIELDS = frozenset({
    "quantity", "target_price", "fill_price", "stop_price", "target_exit_price",
})

_COLUMNS = (
    "id", "created_at", "updated_at", "symbol", "instrument_type", "side",
    "quantity", "target_price", "fill_price", "status", "thesis", "horizon",
    "stop_price", "target_exit_price", "catalysts", "tags", "option_details",
    "parent_intent_id", "account_id", "external_order_id", "notes",
    "class", "lifecycle", "sleeve_id",
    "rule_refs", "params", "catalysts_structured",
)
_UPDATABLE = tuple(c for c in _COLUMNS if c not in {"id", "created_at"})

# Schema-evolution: columns the original v0.4 schema lacked. The
# migration runner ALTERs them in on first connect when missing.
_ADDED_COLUMNS_V05 = (
    ("class",                "TEXT"),
    ("lifecycle",            "TEXT"),
    ("sleeve_id",            "TEXT"),
    ("rule_refs",            "TEXT"),
    ("params",               "TEXT"),
    ("catalysts_structured", "TEXT"),
)
_ADDED_INDEXES_V05 = (
    "CREATE INDEX IF NOT EXISTS idx_trade_intents_class ON trade_intents(class)",
    "CREATE INDEX IF NOT EXISTS idx_trade_intents_lifecycle ON trade_intents(lifecycle)",
    "CREATE INDEX IF NOT EXISTS idx_trade_intents_sleeve ON trade_intents(sleeve_id)",
)


def _now_iso() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


def _resolve_db_path() -> Path:
    raw = os.environ.get("TRAIDER_INTENT_DB")
    return Path(raw).expanduser() if raw else _DEFAULT_DB_PATH


class IntentStore:
    """Thin SQLite wrapper. One connection per process, guarded by a lock."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _resolve_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            self.db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA_BASE)
        self._migrate()

    def _migrate(self) -> None:
        """Idempotent schema upgrades for older DBs.

        New columns added in v0.5 (class, lifecycle, sleeve_id,
        rule_refs, params, catalysts_structured) are ALTERed in if
        missing. Safe to run on every connect.
        """
        with self._lock:
            existing = {
                row["name"]
                for row in self._conn.execute(
                    "PRAGMA table_info(trade_intents)"
                ).fetchall()
            }
            for col, decl in _ADDED_COLUMNS_V05:
                if col not in existing:
                    self._conn.execute(
                        f"ALTER TABLE trade_intents ADD COLUMN {col} {decl}"
                    )
            for stmt in _ADDED_INDEXES_V05:
                self._conn.execute(stmt)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def insert(self, **fields: Any) -> dict[str, Any]:
        now = _now_iso()
        record = {
            "id": fields.get("id") or str(uuid.uuid4()),
            "created_at": now,
            "updated_at": now,
            "symbol": fields["symbol"].upper(),
            "instrument_type": fields["instrument_type"],
            "side": fields["side"],
            "quantity": float(fields["quantity"]),
            "target_price": _opt_float(fields.get("target_price")),
            "fill_price": _opt_float(fields.get("fill_price")),
            "status": fields.get("status") or "planned",
            "thesis": fields["thesis"],
            "horizon": fields.get("horizon"),
            "stop_price": _opt_float(fields.get("stop_price")),
            "target_exit_price": _opt_float(fields.get("target_exit_price")),
            "catalysts": fields.get("catalysts"),
            "tags": _dump_json(fields.get("tags")),
            "option_details": _dump_json(fields.get("option_details")),
            "parent_intent_id": fields.get("parent_intent_id"),
            "account_id": fields.get("account_id"),
            "external_order_id": fields.get("external_order_id"),
            "notes": fields.get("notes"),
            # v0.5 structured fields
            "class": fields.get("class_"),  # `class` is a Python keyword
            "lifecycle": fields.get("lifecycle"),
            "sleeve_id": fields.get("sleeve_id"),
            "rule_refs": _dump_json(fields.get("rule_refs")),
            "params": _dump_json(fields.get("params")),
            "catalysts_structured": _dump_json(fields.get("catalysts_structured")),
        }
        cols = ",".join(_COLUMNS)
        placeholders = ",".join(f":{c}" for c in _COLUMNS)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO trade_intents ({cols}) VALUES ({placeholders})",
                record,
            )
        return self.get(record["id"])  # type: ignore[return-value]

    def update(self, intent_id: str, **fields: Any) -> dict[str, Any] | None:
        existing = self.get(intent_id)
        if existing is None:
            return None

        sets: dict[str, Any] = {}
        # Caller passes `class_` (since `class` is a Python keyword); map
        # it to the column name `class` here.
        if fields.get("class_") is not None:
            fields = dict(fields)
            fields["class"] = fields.pop("class_")
        for key, value in fields.items():
            if value is None or key not in _UPDATABLE:
                continue
            if key in _JSON_FIELDS:
                sets[key] = _dump_json(value)
            elif key in _NUMERIC_FIELDS:
                sets[key] = float(value)
            elif key == "symbol":
                sets[key] = value.upper()
            else:
                sets[key] = value

        append = fields.get("append_note")
        if not sets and not append:
            return existing

        if sets:
            sets["updated_at"] = _now_iso()
            assignments = ",".join(f"{k}=:{k}" for k in sets)
            sets["id"] = intent_id
            with self._lock:
                self._conn.execute(
                    f"UPDATE trade_intents SET {assignments} WHERE id=:id", sets
                )

        # Append-only journal for `notes`. Independent of the column
        # update above so an append-only call (no other fields passed)
        # still persists.
        if append:
            stamp = _now_iso()
            line = f"[{stamp}] {append}"
            current = self.get(intent_id)
            assert current is not None
            merged = f"{current['notes']}\n{line}" if current.get("notes") else line
            with self._lock:
                self._conn.execute(
                    "UPDATE trade_intents SET notes=:notes, updated_at=:updated_at WHERE id=:id",
                    {"notes": merged, "updated_at": _now_iso(), "id": intent_id},
                )

        return self.get(intent_id)

    def get(self, intent_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM trade_intents WHERE id=?", (intent_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None

    def list(
        self,
        symbol: str | None = None,
        status: str | None = None,
        account_id: str | None = None,
        instrument_type: str | None = None,
        since: str | None = None,
        until: str | None = None,
        class_: str | None = None,
        lifecycle: str | None = None,
        sleeve_id: str | None = None,
        rule_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: dict[str, Any] = {}
        if symbol:
            clauses.append("symbol = :symbol")
            params["symbol"] = symbol.upper()
        if status:
            clauses.append("status = :status")
            params["status"] = status
        if account_id:
            clauses.append("account_id = :account_id")
            params["account_id"] = account_id
        if instrument_type:
            clauses.append("instrument_type = :instrument_type")
            params["instrument_type"] = instrument_type
        if since:
            clauses.append("created_at >= :since")
            params["since"] = since
        if until:
            clauses.append("created_at <= :until")
            params["until"] = until
        if class_:
            clauses.append("class = :class_")
            params["class_"] = class_
        if lifecycle:
            clauses.append("lifecycle = :lifecycle")
            params["lifecycle"] = lifecycle
        if sleeve_id:
            clauses.append("sleeve_id = :sleeve_id")
            params["sleeve_id"] = sleeve_id
        if rule_name:
            # rule_refs is a JSON array of objects; LIKE-match the name.
            # Acceptable for the volume of intents this DB holds.
            clauses.append("rule_refs LIKE :rule_pattern")
            params["rule_pattern"] = f'%"rule":"{rule_name}"%'
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params["limit"] = limit
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM trade_intents {where} "
                f"ORDER BY created_at DESC LIMIT :limit",
                params,
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def list_sleeve_legs(self, sleeve_id: str) -> list[dict[str, Any]]:
        """Return all open intents in one sleeve, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM trade_intents "
                "WHERE sleeve_id = ? AND status IN ('open', 'partially_filled') "
                "ORDER BY created_at ASC",
                (sleeve_id,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def delete(self, intent_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM trade_intents WHERE id=?", (intent_id,)
            )
        return cur.rowcount > 0


def _opt_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for field in _JSON_FIELDS:
        raw = out.get(field)
        out[field] = json.loads(raw) if raw else None
    return out


def validate_inputs(
    instrument_type: str, side: str, status: str | None = None
) -> None:
    if instrument_type not in VALID_INSTRUMENTS:
        raise ValueError(
            f"instrument_type must be one of {sorted(VALID_INSTRUMENTS)}; "
            f"got {instrument_type!r}"
        )
    if side not in VALID_SIDES:
        raise ValueError(
            f"side must be one of {sorted(VALID_SIDES)}; got {side!r}"
        )
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(
            f"status must be one of {sorted(VALID_STATUSES)}; got {status!r}"
        )


def coerce_iterable(value: Iterable[str] | None) -> list[str] | None:
    if value is None:
        return None
    return [str(v) for v in value]
