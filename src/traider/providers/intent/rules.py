"""YAML rules loader with seed + per-user overlay.

Rules are framework-level decision discipline (concentration caps,
position lifecycles, hedge management, sizing, tax) that intents
reference by name. Each rule is one YAML file at ``rules/<name>.yaml``;
per-user overrides live at ``rules.local/<name>.yaml`` (gitignored).

Loader behavior:

- Walks the seed directory first, parsing each ``*.yaml`` file.
- Walks the overlay directory if it exists, merging per-rule on top
  of the seed (deep-merge on ``parameters``, whole-replace on arrays,
  full-replace on scalars).
- Validates each rule against the schema (known top-level keys,
  enum values, required fields).
- Computes a content_hash per *merged* rule so intents can capture
  drift relative to whatever was effective when they were filed.
- Logs every active override on startup so divergence is visible.

The module is local: nothing here calls out to a brokerage or external
service. The traider read-only constraint is preserved.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("traider.intent.rules")

# ---------------------------------------------------------------------------
# Schema enums

VALID_KINDS = frozenset({
    "concentration-cap",
    "lifecycle",
    "hedge-mgmt",
    "tax-discipline",
    "sizing",
})

VALID_CLASSES = frozenset({
    "leadership",
    "thematic",
    "speculative",
    "hedge",
    "dry-powder",
    "diversifier",
    "index-core",
})

VALID_ACCOUNT_TYPES = frozenset({"taxable", "ira", "401k", "roth-ira", "hsa"})

VALID_DECISIONS = frozenset({
    "add", "trim", "open", "close", "exit", "reentry",
    "monetize", "roll", "rotate", "rebuy", "rebalance",
    "scale-in", "deploy", "replenish",
    "portfolio-check", "hold-through-event",
    "evaluate-trade-idea", "evaluate-after-tax-rr",
    "evaluate-after-tax-yield", "tax-loss-harvest",
    "select-vehicle", "hold", "distribute", "target-set", "partial-exit",
})

# Top-level keys allowed in a rule yaml. Loader rejects unknown keys
# (catches typos before they silently disable validation).
ALLOWED_TOP_LEVEL_KEYS = frozenset({
    "name", "version", "kind",
    "applies_to_class", "applies_to_account_type",
    "governs_decisions",
    "parameters", "requires_intent_params",
    "exit_triggers", "rationale", "related_rules",
})

REQUIRED_TOP_LEVEL_KEYS = frozenset({
    "name", "version", "kind",
    "applies_to_class", "governs_decisions",
    "rationale",
})

# Fields that array-merge as whole-replace in overlays (not deep-merge).
ARRAY_REPLACE_FIELDS = frozenset({
    "applies_to_class", "applies_to_account_type",
    "governs_decisions", "exit_triggers",
    "requires_intent_params", "related_rules",
})

# Fields that deep-merge in overlays (key-by-key on a dict).
DEEP_MERGE_FIELDS = frozenset({"parameters"})


# ---------------------------------------------------------------------------
# Rule dataclass

@dataclass(frozen=True)
class Rule:
    """A single framework rule, post-merge of seed + overlay."""

    name: str
    version: int
    kind: str
    applies_to_class: tuple[str, ...]
    governs_decisions: tuple[str, ...]
    rationale: str
    parameters: dict[str, Any] = field(default_factory=dict)
    requires_intent_params: tuple[str, ...] = ()
    exit_triggers: tuple[dict[str, Any], ...] = ()
    related_rules: tuple[str, ...] = ()
    applies_to_account_type: tuple[str, ...] | None = None
    content_hash: str = ""
    source_files: tuple[Path, ...] = ()
    overridden_fields: tuple[str, ...] = ()

    def to_dict(self, *, include_rationale: bool = True) -> dict[str, Any]:
        """Plain-dict shape for JSON-serializable MCP responses."""
        out: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "applies_to_class": list(self.applies_to_class),
            "governs_decisions": list(self.governs_decisions),
            "parameters": self.parameters,
            "requires_intent_params": list(self.requires_intent_params),
            "related_rules": list(self.related_rules),
            "content_hash": self.content_hash,
            "overridden_fields": list(self.overridden_fields),
        }
        if self.applies_to_account_type is not None:
            out["applies_to_account_type"] = list(self.applies_to_account_type)
        if self.exit_triggers:
            out["exit_triggers"] = list(self.exit_triggers)
        if include_rationale:
            out["rationale"] = self.rationale
        return out

    def summary(self) -> dict[str, Any]:
        """Lightweight index entry — no rationale, no parameters detail.

        Use for ``list_rules`` so the AI can scan available rules
        without paying the body cost.
        """
        first_line = self.rationale.strip().split("\n", 1)[0]
        return {
            "name": self.name,
            "version": self.version,
            "kind": self.kind,
            "applies_to_class": list(self.applies_to_class),
            "governs_decisions": list(self.governs_decisions),
            "summary": first_line,
            "content_hash": self.content_hash,
            "overridden": bool(self.overridden_fields),
        }


# ---------------------------------------------------------------------------
# Rules index

class RulesIndex:
    """In-memory index of all loaded rules, keyed by name."""

    def __init__(self, rules: dict[str, Rule]) -> None:
        self._rules = rules

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, name: str) -> bool:
        return name in self._rules

    def get(self, name: str) -> Rule | None:
        return self._rules.get(name)

    def all(self) -> list[Rule]:
        return list(self._rules.values())

    def filter(
        self,
        applies_to_class: str | None = None,
        governs_decision: str | None = None,
        kind: str | None = None,
    ) -> list[Rule]:
        out = []
        for rule in self._rules.values():
            if applies_to_class and applies_to_class not in rule.applies_to_class:
                continue
            if governs_decision and governs_decision not in rule.governs_decisions:
                continue
            if kind and rule.kind != kind:
                continue
            out.append(rule)
        return out

    def validate_refs(
        self, rule_refs: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Check intent rule_refs against the current index.

        Returns a dict with three lists:
          - ``dangling``: refs whose ``rule`` name does not resolve.
          - ``drifted``: refs whose ``content_hash_at_fill`` differs from
            the current merged rule's hash.
          - ``stale_versions``: refs whose ``version`` field is older
            than the current rule's version.
        """
        dangling: list[dict[str, Any]] = []
        drifted: list[dict[str, Any]] = []
        stale: list[dict[str, Any]] = []
        for ref in rule_refs or []:
            name = ref.get("rule")
            if not name or name not in self._rules:
                dangling.append(ref)
                continue
            rule = self._rules[name]
            if (
                ref.get("content_hash_at_fill")
                and ref["content_hash_at_fill"] != rule.content_hash
            ):
                drifted.append({
                    "rule": name,
                    "stored_hash": ref["content_hash_at_fill"],
                    "current_hash": rule.content_hash,
                    "stored_version": ref.get("version"),
                    "current_version": rule.version,
                })
            if (
                ref.get("version") is not None
                and ref["version"] < rule.version
            ):
                stale.append({
                    "rule": name,
                    "stored_version": ref["version"],
                    "current_version": rule.version,
                })
        return {"dangling": dangling, "drifted": drifted, "stale_versions": stale}


