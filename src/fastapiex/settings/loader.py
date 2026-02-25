from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

DEFAULT_ENV_PREFIX = ""
ENV_PREFIX_ENV_KEYS = ("FASTAPIEX__SETTINGS__ENV_PREFIX",)
_INTERNAL_ENV_RESERVED_PREFIX = "FASTAPIEX__"
_INT_RE = re.compile(r"^[+-]?\d(?:_?\d)*$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:\d(?:_?\d)*)[eE][+-]?\d+$|"
    r"^[+-]?(?:(?:\d(?:_?\d)*)?\.\d(?:_?\d)*|\d(?:_?\d)*\.)(?:[eE][+-]?\d+)?$"
)


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


def _parse_env_value(raw: str) -> Any:
    stripped = raw.strip()
    if stripped == "":
        return ""

    value = _strip_matching_quotes(stripped)
    lowered = value.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none"}:
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


def _set_nested(target: dict[str, Any], parts: list[str], value: Any) -> None:
    cursor = target
    for part in parts[:-1]:
        existing = cursor.get(part)
        if not isinstance(existing, dict):
            existing = {}
            cursor[part] = existing
        cursor = existing
    cursor[parts[-1]] = value


def _key_to_parts(env_key: str, *, prefix: str, case_sensitive: bool) -> list[str] | None:
    reserved = env_key.upper().startswith(_INTERNAL_ENV_RESERVED_PREFIX)

    if reserved:
        key_path = env_key
    elif prefix:
        if not env_key.startswith(prefix):
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

    raw_parts = key_path.split("__")
    if any(not part for part in raw_parts):
        return None

    if reserved:
        parts = [part.lower() for part in raw_parts]
    else:
        parts = raw_parts if case_sensitive else [part.lower() for part in raw_parts]
    return parts


def load_env_overrides(*, prefix: str = DEFAULT_ENV_PREFIX, case_sensitive: bool) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for env_key, env_val in os.environ.items():
        parts = _key_to_parts(env_key, prefix=prefix, case_sensitive=case_sensitive)
        if parts is None:
            continue
        _set_nested(overrides, parts, _parse_env_value(env_val))
    return overrides


def find_dotenv_path(start_dir: Path) -> Path | None:
    candidate = start_dir.resolve() / ".env"
    return candidate if candidate.is_file() else None


def _strip_inline_comment(raw: str) -> str:
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


def _parse_dotenv_value(raw: str) -> str:
    value = _strip_inline_comment(raw.strip())
    return _strip_matching_quotes(value)


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


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
        parts = _key_to_parts(env_key, prefix=prefix, case_sensitive=case_sensitive)
        if parts is None:
            continue

        parsed = _parse_env_value(_parse_dotenv_value(raw_value))
        _set_nested(overrides, parts, parsed)
    return overrides
