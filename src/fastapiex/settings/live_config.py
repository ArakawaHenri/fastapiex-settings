from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .constants import SOURCE_ORDER, SOURCE_PRIORITY
from .types import ProjectionKind, SourceName


@dataclass(frozen=True)
class _SourceValue:
    rev: int
    value: Any


@dataclass(frozen=True)
class SourceEntry:
    source: SourceName
    priority: int
    kind: ProjectionKind
    include_in_control: bool
    path: tuple[str, ...]
    rev: int
    value: Any


@dataclass(frozen=True)
class EntrySource:
    source: SourceName
    priority: int
    kind: ProjectionKind
    include_in_control: bool
    rev: int
    mapping: Mapping[Any, Any]


@dataclass
class _FlattenFrame:
    prefix: tuple[str, ...]
    mapping: Mapping[Any, Any]
    items: Any


class LiveConfigStore:
    """Source-aware raw configuration state using LWW + source-priority tie-break."""

    def __init__(self) -> None:
        self._slots: dict[tuple[str, ...], dict[SourceName, _SourceValue]] = {}
        self._rev: int = 0
        self._version: int = 0
        self._cached_materialized: dict[str, Any] | None = None

    def version(self) -> int:
        return self._version

    def reset(
        self,
        sources: Mapping[SourceName, Mapping[Any, Any]],
    ) -> bool:
        flat_by_source: dict[SourceName, dict[tuple[str, ...], Any]] = {
            source: _flatten_mapping(sources.get(source, {}))
            for source in SOURCE_ORDER
        }

        new_slots = _build_seed_slots(flat_by_source)
        if new_slots == self._slots:
            return False

        self._slots = new_slots
        self._rev = max((value.rev for slot in self._slots.values() for value in slot.values()), default=0)
        self._version += 1
        self._cached_materialized = None
        return True

    def replace_source(self, source: SourceName, mapping: Mapping[Any, Any]) -> bool:
        return self.replace_sources({source: mapping})

    def replace_sources(self, updates: Mapping[SourceName, Mapping[Any, Any]]) -> bool:
        self._validate_update_sources(updates)
        touched_sources, removed_by_source, updated_by_source = self._plan_source_updates(updates)
        if not touched_sources:
            return False

        rev_by_source = self._allocate_revs(touched_sources)
        self._apply_source_updates(
            touched_sources=touched_sources,
            removed_by_source=removed_by_source,
            updated_by_source=updated_by_source,
            rev_by_source=rev_by_source,
        )

        self._version += 1
        self._cached_materialized = None
        return True

    def materialize(self) -> dict[str, Any]:
        if self._cached_materialized is None:
            winners = self._compute_winners()
            self._cached_materialized = _build_materialized_snapshot(winners)

        return _clone_materialized_snapshot(self._cached_materialized)

    def entries(self) -> tuple[SourceEntry, ...]:
        rows: list[SourceEntry] = []
        for path, slot in self._slots.items():
            for source, value in slot.items():
                rows.append(
                    SourceEntry(
                        source=source,
                        priority=SOURCE_PRIORITY[source],
                        kind=_builtin_projection_kind(source),
                        include_in_control=True,
                        path=path,
                        rev=value.rev,
                        value=deepcopy(value.value),
                    )
                )
        rows.sort(key=lambda row: (row.rev, row.priority, row.path, row.source))
        return tuple(rows)

    def _validate_update_sources(self, updates: Mapping[SourceName, Mapping[Any, Any]]) -> None:
        unknown_sources = set(updates) - set(SOURCE_ORDER)
        if not unknown_sources:
            return
        unknown = ", ".join(sorted(str(source) for source in unknown_sources))
        raise ValueError(f"unknown sources: {unknown}")

    def _plan_source_updates(
        self,
        updates: Mapping[SourceName, Mapping[Any, Any]],
    ) -> tuple[
        list[SourceName],
        dict[SourceName, list[tuple[str, ...]]],
        dict[SourceName, dict[tuple[str, ...], Any]],
    ]:
        touched_sources: list[SourceName] = []
        removed_by_source: dict[SourceName, list[tuple[str, ...]]] = {}
        updated_by_source: dict[SourceName, dict[tuple[str, ...], Any]] = {}

        for source, mapping in updates.items():
            removed, updated = self._diff_source_update(source, mapping)
            if not removed and not updated:
                continue
            touched_sources.append(source)
            removed_by_source[source] = removed
            updated_by_source[source] = updated

        return touched_sources, removed_by_source, updated_by_source

    def _diff_source_update(
        self,
        source: SourceName,
        mapping: Mapping[Any, Any],
    ) -> tuple[list[tuple[str, ...]], dict[tuple[str, ...], Any]]:
        next_flat = _flatten_mapping(mapping)
        current = self._current_source_values(source)

        removed = [path for path in current if path not in next_flat]
        updated: dict[tuple[str, ...], Any] = {}
        for path, value in next_flat.items():
            existing = current.get(path)
            if existing is None or existing.value != value:
                updated[path] = deepcopy(value)
        return removed, updated

    def _apply_source_updates(
        self,
        *,
        touched_sources: list[SourceName],
        removed_by_source: Mapping[SourceName, list[tuple[str, ...]]],
        updated_by_source: Mapping[SourceName, Mapping[tuple[str, ...], Any]],
        rev_by_source: Mapping[SourceName, int],
    ) -> None:
        for source in _sort_sources(touched_sources):
            self._apply_source_path_removals(source=source, paths=removed_by_source.get(source, []))
            self._apply_source_path_updates(
                source=source,
                updates=updated_by_source.get(source, {}),
                rev=rev_by_source[source],
            )

    def _apply_source_path_removals(self, *, source: SourceName, paths: list[tuple[str, ...]]) -> None:
        for path in paths:
            slot = self._slots.get(path)
            if slot is None:
                continue
            slot.pop(source, None)
            if not slot:
                del self._slots[path]

    def _apply_source_path_updates(
        self,
        *,
        source: SourceName,
        updates: Mapping[tuple[str, ...], Any],
        rev: int,
    ) -> None:
        for path, value in updates.items():
            slot = self._slots.setdefault(path, {})
            slot[source] = _SourceValue(rev=rev, value=value)

    def _compute_winners(self) -> dict[tuple[str, ...], tuple[int, int, Any]]:
        winners: dict[tuple[str, ...], tuple[int, int, Any]] = {}
        for path, slot in self._slots.items():
            source, value = _pick_winner(slot)
            winners[path] = (value.rev, SOURCE_PRIORITY[source], value.value)
        return winners

    def _current_source_values(self, source: SourceName) -> dict[tuple[str, ...], _SourceValue]:
        result: dict[tuple[str, ...], _SourceValue] = {}
        for path, slot in self._slots.items():
            value = slot.get(source)
            if value is not None:
                result[path] = value
        return result

    def _allocate_revs(self, sources: list[SourceName]) -> dict[SourceName, int]:
        ordered = _sort_sources(sources)
        base = self._rev
        rev_by_source: dict[SourceName, int] = {}
        for offset, source in enumerate(ordered, start=1):
            rev_by_source[source] = base + offset
        self._rev = base + len(ordered)
        return rev_by_source


