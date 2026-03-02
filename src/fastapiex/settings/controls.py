from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, TypeVar

from .constants import SETTINGS_FILENAME
from .control_contract import CONTROL_SPEC, ControlModel
from .loader import load_env_overrides


def _merge_casefold_mapping(
    target: dict[str, Any],
    incoming: Mapping[Any, Any],
) -> None:
    for key, value in incoming.items():
        if not isinstance(key, str):
            continue
        canonical_key = key.casefold()
        if isinstance(value, Mapping):
            existing = target.get(canonical_key)
            nested: dict[str, Any]
            if isinstance(existing, dict):
                nested = existing
            else:
                nested = {}
                target[canonical_key] = nested
            _merge_casefold_mapping(nested, value)
            continue
        target[canonical_key] = value


def normalize_control_snapshot(snapshot: Mapping[Any, Any]) -> dict[str, Any]:
    return _extract_control_mapping(snapshot, CONTROL_SPEC.path)


def read_control_model(snapshot: Mapping[Any, Any]) -> ControlModel:
    normalized = normalize_control_snapshot(snapshot)
    return ControlModel.model_validate(normalized)


def _extract_control_mapping(
    snapshot: Mapping[Any, Any],
    path: tuple[str, ...],
) -> dict[str, Any]:
    candidates: list[Mapping[Any, Any]] = [snapshot]

    for segment in path:
        next_candidates: list[Mapping[Any, Any]] = []
        for candidate in candidates:
            for key, value in candidate.items():
                if not isinstance(key, str):
                    continue
                if key.casefold() != segment.casefold():
                    continue
                if isinstance(value, Mapping):
                    next_candidates.append(value)
        if not next_candidates:
            return {}
        candidates = next_candidates

    merged: dict[str, Any] = {}
    for candidate in candidates:
        _merge_casefold_mapping(merged, candidate)
    return merged


def normalize_override_path(raw: str | Path | None, *, as_directory: bool = False) -> Path | None:
    if raw is None:
        return None

    if isinstance(raw, Path):
        path = raw.expanduser()
    else:
        text = raw.strip()
        if not text:
            return None
        path = Path(text).expanduser()

    if as_directory:
        return path.resolve()

    if path.suffix.lower() in {".yaml", ".yml"}:
        return path.resolve()

    return (path / SETTINGS_FILENAME).resolve()


def build_env_controls_snapshot() -> Mapping[Any, Any]:
    return load_env_overrides(prefix="", case_sensitive=False)


class SupportsSettingsPath(Protocol):
    @property
    def settings_path(self) -> Path: ...


SourceT = TypeVar("SourceT", bound=SupportsSettingsPath)


def converge_control_source(
    *,
    initial_source: SourceT,
    materialize_control_snapshot: Callable[[], dict[str, Any]],
    build_source_from_controls: Callable[[Mapping[str, Any]], SourceT],
    on_path_switch: Callable[[SourceT], None],
    stabilize_path: Callable[[SourceT, Path], SourceT],
    logger: logging.Logger,
) -> tuple[SourceT, bool]:
    source = initial_source
    changed = False
    visited_paths: set[Path] = {source.settings_path}

    while True:
        control_snapshot = materialize_control_snapshot()
        next_source = build_source_from_controls(control_snapshot)

        if next_source.settings_path != source.settings_path:
            if next_source.settings_path in visited_paths:
                logger.warning("settings path control cycle detected; keeping path=%s", source.settings_path)
                stabilized = stabilize_path(next_source, source.settings_path)
                changed = changed or stabilized != source
                return stabilized, changed

            visited_paths.add(next_source.settings_path)
            source = next_source
            on_path_switch(source)
            changed = True
            continue

        if next_source != source:
            source = next_source
            changed = True

        return source, changed


__all__ = [
    "build_env_controls_snapshot",
    "ControlModel",
    "converge_control_source",
    "normalize_override_path",
    "read_control_model",
]
