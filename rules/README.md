# Rules

Canonical framework rules consumed by the AI analyst at runtime. Each
rule is one YAML file. Filename (sans extension) is the rule name and
the stable reference key.

Intents in the database reference rules by name (`rule_refs: [{rule:
"hedge-sleeve", ...}]`). The MCP server resolves references to file
contents on each read; broken references fail validation at intent
write time.

## How the AI uses these

The AI analyst:
- calls `list_rules(...)` to see what's in the framework,
- calls `get_rule(name)` for the bodies of rules a current decision
  depends on,
- captures `content_hash` of each referenced rule at the moment an
  intent is recorded — drift between fill-time and current is
  surfaced automatically without forcing version-pinning.

Rules are *not* loaded as a single document. The AI does not read
`rules/` end-to-end; it queries by name.

## Editing a rule (canonical)

`vim rules/<rule-name>.yaml`. Commit the change. The `version:` field
in the YAML increments on **material** edits (parameter changes,
exit-trigger semantics, applies-to scope). Cosmetic edits (typos,
phrasing) leave `version` alone — the file's content_hash will
change either way.

Material rule edits should walk the open intents that reference the
rule (the loader logs which) and decide whether each remains fitted
to the new framework or needs an update.

## Editing a rule locally without committing — `rules.local/`

To change a rule for your own use without dirtying git, drop a
partial override file at `rules.local/<rule-name>.yaml`. The
directory is gitignored. The loader merges any override on top of
the seed at startup.

Override file shape — only the fields you want to change need
appear; the loader infers everything else from the seed:

```yaml
# rules.local/leadership-cap.yaml — gitignored
name: leadership-cap         # required: tells the loader what is being overridden
parameters:
  cap_pct_nlv: 30             # overrides seed value of 25; siblings preserved
```

Merge semantics:

- `parameters` — deep-merged at the key level. Set only the keys you
  want to change; siblings come from the seed.
- `exit_triggers`, `requires_intent_params`, `applies_to_class`,
  `governs_decisions` — arrays are *whole-replace*. To change one
  trigger, write the full array. (Array-by-index or array-by-name
  merging is more confusing than it is concise.)
- `rationale`, `name`, `version`, `kind`, `related_rules` — full
  replacement.
- Unknown top-level keys are rejected. Catches typos.

The loader logs every active override on startup so divergence from
seed is visible:

```
[rules] loaded 20 rules from rules/
[rules] applied 1 override from rules.local/:
[rules]   leadership-cap: parameters.cap_pct_nlv 25 → 30
```

`traider rules diff` shows the same in-place (planned). `traider
rules reset <name>` deletes the override file (planned).

## Drift vs override — distinct

- **Override** — intentional persistent local change in
  `rules.local/`. Visible at startup; not in git. Not a problem.
- **Drift** — a seed `rules/<name>.yaml` was edited upstream after
  an intent was recorded. Caught via `content_hash_at_fill`
  mismatch when the intent is read. Surfaces as a flag on the
  intent, not on the rule.

The hash captured at intent record time is computed against the
*merged* (post-overlay) rule, so adding an override after an intent
was filed shows up as drift on that intent — overrides do not
escape the audit trail, they just don't pollute git history.

## Per-account overrides (future)

The same overlay convention extends to per-account scope when
needed:

```
rules.local/                          user-wide overrides
rules.local/<account_id>/             account-specific overrides
```

Merge order: `rules/` < `rules.local/` < `rules.local/<active>/`.
Not needed for v1; the design supports it without rework.

## Rule schema reference

Each rule YAML carries:

```yaml
name: <string>                      # required, must equal filename sans ext
version: <int>                      # increments on material change
kind: <enum>                        # concentration-cap | lifecycle |
                                    # tax-discipline | sizing | hedge-mgmt
applies_to_class: [<enum>...]       # which intent class triggers this
                                    # (leadership | thematic | speculative |
                                    #  hedge | dry-powder | diversifier |
                                    #  index-core)
applies_to_account_type: [<enum>...]   # optional; defaults to all
governs_decisions: [<enum>...]      # add | trim | exit | open | close |
                                    # monetize | roll | rotate | rebuy |
                                    # rebalance | portfolio-check |
                                    # hold-through-event

parameters:                         # rule-level constants. Schema-validated.
  <key>: <value>                    # primitives, ranges {min, max}, lists.

requires_intent_params:             # intent-level params the rule expects
  - <param_name>                    # e.g. trim_rungs, exit_levels, etc.
                                    # validated when an intent references
                                    # the rule.

exit_triggers:                      # named triggers, when applicable
  - name: <string>
    spec: <prose description>
    requires_params: [<param>...]   # which intent params the trigger reads

rationale: |                        # human-readable why; attached to the rule,
  <multi-line prose>                # not duplicated across intents.

related_rules: [<name>...]          # cross-references for "see also"
```

See `leadership-cap.yaml`, `core-thematic-hold.yaml`, `hedge-sleeve.yaml`,
and `wash-sale-window.yaml` as canonical examples covering the four
distinct rule shapes (concentration-cap, lifecycle, hedge-mgmt,
tax-discipline).
