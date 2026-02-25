from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from typing import Any

from .control_model import CONTROL_ENV_PREFIX, CONTROL_ROOT
from .env_keypath import key_to_parts
from .env_value_parser import parse_env_value
from .live_config import SourceEntry, source_priority

_WinnerMeta = tuple[int, int, Any]
_ProjectedEntry = tuple[tuple[str, ...], Any]
_Projector = Callable[[SourceEntry], _ProjectedEntry | None]


def materialize_control_snapshot(entries: Iterable[SourceEntry]) -> dict[str, Any]:
    winners = _collect_projected_winners(entries, projector=_project_control_entry)
    return _build_snapshot_from_winners(winners)


def materialize_effective_snapshot(
    entries: Iterable[SourceEntry],
    *,
    env_prefix: str,
    case_sensitive: bool,
) -> dict[str, Any]:
    def _project(entry: SourceEntry) -> _ProjectedEntry | None:
        return _project_settings_entry(
            entry,
            env_prefix=env_prefix,
            case_sensitive=case_sensitive,
        )

    winners = _collect_projected_winners(entries, projector=_project)
    return _build_snapshot_from_winners(winners)


def _collect_projected_winners(
    entries: Iterable[SourceEntry],
    *,
    projector: _Projector,
) -> dict[tuple[str, ...], _WinnerMeta]:
    winners: dict[tuple[str, ...], _WinnerMeta] = {}
    for entry in entries:
        projected = projector(entry)
        if projected is None:
            continue

        path, value = projected
        meta = (entry.rev, source_priority(entry.source))
        existing = winners.get(path)
        if existing is not None and meta <= (existing[0], existing[1]):
            continue
        winners[path] = (meta[0], meta[1], deepcopy(value))
    return winners


def _project_control_entry(entry: SourceEntry) -> _ProjectedEntry | None:
    if entry.source == "yaml":
        return _project_yaml_control_entry(entry)
    return _project_env_control_entry(entry)


def _project_settings_entry(
    entry: SourceEntry,
    *,
    env_prefix: str,
    case_sensitive: bool,
) -> _ProjectedEntry | None:
    if entry.source == "yaml":
        return _project_yaml_settings_entry(entry)
    return _project_env_settings_entry(
        entry,
        env_prefix=env_prefix,
        case_sensitive=case_sensitive,
    )


def _project_yaml_control_entry(entry: SourceEntry) -> _ProjectedEntry | None:
    if not entry.path:
        return None
    if entry.path[0].casefold() != CONTROL_ROOT.casefold():
        return None
    canonical_path = tuple(segment.casefold() for segment in entry.path)
    return (canonical_path, entry.value)


def _project_env_control_entry(entry: SourceEntry) -> _ProjectedEntry | None:
    env_key = _entry_env_key(entry)
    if env_key is None:
        return None
    if not env_key.upper().startswith(CONTROL_ENV_PREFIX):
        return None

    raw_parts = env_key.split("__")
    if any(not part for part in raw_parts):
        return None

    return (tuple(part.lower() for part in raw_parts), _parse_env_like_value(entry.value))


def _project_yaml_settings_entry(entry: SourceEntry) -> _ProjectedEntry | None:
    if not entry.path:
        return None
    return (entry.path, entry.value)


def _project_env_settings_entry(
    entry: SourceEntry,
    *,
    env_prefix: str,
    case_sensitive: bool,
) -> _ProjectedEntry | None:
    env_key = _entry_env_key(entry)
    if env_key is None:
        return None

    parts = key_to_parts(env_key, prefix=env_prefix, case_sensitive=case_sensitive)
    if parts is None:
        return None
    return (tuple(parts), _parse_env_like_value(entry.value))


def _entry_env_key(entry: SourceEntry) -> str | None:
    if len(entry.path) != 1:
        return None
    return entry.path[0]


def _parse_env_like_value(value: Any) -> Any:
    if isinstance(value, str):
        return parse_env_value(value)
    return deepcopy(value)


def _build_snapshot_from_winners(winners: Mapping[tuple[str, ...], _WinnerMeta]) -> dict[str, Any]:
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
