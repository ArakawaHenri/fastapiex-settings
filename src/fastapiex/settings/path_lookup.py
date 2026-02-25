from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from .registry import SettingsSection


def resolve_lookup_path(root: object, path: str, *, case_sensitive: bool) -> Any:
    segments = _split_lookup_path(path)
    reserved_namespace = bool(segments) and segments[0].casefold() == "fastapiex"
    current: Any = root
    for segment in segments:
        effective_case_sensitive = case_sensitive and not reserved_namespace
        if isinstance(current, Mapping):
            current = _resolve_mapping_value(
                current,
                segment,
                case_sensitive=effective_case_sensitive,
            )
            continue

        if isinstance(current, BaseModel):
            current = _resolve_model_field(
                current,
                segment,
                case_sensitive=effective_case_sensitive,
            )
            continue

        raise KeyError(path)

    return current


def section_matches_target_type(section: SettingsSection, target_type: type[object]) -> bool:
    candidate_types: tuple[type[object], ...]
    if section.kind == "map":
        candidate_types = (section.model, dict)
    else:
        candidate_types = (section.model,)
    return any(_issubclass_safe(candidate, target_type) for candidate in candidate_types)


def _split_lookup_path(path: str) -> tuple[str, ...]:
    parts = [part.strip() for part in path.split(".")]
    if not parts or any(not part for part in parts):
        raise KeyError(path)
    return tuple(parts)


def _issubclass_safe(candidate: type[object], base: type[object]) -> bool:
    try:
        return issubclass(candidate, base)
    except TypeError:
        return False


def _resolve_mapping_value(mapping: Mapping[Any, Any], segment: str, *, case_sensitive: bool) -> Any:
    if case_sensitive:
        if segment not in mapping:
            raise KeyError(segment)
        return mapping[segment]

    folded_segment = segment.casefold()
    folded_matches: list[Any] = []

    for key in mapping.keys():
        if isinstance(key, str) and key.casefold() == folded_segment:
            folded_matches.append(key)

    if len(folded_matches) == 1:
        return mapping[folded_matches[0]]

    raise KeyError(segment)


def _resolve_model_field(model: BaseModel, segment: str, *, case_sensitive: bool) -> Any:
    fields = model.__class__.model_fields

    if case_sensitive:
        if segment not in fields:
            raise KeyError(segment)
        return getattr(model, segment)

    folded_segment = segment.casefold()
    matches = [name for name in fields if name.casefold() == folded_segment]
    if len(matches) != 1:
        raise KeyError(segment)
    return getattr(model, matches[0])


__all__ = [
    "resolve_lookup_path",
    "section_matches_target_type",
]
