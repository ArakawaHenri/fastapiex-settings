from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from .constants import (
    DEFAULT_ENV_PREFIX,
    DOTENV_EXPORT_PREFIX,
    DOTENV_FILENAME,
    ENV_KEY_SEPARATOR,
    FALSE_TEXT_VALUES,
    NULL_TEXT_VALUES,
    TRUE_TEXT_VALUES,
)
from .control_contract import CONTROL_ENV_PREFIX, SETTINGS_ENV_PREFIX_ENV_KEY

logger = logging.getLogger(__name__)
_INTERNAL_ENV_RESERVED_PREFIX = CONTROL_ENV_PREFIX
_INT_RE = re.compile(r"^[+-]?\d(?:_?\d)*$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:\d(?:_?\d)*)[eE][+-]?\d+$|"
    r"^[+-]?(?:(?:\d(?:_?\d)*)?\.\d(?:_?\d)*|\d(?:_?\d)*\.)(?:[eE][+-]?\d+)?$"
)


def read_env_prefix_override() -> str | None:
    exact = os.getenv(SETTINGS_ENV_PREFIX_ENV_KEY)
    if exact is not None:
        stripped = exact.strip()
        if stripped:
            return stripped

    target = SETTINGS_ENV_PREFIX_ENV_KEY.upper()
    for env_key, value in os.environ.items():
        if env_key.upper() != target:
            continue
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def resolve_env_prefix(prefix: str | None = None) -> str:
    raw = prefix if prefix is not None else read_env_prefix_override()
    if raw is None:
        return DEFAULT_ENV_PREFIX

    value = raw.strip()
    if not value:
        return ""

    if value.upper().startswith(_INTERNAL_ENV_RESERVED_PREFIX):
        raise ValueError(
            f"{SETTINGS_ENV_PREFIX_ENV_KEY} cannot start with reserved prefix '{CONTROL_ENV_PREFIX}'"
        )

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


def load_env_snapshot_raw() -> dict[str, str]:
    return dict(os.environ)


def parse_env_snapshot(
    raw_env: Mapping[str, str],
    *,
    prefix: str = DEFAULT_ENV_PREFIX,
    case_sensitive: bool,
) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for env_key, env_val in raw_env.items():
        parts = key_to_parts(env_key, prefix=prefix, case_sensitive=case_sensitive)
        if parts is None:
            continue
        set_nested_mapping(overrides, parts, parse_env_value(env_val))
    return overrides


def load_env_overrides(*, prefix: str = DEFAULT_ENV_PREFIX, case_sensitive: bool) -> dict[str, Any]:
    return parse_env_snapshot(
        load_env_snapshot_raw(),
        prefix=prefix,
        case_sensitive=case_sensitive,
    )


def find_dotenv_path(start_dir: Path) -> Path | None:
    candidate = start_dir.resolve() / DOTENV_FILENAME
    return candidate if candidate.is_file() else None


def load_dotenv_snapshot_raw(*, start_dir: Path) -> dict[str, str]:
    dotenv_path = find_dotenv_path(start_dir)
    if dotenv_path is None:
        return {}

    pairs: dict[str, str] = {}
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(DOTENV_EXPORT_PREFIX):
            line = line[len(DOTENV_EXPORT_PREFIX):].lstrip()
        if "=" not in line:
            continue

        key, raw_value = line.split("=", 1)
        env_key = key.strip()
        if not env_key:
            continue
        pairs[env_key] = parse_dotenv_value(raw_value)
    return pairs


def load_dotenv_overrides(*, start_dir: Path, prefix: str = DEFAULT_ENV_PREFIX, case_sensitive: bool) -> dict[str, Any]:
    return parse_env_snapshot(
        load_dotenv_snapshot_raw(start_dir=start_dir),
        prefix=prefix,
        case_sensitive=case_sensitive,
    )


def set_nested_mapping(target: dict[str, Any], parts: list[str], value: Any) -> None:
    cursor = target
    for part in parts[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[parts[-1]] = value


def key_to_parts(env_key: str, *, prefix: str, case_sensitive: bool) -> list[str] | None:
    reserved = env_key.upper().startswith(_INTERNAL_ENV_RESERVED_PREFIX)

    if reserved:
        key_path = env_key
    elif prefix:
        if not _startswith_prefix(env_key, prefix, case_sensitive=case_sensitive):
            return None
        key_path = env_key[len(prefix):]
        if key_path.upper().startswith(_INTERNAL_ENV_RESERVED_PREFIX):
            logger.warning(
                "ignoring env key '%s': FASTAPIEX__* keys must not carry "
                "the business prefix '%s'; use '%s' directly",
                env_key,
                prefix,
                key_path,
            )
            return None
    else:
        key_path = env_key

    if not key_path:
        return None

    raw_parts = key_path.split(ENV_KEY_SEPARATOR)
    if any(not part for part in raw_parts):
        return None

    if reserved or not case_sensitive:
        return [part.lower() for part in raw_parts]
    return raw_parts


def parse_env_value(raw: str) -> Any:
    stripped = raw.strip()
    if stripped == "":
        return ""

    value = strip_matching_quotes(stripped)
    lowered = value.lower()
    if lowered in TRUE_TEXT_VALUES:
        return True
    if lowered in FALSE_TEXT_VALUES:
        return False
    if lowered in NULL_TEXT_VALUES:
        return None

    if (value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    try:
        normalized = value.replace("_", "")
        if _INT_RE.match(value):
            return int(normalized)
        if _FLOAT_RE.match(value):
            return float(normalized)
    except ValueError:
        return value
    return value


def parse_dotenv_value(raw: str) -> str:
    value = strip_inline_comment(raw.strip())
    return strip_matching_quotes(value)


def strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def strip_inline_comment(raw: str) -> str:
    quote: str | None = None
    escaped = False
    for idx, ch in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in {"'", '"'}:
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            continue
        if ch == "#" and quote is None:
            return raw[:idx].rstrip()
    return raw.rstrip()


def _startswith_prefix(value: str, prefix: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return value.startswith(prefix)
    return value.casefold().startswith(prefix.casefold())
