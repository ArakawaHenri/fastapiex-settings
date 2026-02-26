from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .casefold_mapping import merge_casefold_mapping
from .control_model import CONTROL_ROOT, ControlModel


def read_control_model(snapshot: Mapping[Any, Any]) -> ControlModel:
    normalized = normalize_control_snapshot(snapshot)
    return ControlModel.model_validate(normalized)


def normalize_control_snapshot(snapshot: Mapping[Any, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in snapshot.items():
        if not isinstance(key, str):
            continue
        if key.casefold() != CONTROL_ROOT.casefold():
            continue
        if not isinstance(value, Mapping):
            continue
        merge_casefold_mapping(merged, value, deepcopy_values=False)
    return merged