def _pick_winner(slot: Mapping[SourceName, _SourceValue]) -> tuple[SourceName, _SourceValue]:
    winner_source: SourceName | None = None
    winner_value: _SourceValue | None = None
    winner_meta: tuple[int, int] | None = None

    for source, value in slot.items():
        meta = (value.rev, SOURCE_PRIORITY[source])
        if winner_meta is None or meta > winner_meta:
            winner_meta = meta
            winner_source = source
            winner_value = value

    assert winner_source is not None
    assert winner_value is not None
    return winner_source, winner_value


def _flatten_mapping(
    mapping: Mapping[Any, Any],
    *,
    prefix: tuple[str, ...] = (),
) -> dict[tuple[str, ...], Any]:
    flat: dict[tuple[str, ...], Any] = {}

    stack: list[_FlattenFrame] = [
        _FlattenFrame(prefix=prefix, mapping=mapping, items=iter(_snapshot_mapping_items(mapping)))
    ]
    active_mapping_ids: set[int] = {id(mapping)}

    while stack:
        frame = stack[-1]
        try:
            key, value = next(frame.items)
        except StopIteration:
            active_mapping_ids.remove(id(frame.mapping))
            stack.pop()
            continue

        path = (*frame.prefix, str(key))
        if not isinstance(value, Mapping):
            flat[path] = value
            continue

        if not value:
            flat[path] = {}
            continue

        nested_id = id(value)
        if nested_id in active_mapping_ids:
            path_text = ".".join(path)
            raise ValueError(f"cyclic mapping detected at path '{path_text}'")

        active_mapping_ids.add(nested_id)
        stack.append(
            _FlattenFrame(prefix=path, mapping=value, items=iter(_snapshot_mapping_items(value)))
        )

    return flat


