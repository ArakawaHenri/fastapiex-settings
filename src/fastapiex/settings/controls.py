from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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

def build_env_controls_snapshot() -> Mapping[Any, Any]:
    return load_env_overrides(prefix="", case_sensitive=False)


__all__ = [
    "build_env_controls_snapshot",
    "ControlModel",
    "read_control_model",
]
