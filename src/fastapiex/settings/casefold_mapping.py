from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def merge_casefold_mapping(
    target: dict[str, Any],
    incoming: Mapping[Any, Any],
    *,
    deepcopy_values: bool,
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
            merge_casefold_mapping(nested, value, deepcopy_values=deepcopy_values)
            continue
        target[canonical_key] = deepcopy(value) if deepcopy_values else value


def build_casefold_mapping(raw: Mapping[Any, Any], *, deepcopy_values: bool) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    merge_casefold_mapping(projected, raw, deepcopy_values=deepcopy_values)
    return projected
