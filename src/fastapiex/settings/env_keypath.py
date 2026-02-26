from __future__ import annotations

import logging
from typing import Any

from .constants import ENV_KEY_SEPARATOR
from .control_model import CONTROL_ENV_PREFIX
from .key_policy import startswith_prefix

logger = logging.getLogger(__name__)

_INTERNAL_ENV_RESERVED_PREFIX = CONTROL_ENV_PREFIX


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
        if not startswith_prefix(env_key, prefix, case_sensitive=case_sensitive):
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

    if reserved:
        return [part.lower() for part in raw_parts]
    if case_sensitive:
        return raw_parts
    return [part.lower() for part in raw_parts]