# ---------------------------------------------------------------------------
# Loader


class RuleValidationError(ValueError):
    """Raised when a rule yaml fails schema validation."""


def _resolve_seed_dir() -> Path:
    """Find the rules/ directory.

    Order:
      1. ``TRAIDER_RULES_DIR`` env var if set.
      2. ``Path.cwd() / "rules"`` if it exists (running from repo root).
      3. Walk up from this file to find a sibling ``rules/`` directory.
    """
    raw = os.environ.get("TRAIDER_RULES_DIR")
    if raw:
        return Path(raw).expanduser().resolve()

    cwd_candidate = Path.cwd() / "rules"
    if cwd_candidate.is_dir():
        return cwd_candidate.resolve()

    # Walk up from this file looking for rules/
    here = Path(__file__).resolve()
    for ancestor in (here, *here.parents):
        candidate = ancestor / "rules"
        if candidate.is_dir() and (candidate / "README.md").exists():
            return candidate.resolve()

    raise FileNotFoundError(
        "rules directory not found. Set TRAIDER_RULES_DIR or run from "
        "the repo root."
    )


def _resolve_overlay_dir(seed_dir: Path) -> Path | None:
    """Per-user overlay dir is ``rules.local/`` next to the seed dir."""
    raw = os.environ.get("TRAIDER_RULES_LOCAL_DIR")
    if raw:
        path = Path(raw).expanduser().resolve()
        return path if path.is_dir() else None
    candidate = seed_dir.parent / "rules.local"
    return candidate.resolve() if candidate.is_dir() else None


