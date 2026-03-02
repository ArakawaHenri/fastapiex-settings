from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .control_contract import is_control_root
from .exceptions import SettingsResolveError
from .specs import SectionSpec
from .types import ResolveAPI


@dataclass(frozen=True)
class ResolveRequest:
    api: ResolveAPI
    target: str | type[object] | None
    field: str | None
    default: object
    has_default: bool

    def cache_key(self) -> str:
        target_repr: str
        if isinstance(self.target, str):
            target_repr = f"str:{self.target}"
        elif isinstance(self.target, type):
            target_repr = f"type:{self.target.__module__}.{self.target.__qualname__}"
        else:
            target_repr = "none"
        return f"{self.api}|{target_repr}|field={self.field}"


class QueryMiss(Exception):
    pass


def evaluate_request(
    *,
    request: ResolveRequest,
    settings: BaseModel,
    sections: list[SectionSpec],
    case_sensitive: bool,
) -> Any:
    value = resolve_target_value(
        target=request.target,
        settings=settings,
        sections=sections,
        case_sensitive=case_sensitive,
    )

    if request.field is not None:
        field = request.field.strip()
        if not field:
            raise QueryMiss("field is empty")
        value = resolve_lookup_path(value, field, case_sensitive=case_sensitive)

    if request.api == "map" and not isinstance(value, Mapping):
        raise QueryMiss("resolved value is not a mapping")

    return value


def resolve_target_value(
    *,
    target: str | type[object] | None,
    settings: BaseModel,
    sections: list[SectionSpec],
    case_sensitive: bool,
) -> Any:
    if target is None:
        raise QueryMiss("target is not provided")

    if isinstance(target, str):
        target_text = target.strip()
        if not target_text:
            raise QueryMiss("target is empty")
        return resolve_lookup_path(settings, target_text, case_sensitive=case_sensitive)

    if not isinstance(target, type):
        raise QueryMiss("target must be a string path or class")

    section = resolve_type_target(target_type=target, sections=sections)
    return resolve_lookup_path(settings, section.path_text, case_sensitive=True)


def resolve_type_target(
    *,
    target_type: type[object],
    sections: list[SectionSpec],
) -> SectionSpec:
    target_name = f"{target_type.__module__}.{target_type.__qualname__}"
    candidates = [section for section in sections if section_matches_target_type(section, target_type)]

    if not candidates:
        raise QueryMiss(f"target type '{target_name}' did not match any declared section")

    if len(candidates) > 1:
        matched_paths = ", ".join(sorted(section.path_text for section in candidates))
        raise QueryMiss(f"target type '{target_name}' matched multiple sections: {matched_paths}")

    return candidates[0]


def resolve_default(request: ResolveRequest) -> Any:
    if request.api == "map" and not isinstance(request.default, Mapping):
        raise SettingsResolveError("default value for SettingsMap must be a mapping")
    return request.default


def resolve_lookup_path(root: object, path: str, *, case_sensitive: bool) -> Any:
    segments = _split_lookup_path(path)
    reserved_namespace = bool(segments) and is_control_root(segments[0])
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


def section_matches_target_type(section: SectionSpec, target_type: type[object]) -> bool:
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
