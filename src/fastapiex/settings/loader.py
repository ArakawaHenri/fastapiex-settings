from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .control_model import CONTROL_ENV_PREFIX, DEFAULT_ENV_PREFIX, ENV_PREFIX_ENV_KEYS
from .env_keypath import key_to_parts, set_nested_mapping
from .env_value_parser import parse_dotenv_value, parse_env_value

_INTERNAL_ENV_RESERVED_PREFIX = CONTROL_ENV_PREFIX


def _read_env_override(keys: tuple[str, ...]) -> str | None:
    normalized = {key.upper() for key in keys}
    for key in keys:
        value = os.getenv(key)
        if value is None:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    for env_key, value in os.environ.items():
        if env_key.upper() not in normalized:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def read_env_prefix_override() -> str | None:
    return _read_env_override(ENV_PREFIX_ENV_KEYS)


def resolve_env_prefix(prefix: str | None = None) -> str:
    raw = prefix if prefix is not None else read_env_prefix_override()
    if raw is None:
        return DEFAULT_ENV_PREFIX

    value = raw.strip()
    if not value:
        return ""

    if value.upper().startswith(_INTERNAL_ENV_RESERVED_PREFIX):
        raise ValueError("FASTAPIEX__SETTINGS__ENV_PREFIX cannot start with reserved prefix 'FASTAPIEX__'")

    return value


def load_yaml_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError(f"settings file must contain a mapping at top-level: {path}")
    return raw


def load_env_overrides(*, prefix: str = DEFAULT_ENV_PREFIX, case_sensitive: bool) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for env_key, env_val in os.environ.items():
        parts = key_to_parts(env_key, prefix=prefix, case_sensitive=case_sensitive)
        if parts is None:
            continue
        set_nested_mapping(overrides, parts, parse_env_value(env_val))
    return overrides


def find_dotenv_path(start_dir: Path) -> Path | None:
    candidate = start_dir.resolve() / ".env"
    return candidate if candidate.is_file() else None


def load_dotenv_overrides(*, start_dir: Path, prefix: str = DEFAULT_ENV_PREFIX, case_sensitive: bool) -> dict[str, Any]:
    dotenv_path = find_dotenv_path(start_dir)
    if dotenv_path is None:
        return {}

    overrides: dict[str, Any] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        env_key = key.strip()
        parts = key_to_parts(env_key, prefix=prefix, case_sensitive=case_sensitive)
        if parts is None:
            continue

        parsed = parse_env_value(parse_dotenv_value(raw_value))
        set_nested_mapping(overrides, parts, parsed)
    return overrides
