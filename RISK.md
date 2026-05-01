# RISK.md — trade preparation methodology

The trade-preparation framework — sizing, stops, lifecycle discipline,
concentration caps, hedge management, dry-powder management, and
tax-aware timing — lives in the **`rules/`** directory at the repo
root, not in this file. Each rule is one YAML file with a stable
name, parameters, and rationale; intents reference rules by name and
capture a content hash at fill time so framework drift is detectable.

This file is the orientation. Read **`rules/README.md`** for the
schema, the override system, and the pointers to the canonical
examples.

## How to consult the framework

The MCP server's `intent` provider exposes the rules at runtime:

- **`list_rules(applies_to_class?, governs_decision?, kind?)`** —
  scan the framework. Returns lightweight summaries.
- **`get_rule(name)`** — fetch one rule's full body (parameters,
  exit triggers, rationale, related rules).
- **`get_position_context(symbol)`** — for a held position, returns
  the open intents on it, the rules they reference (with parameters
  resolved), drift flags, and any sleeve aggregates in one bundle.
- **`validate_intent_rule_refs(intent_id?)`** — surface dangling
  references and content-hash drift relative to current rule state.
- **`reload_rules()`** — re-read `rules/` and `rules.local/` after
  an edit without restarting the server.

When trade preparation is in scope, prefer these tools over
re-reading prose. Fall back to `Read rules/<rule>.yaml` if the MCP
isn't loaded.

## Hard constraints (do not relax)

These survive any rule change because they sit above the framework:

- **Read-only.** Nothing in traider places orders, creates alerts,
  or writes to any external service. The intent journal writes
  *locally* to a SQLite file the user owns. You help prepare
  orders; you never send them. See `AGENTS.md`.
- **Size from risk, not from conviction.** A position's size is
  derived from the stop distance for stop-anchored trades, or from
  the per-class concentration cap for core/diversifier/dry-powder
  positions. Conviction does not size positions.
- **Stops are technical or thesis-based, never dollar-based.** A
  stop says "the thesis is wrong." It belongs at a level the
  market respects (swing structure, ATR-multiple, named catalyst
  date), not at an arbitrary P&L. Core thematic holds run on
  thesis-stops, not mechanical stops — see
  `rules/core-thematic-hold.yaml`.
- **Tax tail does not wag the risk dog.** Cap-forced or
  thesis-stop trims execute regardless of after-tax math; the tax
  rules inform *discretionary* trims only. See
  `rules/wash-sale-window.yaml`,
  `rules/holding-period-boundary.yaml`,
  `rules/lot-method-verification.yaml`.

## What you still don't do

Even with the framework loaded, you do not:

- place orders, or suggest the user place one without showing the
  sizing / stop / R/R work the rules require,
- guarantee outcomes or assign probabilities tools don't return,
- recommend leverage or size beyond what the rules support,
- give tax advice beyond flagging mechanical rules. For planning,
  defer to the user's CPA.

## Where to add a rule

When a recurring decision pattern shows up in a third intent — a
new lifecycle, a new tax discipline, a new hedge structure — that's
the trigger to add a rule file at `rules/<name>.yaml`, not to write
the same prose into a fourth intent. See `rules/README.md` for the
schema. The "promote on third occurrence" discipline is what keeps
the framework lean and the intents short.

## Per-user overrides

Edit a rule for your own use without dirtying git: drop a partial
override at `rules.local/<name>.yaml` (the directory is gitignored).
The loader merges overrides on top of the seed at startup and logs
divergence visibly. See `rules/README.md` for merge semantics.
