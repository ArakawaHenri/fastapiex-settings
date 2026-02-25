from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

SourceName = Literal["yaml", "dotenv", "env"]

_SOURCE_PRIORITY: dict[SourceName, int] = {
    "yaml": 1,
    "dotenv": 2,
    "env": 3,
}
_SOURCE_ORDER: tuple[SourceName, ...] = tuple(
    sorted(_SOURCE_PRIORITY.keys(), key=lambda source: _SOURCE_PRIORITY[source])
)


@dataclass(frozen=True)
class _SourceValue:
    rev: int
    value: Any


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
            for source in _SOURCE_ORDER
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

        return deepcopy(self._cached_materialized)

    def _validate_update_sources(self, updates: Mapping[SourceName, Mapping[Any, Any]]) -> None:
        unknown_sources = set(updates) - set(_SOURCE_ORDER)
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
            winners[path] = (value.rev, _SOURCE_PRIORITY[source], value.value)
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
        meta = (value.rev, _SOURCE_PRIORITY[source])
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
    for key, value in mapping.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            if not value:
                flat[path] = {}
                continue
            nested = _flatten_mapping(value, prefix=path)
            if nested:
                flat.update(nested)
            else:
                flat[path] = {}
            continue
        flat[path] = value
    return flat


def _build_seed_slots(
    flat_by_source: Mapping[SourceName, Mapping[tuple[str, ...], Any]],
) -> dict[tuple[str, ...], dict[SourceName, _SourceValue]]:
    slots: dict[tuple[str, ...], dict[SourceName, _SourceValue]] = {}
    for source in _SOURCE_ORDER:
        source_rev = _SOURCE_PRIORITY[source]
        flat = flat_by_source[source]
        for path, value in flat.items():
            slot = slots.setdefault(path, {})
            slot[source] = _SourceValue(rev=source_rev, value=deepcopy(value))
    return slots


def _sort_sources(sources: list[SourceName]) -> list[SourceName]:
    ordered_set = set(sources)
    return [source for source in _SOURCE_ORDER if source in ordered_set]


def _build_materialized_snapshot(winners: Mapping[tuple[str, ...], tuple[int, int, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    ordered = sorted(
        winners.items(),
        key=lambda item: (item[1][0], item[1][1], len(item[0]), item[0]),
    )
    for path, (_, _, value) in ordered:
        _set_nested_force(merged, path, deepcopy(value))
    return merged


def _set_nested_force(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[path[-1]] = value


def source_order() -> tuple[SourceName, ...]:
    return _SOURCE_ORDER
