from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .context import ConfigContext
from .live_config import EntrySource, build_entries_from_mappings
from .projection import materialize_control_snapshot
from .runtime_state import SourceSnapshot
from .source_contract import SourceRegistry, SourceSpec
from .types import SourceSyncMode

_MAX_CONTROL_HOPS = 16


@dataclass(frozen=True)
class CandidateRuntime:
    last_rev: int
    context: ConfigContext
    snapshots: dict[str, SourceSnapshot]
    changed: bool


def build_candidate_runtime(
    *,
    initial_context: ConfigContext,
    current_snapshots: Mapping[str, SourceSnapshot],
    current_last_rev: int,
    mode: SourceSyncMode,
    sources: SourceRegistry,
    build_context_from_controls: Callable[[Mapping[str, Any], ConfigContext], ConfigContext],
    logger: logging.Logger,
) -> CandidateRuntime:
    context = initial_context
    snapshots = dict(current_snapshots)
    last_rev = current_last_rev
    changed = False
    visited_targets: set[tuple[object, object]] = {context.cycle_key()}

    for _ in range(_MAX_CONTROL_HOPS):
        refreshed_snapshots, refreshed_last_rev, refreshed = refresh_snapshot_set(
            mode=mode,
            context=context,
            current=snapshots,
            current_last_rev=last_rev,
            sources=sources,
        )
        if not refreshed and not changed and context == initial_context:
            return CandidateRuntime(
                last_rev=refreshed_last_rev,
                context=context,
                snapshots=refreshed_snapshots,
                changed=False,
            )

        control_snapshot = materialize_control_snapshot(
            build_entries_from_runtime_snapshots(refreshed_snapshots, sources=sources)
        )
        next_context = build_context_from_controls(control_snapshot, context)

        if next_context.cycle_key() != context.cycle_key():
            if next_context.cycle_key() in visited_targets:
                logger.warning(
                    "settings path control cycle detected; keeping path=%s",
                    context.settings_path,
                )
                return CandidateRuntime(
                    last_rev=refreshed_last_rev,
                    context=context,
                    snapshots=refreshed_snapshots,
                    changed=True,
                )

            visited_targets.add(next_context.cycle_key())
            context = next_context
            snapshots = refreshed_snapshots
            last_rev = refreshed_last_rev
            changed = True
            continue

        if next_context != context:
            context = next_context
            snapshots = refreshed_snapshots
            last_rev = refreshed_last_rev
            changed = True
            continue

        return CandidateRuntime(
            last_rev=refreshed_last_rev,
            context=context,
            snapshots=refreshed_snapshots,
            changed=changed or refreshed or context != initial_context,
        )

    logger.warning("settings control convergence hop limit reached; keeping path=%s", context.settings_path)
    return CandidateRuntime(
        last_rev=last_rev,
        context=context,
        snapshots=snapshots,
        changed=True,
    )


def refresh_snapshot_set(
    *,
    mode: SourceSyncMode,
    context: ConfigContext,
    current: Mapping[str, SourceSnapshot],
    current_last_rev: int,
    sources: SourceRegistry,
) -> tuple[dict[str, SourceSnapshot], int, bool]:
    if mode == "none":
        return dict(current), current_last_rev, False

    if mode == "auto" and context.reload_mode == "off":
        return dict(current), current_last_rev, False

    next_snapshots: dict[str, SourceSnapshot] = {}
    changed_snapshots: list[tuple[SourceSpec, SourceSnapshot]] = []

    for spec in sources.ordered():
        previous = current.get(spec.name)
        binding = (
            previous.binding
            if previous is not None and not spec.policy.follow_context and mode != "full"
            else spec.bind(context)
        )
        if not _should_load_source(
            spec=spec,
            context=context,
            previous=previous,
            binding=binding,
            mode=mode,
        ):
            if previous is not None:
                next_snapshots[spec.name] = previous
            continue

        loaded = spec.load(binding)
        previous_rev = 0 if previous is None else previous.rev
        snapshot = SourceSnapshot(
            source=spec.name,
            rev=previous_rev,
            binding=binding,
            token=loaded.token,
            payload=loaded.payload,
        )
        if previous == snapshot:
            if previous is not None:
                next_snapshots[spec.name] = previous
            continue
        changed_snapshots.append((spec, snapshot))

    next_last_rev = current_last_rev
    for offset, (spec, snapshot) in enumerate(changed_snapshots, start=1):
        next_last_rev = current_last_rev + offset
        next_snapshots[spec.name] = SourceSnapshot(
            source=spec.name,
            rev=next_last_rev,
            binding=snapshot.binding,
            token=snapshot.token,
            payload=snapshot.payload,
        )

    return next_snapshots, next_last_rev, bool(changed_snapshots)


def build_entries_from_runtime_snapshots(
    snapshots: Mapping[str, SourceSnapshot],
    *,
    sources: SourceRegistry,
) -> tuple[Any, ...]:
    rows: list[EntrySource] = []
    for spec in sources.ordered():
        snapshot = snapshots.get(spec.name)
        if snapshot is None:
            continue
        rows.append(
            EntrySource(
                source=spec.name,
                priority=spec.priority,
                kind=spec.projection_kind,
                include_in_control=spec.policy.participates_in_controls,
                rev=snapshot.rev,
                mapping=snapshot.payload,
            )
        )
    return build_entries_from_mappings(rows)


def validate_final_source_bindings(
    *,
    context: ConfigContext,
    snapshots: Mapping[str, SourceSnapshot],
    sources: SourceRegistry,
) -> None:
    for spec in sources.ordered():
        if spec.validate_final_binding is None:
            continue
        snapshot = snapshots.get(spec.name)
        binding = spec.bind(context) if snapshot is None else snapshot.binding
        spec.validate_final_binding(context, binding)


def _should_load_source(
    *,
    spec: SourceSpec,
    context: ConfigContext,
    previous: SourceSnapshot | None,
    binding: Any,
    mode: SourceSyncMode,
) -> bool:
    if previous is None:
        return True

    if binding != previous.binding and spec.policy.follow_context:
        return True

    if mode == "full":
        return True

    if mode == "reload":
        return spec.policy.manual_refresh

    if mode != "auto":
        return False

    if context.reload_mode == "always":
        return spec.policy.auto_refresh

    if not spec.policy.auto_refresh:
        return False

    probe_token = spec.probe(binding)
    return probe_token != previous.token


__all__ = [
    "build_candidate_runtime",
    "build_entries_from_runtime_snapshots",
    "CandidateRuntime",
    "refresh_snapshot_set",
    "validate_final_source_bindings",
]
