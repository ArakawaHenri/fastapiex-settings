from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .control_model import (
    BASE_DIR_KEYS,
    CASE_SENSITIVE_KEYS,
    CONTROL_ROOT,
    DEFAULT_CASE_SENSITIVE,
    DEFAULT_ENV_PREFIX,
    DEFAULT_RELOAD_MODE,
    ENV_PREFIX_KEYS,
    RELOAD_KEYS,
    SETTINGS_PATH_KEYS,
    ControlModel,
)
from .runtime_options import RuntimeOptions, parse_case_sensitive_mode, parse_reload_mode


def read_control_model(snapshot: Mapping[Any, Any]) -> ControlModel:
    normalized = normalize_control_snapshot(snapshot)
    env_prefix_raw = read_nested_value(normalized, ENV_PREFIX_KEYS)
    env_prefix = str(env_prefix_raw).strip() if env_prefix_raw is not None else DEFAULT_ENV_PREFIX
    if not env_prefix:
        env_prefix = DEFAULT_ENV_PREFIX

    return ControlModel(
        settings_path=_read_optional_str(normalized, SETTINGS_PATH_KEYS),
        base_dir=_read_optional_str(normalized, BASE_DIR_KEYS),
        env_prefix=env_prefix,
        case_sensitive=read_nested_value(normalized, CASE_SENSITIVE_KEYS),
        reload_mode=read_nested_value(normalized, RELOAD_KEYS),
    )


def runtime_options_from_snapshot(snapshot: Mapping[Any, Any]) -> RuntimeOptions:
    control = read_control_model(snapshot)
    return RuntimeOptions(
        case_sensitive=parse_case_sensitive_mode(control.case_sensitive, default=DEFAULT_CASE_SENSITIVE),
        reload_mode=parse_reload_mode(control.reload_mode, default=DEFAULT_RELOAD_MODE),
    )


def normalize_control_snapshot(snapshot: Mapping[Any, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in snapshot.items():
        if not isinstance(key, str):
            continue
        if key.casefold() != CONTROL_ROOT.casefold():
            continue
        if not isinstance(value, Mapping):
            continue
        _merge_casefold_mapping(merged, value)
    if not merged:
        return {}
    return {CONTROL_ROOT: merged}


def _merge_casefold_mapping(target: dict[str, Any], incoming: Mapping[Any, Any]) -> None:
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


def read_nested_value(mapping: Mapping[Any, Any], keys: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        matched = _find_mapping_key(current, key)
        if matched is None:
            return None
        current = current[matched]
    return current


def _find_mapping_key(mapping: Mapping[Any, Any], expected: str) -> Any:
    lowered = expected.lower()
    for key in mapping.keys():
        if isinstance(key, str) and key.lower() == lowered:
            return key
    return None


def _read_optional_str(snapshot: Mapping[Any, Any], keys: tuple[str, ...]) -> str | None:
    raw = read_nested_value(snapshot, keys)
    if not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None
