from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol, get_args, get_origin

from pydantic import BaseModel

from .constants import ENV_KEY_SEPARATOR
from .control_contract import CONTROL_ENV_PREFIX, CONTROL_ROOT, CONTROL_SPEC
from .live_config import SourceEntry
from .loader import key_to_parts, parse_env_value

WinnerMeta = tuple[int, int, Any]
_ProjectedEntry = tuple[tuple[str, ...], Any]
_Projector = Callable[[SourceEntry], _ProjectedEntry | None]
_PathResolver = Callable[[str], tuple[str, ...] | None]


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
    projected: dict[str, Any] = {}
    _merge_casefold_mapping(projected, raw, deepcopy_values=True)
    return projected


def _merge_casefold_mapping(
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
            _merge_casefold_mapping(nested, value, deepcopy_values=deepcopy_values)
            continue
        target[canonical_key] = deepcopy(value) if deepcopy_values else value


class _ProjectionPolicy(Protocol):
    def project(self, entry: SourceEntry) -> _ProjectedEntry | None: ...


@dataclass(frozen=True)
class _ControlProjectionPolicy:
    control_path: tuple[str, ...] = CONTROL_SPEC.path
    control_env_prefix: str = CONTROL_ENV_PREFIX

    def project(self, entry: SourceEntry) -> _ProjectedEntry | None:
        if not entry.include_in_control:
            return None
        if entry.kind == "mapping":
            return self._project_yaml(entry)
        return _project_env_entry(entry, key_to_path=self._control_env_key_to_path)

    def _project_yaml(self, entry: SourceEntry) -> _ProjectedEntry | None:
        if not entry.path:
            return None
        if len(entry.path) < len(self.control_path):
            return None
        entry_prefix = entry.path[: len(self.control_path)]
        if any(
            left.casefold() != right.casefold()
            for left, right in zip(entry_prefix, self.control_path, strict=False)
        ):
            return None
        canonical_path = tuple(segment.casefold() for segment in entry.path)
        return (canonical_path, entry.value)

    def _control_env_key_to_path(self, env_key: str) -> tuple[str, ...] | None:
        if not env_key.upper().startswith(self.control_env_prefix):
            return None
        raw_parts = env_key.split(ENV_KEY_SEPARATOR)
        if any(not part for part in raw_parts):
            return None
        return tuple(part.casefold() for part in raw_parts)


@dataclass(frozen=True)
class _SettingsProjectionPolicy:
    env_prefix: str
    case_sensitive: bool

    def project(self, entry: SourceEntry) -> _ProjectedEntry | None:
        if entry.kind == "mapping":
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
    return build_snapshot_from_winners(winners)


def _collect_projected_winners(
    entries: Iterable[SourceEntry],
    *,
    projector: _Projector,
) -> dict[tuple[str, ...], WinnerMeta]:
    winners: dict[tuple[str, ...], WinnerMeta] = {}
    for entry in entries:
        projected = projector(entry)
        if projected is None:
            continue

        path, value = projected
        meta = (entry.rev, entry.priority)
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


def project_snapshot_for_validation(
    raw: Mapping[str, Any],
    *,
    root_model: type[BaseModel],
    case_sensitive: bool,
) -> dict[str, Any]:
    return _project_mapping_to_model(
        raw,
        root_model=root_model,
        case_sensitive=case_sensitive,
        allow_control_root=True,
    )


def _project_mapping_to_model(
    raw: Mapping[Any, Any],
    *,
    root_model: type[BaseModel],
    case_sensitive: bool,
    allow_control_root: bool = False,
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    fields = root_model.model_fields

    for key, value in raw.items():
        target_key, projected_value = _project_entry_to_model(
            fields,
            key=key,
            value=value,
            case_sensitive=case_sensitive,
            allow_control_root=allow_control_root,
        )
        assign_projected_value(projected, target_key, projected_value)

    return projected


def _project_entry_to_model(
    fields: Mapping[str, Any],
    *,
    key: Any,
    value: Any,
    case_sensitive: bool,
    allow_control_root: bool,
) -> tuple[str, Any]:
    input_key = key if isinstance(key, str) else str(key)
    control_entry = _project_control_root_entry(
        fields,
        input_key,
        value,
        allow_control_root=allow_control_root,
    )
    if control_entry is not None:
        return control_entry

    field_name = _resolve_field_name(fields, input_key, case_sensitive=case_sensitive)
    if field_name is None:
        return input_key, deepcopy(value)

    return field_name, _project_model_field_value(
        annotation=fields[field_name].annotation,
        value=value,
        case_sensitive=case_sensitive,
    )


def _project_model_field_value(
    *,
    annotation: Any,
    value: Any,
    case_sensitive: bool,
) -> Any:
    object_model = _extract_model_type(annotation)
    if object_model is not None and isinstance(value, Mapping):
        return _project_mapping_to_model(
            value,
            root_model=object_model,
            case_sensitive=case_sensitive,
            allow_control_root=False,
        )

    map_value_model = _extract_mapping_value_model(annotation)
    if map_value_model is not None and isinstance(value, Mapping):
        return _project_mapping_values_to_model(
            value,
            value_model=map_value_model,
            case_sensitive=case_sensitive,
        )

    return deepcopy(value)


def _project_mapping_values_to_model(
    raw: Mapping[Any, Any],
    *,
    value_model: type[BaseModel],
    case_sensitive: bool,
) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, value in raw.items():
        item_key = key if isinstance(key, str) else str(key)
        if isinstance(value, Mapping):
            projected[item_key] = _project_mapping_to_model(
                value,
                root_model=value_model,
                case_sensitive=case_sensitive,
                allow_control_root=False,
            )
            continue
        projected[item_key] = deepcopy(value)
    return projected


def _project_control_root_entry(
    fields: Mapping[str, Any],
    input_key: str,
    value: Any,
    *,
    allow_control_root: bool,
) -> tuple[str, Any] | None:
    if not allow_control_root:
        return None

    control_field = _resolve_control_root_field_name(fields, input_key)
    if control_field is None:
        return None
    if not isinstance(value, Mapping):
        return (control_field, deepcopy(value))
    return (control_field, normalize_control_mapping(value))


def _resolve_control_root_field_name(
    fields: Mapping[str, Any],
    input_key: str,
) -> str | None:
    if input_key.casefold() != CONTROL_ROOT.casefold():
        return None
    matches = [field_name for field_name in fields if field_name.casefold() == CONTROL_ROOT.casefold()]
    if len(matches) != 1:
        return None
    return matches[0]


def _resolve_field_name(
    fields: Mapping[str, Any],
    input_key: str,
    *,
    case_sensitive: bool,
) -> str | None:
    if input_key in fields:
        return input_key

    if case_sensitive:
        return None

    folded = input_key.casefold()
    matches = [field_name for field_name in fields if field_name.casefold() == folded]
    if len(matches) != 1:
        return None

    return matches[0]


def _extract_model_type(annotation: Any) -> type[BaseModel] | None:
    candidate = _unwrap_optional(annotation)
    if isinstance(candidate, type) and issubclass(candidate, BaseModel):
        return candidate
    return None


def _extract_mapping_value_model(annotation: Any) -> type[BaseModel] | None:
    candidate = _unwrap_optional(annotation)
    origin = get_origin(candidate)
    if origin not in {dict, Mapping}:
        return None
    args = get_args(candidate)
    if len(args) != 2:
        return None
    value_type = _unwrap_optional(args[1])
    if isinstance(value_type, type) and issubclass(value_type, BaseModel):
        return value_type
    return None


def _unwrap_optional(annotation: Any) -> Any:
    args = get_args(annotation)
    if not args:
        return annotation
    non_none = [arg for arg in args if arg is not type(None)]
    if len(non_none) == 1 and len(non_none) != len(args):
        return non_none[0]
    return annotation