def _snapshot_mapping_items(mapping: Mapping[Any, Any]) -> tuple[tuple[Any, Any], ...]:
    for _ in range(2):
        try:
            return tuple(mapping.items())
        except (KeyError, RuntimeError):
            continue

    try:
        keys = tuple(mapping.keys())
    except (KeyError, RuntimeError):
        return ()

    items: list[tuple[Any, Any]] = []
    for key in keys:
        try:
            items.append((key, mapping[key]))
        except (KeyError, RuntimeError):
            continue
    return tuple(items)


def _build_seed_slots(
    flat_by_source: Mapping[SourceName, Mapping[tuple[str, ...], Any]],
) -> dict[tuple[str, ...], dict[SourceName, _SourceValue]]:
    slots: dict[tuple[str, ...], dict[SourceName, _SourceValue]] = {}
    for source in SOURCE_ORDER:
        source_rev = SOURCE_PRIORITY[source]
        flat = flat_by_source[source]
        for path, value in flat.items():
            slot = slots.setdefault(path, {})
            slot[source] = _SourceValue(rev=source_rev, value=deepcopy(value))
    return slots


def build_entries_from_sources(sources: Mapping[SourceName, tuple[int, Mapping[Any, Any]]]) -> tuple[SourceEntry, ...]:
    rows: list[EntrySource] = []
    for source in SOURCE_ORDER:
        source_snapshot = sources.get(source)
        if source_snapshot is None:
            continue
        rev, mapping = source_snapshot
        rows.append(
            EntrySource(
                source=source,
                priority=SOURCE_PRIORITY[source],
                kind=_builtin_projection_kind(source),
                include_in_control=True,
                rev=rev,
                mapping=mapping,
            )
        )
    return build_entries_from_mappings(rows)


def build_entries_from_mappings(sources: list[EntrySource]) -> tuple[SourceEntry, ...]:
    rows: list[SourceEntry] = []
    for source in sources:
        flat = _flatten_mapping(source.mapping)
        for path, value in flat.items():
            rows.append(
                SourceEntry(
                    source=source.source,
                    priority=source.priority,
                    kind=source.kind,
                    include_in_control=source.include_in_control,
                    path=path,
                    rev=source.rev,
                    value=deepcopy(value),
                )
            )

    rows.sort(key=lambda row: (row.rev, row.priority, row.path, row.source))
    return tuple(rows)


def _sort_sources(sources: list[SourceName]) -> list[SourceName]:
    ordered_set = set(sources)
    return [source for source in SOURCE_ORDER if source in ordered_set]


def _builtin_projection_kind(source: SourceName) -> ProjectionKind:
    return "mapping" if source == "yaml" else "env_like"


def _build_materialized_snapshot(winners: Mapping[tuple[str, ...], tuple[int, int, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    ordered = sorted(
        winners.items(),
        key=lambda item: (item[1][0], item[1][1], len(item[0]), item[0]),
    )
    for path, (_, _, value) in ordered:
        _set_nested_force(merged, path, deepcopy(value))
    return merged


def _clone_materialized_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    clone: dict[str, Any] = {}
    stack: list[tuple[Mapping[str, Any], dict[str, Any]]] = [(snapshot, clone)]

    while stack:
        source, target = stack.pop()
        for key, value in source.items():
            if isinstance(value, dict):
                child: dict[str, Any] = {}
                target[key] = child
                stack.append((value, child))
                continue

            target[key] = deepcopy(value)

    return clone


def _set_nested_force(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[path[-1]] = value
