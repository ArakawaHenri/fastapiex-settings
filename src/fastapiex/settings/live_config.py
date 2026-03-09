from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .types import ProjectionKind, SourceName


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
