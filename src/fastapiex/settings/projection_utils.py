from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from .casefold_mapping import build_casefold_mapping

WinnerMeta = tuple[int, int, Any]


def set_nested_force(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = target
    for part in path[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[path[-1]] = value


def build_snapshot_from_winners(winners: Mapping[tuple[str, ...], WinnerMeta]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    ordered = sorted(
        winners.items(),
        key=lambda item: (item[1][0], item[1][1], len(item[0]), item[0]),
    )
    for path, (_, _, value) in ordered:
        set_nested_force(merged, path, deepcopy(value))
    return merged


def merge_nested_mapping(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            merge_nested_mapping(existing, value)
            continue
        target[key] = deepcopy(value)


def assign_projected_value(target: dict[str, Any], key: str, value: Any) -> None:
    existing = target.get(key)
    if isinstance(existing, dict) and isinstance(value, Mapping):
        merge_nested_mapping(existing, value)
        return
    target[key] = deepcopy(value)


def normalize_control_mapping(raw: Mapping[Any, Any]) -> dict[str, Any]:
    return build_casefold_mapping(raw, deepcopy_values=True)
