from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any, get_args, get_origin

from pydantic import BaseModel

from .control_model import CONTROL_ROOT


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
        _assign_projected_value(projected, target_key, projected_value)

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
    return (control_field, _project_control_mapping(value))


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


def _project_control_mapping(raw: Mapping[Any, Any]) -> dict[str, Any]:
    projected: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        canonical_key = key.casefold()
        if isinstance(value, Mapping):
            nested = _project_control_mapping(value)
            existing = projected.get(canonical_key)
            if isinstance(existing, dict):
                _merge_nested_mapping(existing, nested)
            else:
                projected[canonical_key] = nested
            continue
        projected[canonical_key] = deepcopy(value)
    return projected


def _merge_nested_mapping(target: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    for key, value in incoming.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _merge_nested_mapping(existing, value)
            continue
        target[key] = deepcopy(value)


def _assign_projected_value(target: dict[str, Any], key: str, value: Any) -> None:
    existing = target.get(key)
    if isinstance(existing, dict) and isinstance(value, Mapping):
        _merge_nested_mapping(existing, value)
        return
    target[key] = deepcopy(value)


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
