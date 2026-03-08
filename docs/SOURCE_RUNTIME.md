# Source Runtime Design

## Goal

The settings runtime is built around three core concepts:

- `ConfigContext`
- `SourceSpec`
- `RuntimeState`

The manager coordinates transactions, but it does not contain source-specific rules.

## Core Model

### `ConfigContext`

`ConfigContext` answers one question: "which configuration space is active right now?"

It contains:

- `settings_path`
- `anchor_dir`
- `path_mode`
- `env_prefix`
- `case_sensitive`
- `reload_mode`

`settings.path` updates the context, not a specific source implementation.

### `SourceSpec`

Every source is described by a spec:

- `name`
- `priority`
- `projection_kind`
- `policy`
- `bind(context) -> SourceBinding`
- `probe(binding) -> token`
- `load(binding) -> LoadedSource`
- `validate_final_binding(context, binding) -> None`

Builtins (`yaml`, `dotenv`, `env`) use the same contract as custom sources.

### `RuntimeState`

The committed runtime state stores:

- `sources_version`
- `last_rev`
- `context`
- `snapshots`
- `settings`

This is the only active committed state.

## Refresh Transaction

One refresh always follows the same flow:

1. Build bindings for all registered sources from the current context.
2. Probe sources that participate in the current refresh mode.
3. Load dirty sources only; clean snapshots are reused.
4. Materialize control snapshot from the candidate source snapshots.
5. Build the next context from controls.
6. If context changed, rebuild bindings and restart the round.
7. Once context is stable, run every source's `validate_final_binding`.
8. Project the effective snapshot and validate against the schema.
9. Commit atomically.

No partial state is published.

## Path Semantics

`settings.path` has only two meanings:

- `explicit_file`
- `directory_anchor`

Rules:

- explicit file paths are exact targets
- directory anchors resolve to `${anchor_dir}/settings.yaml`
- path-cycle detection is keyed by context target identity, not by full context object

## Source Policies

`SourcePolicy` controls refresh participation:

- `auto_refresh`
- `manual_refresh`
- `follow_context`
- `participates_in_controls`

Builtin defaults:

- `yaml`: auto + manual + follow-context
- `dotenv`: static by default
- `env`: static by default

Opting a source into runtime behavior means replacing its `SourceSpec`.

## Priority / LWW

LWW still applies across source snapshots.

Ordering is:

1. snapshot revision (`rev`)
2. source priority

Priority is now part of the source spec instead of being hardcoded into the manager.

## Explicit File Validation

The manager no longer hardcodes file-existence behavior per source.

If a source cares about explicit file existence, it declares that in `validate_final_binding`.

Builtin `yaml` keeps the conservative local-file check.
Custom `yaml` implementations may replace or remove that validator.

## Public Extension Surface

Advanced source customization now uses:

- `get_source(name)`
- `register_source(spec)`
- `unregister_source(name)`

The old parameterized sync API is intentionally removed.

## Design Invariants

- A committed runtime always has a single stable context.
- A committed runtime never mixes old and new snapshots within one transaction.
- Source-specific path / existence / descriptor rules belong to the source spec.
- The manager should stay agnostic to individual source implementations.