def _parse_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise RuleValidationError(f"{path}: invalid YAML — {exc}") from exc
    if not isinstance(data, dict):
        raise RuleValidationError(f"{path}: top level must be a mapping")
    return data


def _validate_seed(name: str, raw: dict[str, Any], path: Path) -> None:
    """Schema check on a seed file. Stricter than overlay validation."""
    if raw.get("name") != name:
        raise RuleValidationError(
            f"{path}: name field {raw.get('name')!r} does not match "
            f"filename {name!r}"
        )
    missing = REQUIRED_TOP_LEVEL_KEYS - set(raw.keys())
    if missing:
        raise RuleValidationError(
            f"{path}: missing required keys: {sorted(missing)}"
        )
    unknown = set(raw.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise RuleValidationError(
            f"{path}: unknown top-level keys: {sorted(unknown)}"
        )
    if raw["kind"] not in VALID_KINDS:
        raise RuleValidationError(
            f"{path}: kind must be one of {sorted(VALID_KINDS)}; "
            f"got {raw['kind']!r}"
        )
    classes = raw["applies_to_class"]
    if not isinstance(classes, list) or not classes:
        raise RuleValidationError(
            f"{path}: applies_to_class must be a non-empty list"
        )
    bad = [c for c in classes if c not in VALID_CLASSES]
    if bad:
        raise RuleValidationError(
            f"{path}: applies_to_class has unknown values: {bad}"
        )
    decisions = raw["governs_decisions"]
    if not isinstance(decisions, list) or not decisions:
        raise RuleValidationError(
            f"{path}: governs_decisions must be a non-empty list"
        )
    bad = [d for d in decisions if d not in VALID_DECISIONS]
    if bad:
        raise RuleValidationError(
            f"{path}: governs_decisions has unknown values: {bad}"
        )
    acct = raw.get("applies_to_account_type")
    if acct is not None:
        if not isinstance(acct, list):
            raise RuleValidationError(
                f"{path}: applies_to_account_type must be a list when present"
            )
        bad = [a for a in acct if a not in VALID_ACCOUNT_TYPES]
        if bad:
            raise RuleValidationError(
                f"{path}: applies_to_account_type has unknown values: {bad}"
            )
    if not isinstance(raw["rationale"], str) or not raw["rationale"].strip():
        raise RuleValidationError(f"{path}: rationale must be a non-empty string")


def _validate_overlay(name: str, raw: dict[str, Any], path: Path) -> None:
    """Schema check on an overlay file. Looser — only the keys present."""
    if raw.get("name") != name:
        raise RuleValidationError(
            f"{path}: name field {raw.get('name')!r} does not match "
            f"filename {name!r}"
        )
    unknown = set(raw.keys()) - ALLOWED_TOP_LEVEL_KEYS
    if unknown:
        raise RuleValidationError(
            f"{path}: unknown top-level keys in overlay: {sorted(unknown)}"
        )


def _merge(seed: dict[str, Any], overlay: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Apply overlay on top of seed per documented merge semantics.

    Returns (merged, overridden_field_paths) where overridden_field_paths
    is a list of dotted paths describing what changed (for the startup log).
    """
    merged = dict(seed)
    overridden: list[str] = []
    for key, ov_val in overlay.items():
        if key == "name":
            continue  # always equal to seed name; just an identifier
        if key in DEEP_MERGE_FIELDS and isinstance(ov_val, dict):
            seed_dict = dict(seed.get(key, {}))
            for k, v in ov_val.items():
                if seed_dict.get(k) != v:
                    overridden.append(f"{key}.{k}")
                seed_dict[k] = v
            merged[key] = seed_dict
        elif key in ARRAY_REPLACE_FIELDS:
            if seed.get(key) != ov_val:
                overridden.append(key)
            merged[key] = ov_val
        else:
            if seed.get(key) != ov_val:
                overridden.append(key)
            merged[key] = ov_val
    return merged, overridden


def _content_hash(merged: dict[str, Any]) -> str:
    """SHA256 of the canonical JSON of the merged rule.

    Hashing the parsed structure (not raw YAML text) makes the hash
    invariant to comments, key order, and whitespace — only semantic
    changes shift the hash.
    """
    canonical = json.dumps(merged, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_rule(merged: dict[str, Any], sources: list[Path], overridden: list[str]) -> Rule:
    return Rule(
        name=merged["name"],
        version=int(merged["version"]),
        kind=merged["kind"],
        applies_to_class=tuple(merged["applies_to_class"]),
        applies_to_account_type=(
            tuple(merged["applies_to_account_type"])
            if merged.get("applies_to_account_type") is not None
            else None
        ),
        governs_decisions=tuple(merged["governs_decisions"]),
        parameters=merged.get("parameters", {}) or {},
        requires_intent_params=tuple(merged.get("requires_intent_params", []) or []),
        exit_triggers=tuple(merged.get("exit_triggers", []) or []),
        rationale=merged["rationale"],
        related_rules=tuple(merged.get("related_rules", []) or []),
        content_hash=_content_hash(merged),
        source_files=tuple(sources),
        overridden_fields=tuple(overridden),
    )


def load_rules(
    seed_dir: Path | None = None,
    overlay_dir: Path | None = None,
) -> RulesIndex:
    """Build a RulesIndex from seed YAMLs + optional per-user overlay.

    Seed-dir defaults are resolved via env var or repo-root walk; pass
    explicit paths to bypass discovery (e.g. in tests).
    """
    seed_dir = seed_dir or _resolve_seed_dir()
    overlay_dir = overlay_dir or _resolve_overlay_dir(seed_dir)

    rules: dict[str, Rule] = {}
    seed_files = sorted(seed_dir.glob("*.yaml"))
    if not seed_files:
        logger.warning("rules seed directory %s has no *.yaml files", seed_dir)

    overlay_log_lines: list[str] = []

    for path in seed_files:
        name = path.stem
        try:
            seed_raw = _parse_yaml(path)
            _validate_seed(name, seed_raw, path)
        except RuleValidationError:
            logger.exception("rule %s failed seed validation", name)
            raise

        sources = [path]
        overridden: list[str] = []
        merged = seed_raw

        if overlay_dir is not None:
            overlay_path = overlay_dir / f"{name}.yaml"
            if overlay_path.exists():
                overlay_raw = _parse_yaml(overlay_path)
                _validate_overlay(name, overlay_raw, overlay_path)
                merged, overridden = _merge(seed_raw, overlay_raw)
                sources.append(overlay_path)
                # Re-validate the merged result for type/enum sanity.
                try:
                    _validate_seed(name, merged, overlay_path)
                except RuleValidationError:
                    logger.exception(
                        "rule %s overlay produced an invalid merged result",
                        name,
                    )
                    raise

                for path_str in overridden:
                    seed_val = _resolve_path(seed_raw, path_str)
                    over_val = _resolve_path(merged, path_str)
                    overlay_log_lines.append(
                        f"  {name}: {path_str} {seed_val!r} → {over_val!r}"
                    )

        rules[name] = _build_rule(merged, sources, overridden)

    logger.info(
        "loaded %d rules from %s",
        len(rules),
        seed_dir,
    )
    if overlay_log_lines:
        logger.info(
            "applied %d overrides from %s:\n%s",
            len(overlay_log_lines),
            overlay_dir,
            "\n".join(overlay_log_lines),
        )

    return RulesIndex(rules)


def _resolve_path(data: dict[str, Any], dotted: str) -> Any:
    """Walk a dotted path through nested dicts. Returns None if missing."""
    cur: Any = data
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


# ---------------------------------------------------------------------------
# Singleton accessor (lazy)

_index: RulesIndex | None = None


def get_index() -> RulesIndex:
    """Return the process-wide RulesIndex, loading on first call."""
    global _index
    if _index is None:
        _index = load_rules()
    return _index


def reload_index() -> RulesIndex:
    """Force-reload from disk. Useful after editing a rule file."""
    global _index
    _index = load_rules()
    return _index
