from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .exceptions import SettingsResolveError
from .path_lookup import resolve_lookup_path, section_matches_target_type
from .registry import SettingsSection
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
    sections: list[SettingsSection],
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
    sections: list[SettingsSection],
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
    # Type-target injection should resolve declared sections exactly.
    return resolve_lookup_path(settings, section.path_text, case_sensitive=True)


def resolve_type_target(
    *,
    target_type: type[object],
    sections: list[SettingsSection],
) -> SettingsSection:
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
