from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .control_model import CONTROL_ENV_PREFIX, CONTROL_ROOT
from .env_keypath import key_to_parts
from .env_value_parser import parse_env_value
from .live_config import SourceEntry, source_priority

_WinnerMeta = tuple[int, int, Any]
_ProjectedEntry = tuple[tuple[str, ...], Any]
_Projector = Callable[[SourceEntry], _ProjectedEntry | None]
_PathResolver = Callable[[str], tuple[str, ...] | None]


class _ProjectionPolicy(Protocol):
    def project(self, entry: SourceEntry) -> _ProjectedEntry | None: ...


@dataclass(frozen=True)
class _ControlProjectionPolicy:
    control_root: str = CONTROL_ROOT
    control_env_prefix: str = CONTROL_ENV_PREFIX

    def project(self, entry: SourceEntry) -> _ProjectedEntry | None:
        if entry.source == "yaml":
            return self._project_yaml(entry)
        return _project_env_entry(entry, key_to_path=self._control_env_key_to_path)

    def _project_yaml(self, entry: SourceEntry) -> _ProjectedEntry | None:
        if not entry.path:
            return None
        if entry.path[0].casefold() != self.control_root.casefold():
            return None
        canonical_path = tuple(segment.casefold() for segment in entry.path)
        return (canonical_path, entry.value)

    def _control_env_key_to_path(self, env_key: str) -> tuple[str, ...] | None:
        if not env_key.upper().startswith(self.control_env_prefix):
            return None
        raw_parts = env_key.split("__")
        if any(not part for part in raw_parts):
            return None
        return tuple(part.casefold() for part in raw_parts)


@dataclass(frozen=True)
class _SettingsProjectionPolicy:
    env_prefix: str
    case_sensitive: bool

    def project(self, entry: SourceEntry) -> _ProjectedEntry | None:
        if entry.source == "yaml":
            return _project_yaml_entry(entry)
        return _project_env_entry(entry, key_to_path=self._settings_env_key_to_path)

    def _settings_env_key_to_path(self, env_key: str) -> tuple[str, ...] | None:
        parts = key_to_parts(env_key, prefix=self.env_prefix, case_sensitive=self.case_sensitive)
        if parts is None:
            return None
        return tuple(parts)


_CONTROL_POLICY = _ControlProjectionPolicy()


def materialize_control_snapshot(entries: Iterable[SourceEntry]) -> dict[str, Any]:
    return _materialize_snapshot(entries, policy=_CONTROL_POLICY)


def materialize_effective_snapshot(
    entries: Iterable[SourceEntry],
    *,
    env_prefix: str,
    case_sensitive: bool,
) -> dict[str, Any]:
    policy = _SettingsProjectionPolicy(env_prefix=env_prefix, case_sensitive=case_sensitive)
    return _materialize_snapshot(entries, policy=policy)


def _materialize_snapshot(entries: Iterable[SourceEntry], *, policy: _ProjectionPolicy) -> dict[str, Any]:
    winners = _collect_projected_winners(entries, projector=policy.project)
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


def _project_yaml_entry(entry: SourceEntry) -> _ProjectedEntry | None:
    if not entry.path:
        return None
    return (entry.path, entry.value)


def _project_env_entry(
    entry: SourceEntry,
    *,
    key_to_path: _PathResolver,
) -> _ProjectedEntry | None:
    env_key = _entry_env_key(entry)
    if env_key is None:
        return None

    path = key_to_path(env_key)
    if path is None:
        return None

    return (path, _parse_env_like_value(entry.value))


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
