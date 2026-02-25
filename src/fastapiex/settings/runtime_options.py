from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

ReloadMode = Literal["off", "on_change", "always"]


@dataclass(frozen=True)
class RuntimeOptions:
    case_sensitive: bool
    reload_mode: ReloadMode


def _parse_bool(raw: str | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def parse_case_sensitive_mode(raw: object | None, *, default: bool = False) -> bool:
    requested: bool | None
    if raw is None:
        requested = None
    elif isinstance(raw, bool):
        requested = raw
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        requested = bool(raw)
    else:
        requested = _parse_bool(str(raw), default=default)

    mode = requested if requested is not None else default
    if os.name == "nt" and mode:
        logger.warning("CASE_SENSITIVE=true is ignored on Windows; falling back to case-insensitive mode")
        return False
    return mode


def parse_reload_mode(raw: object | None, *, default: ReloadMode = "off") -> ReloadMode:
    if isinstance(raw, bool):
        raw_mode = "on_change" if raw else "off"
    elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
        raw_mode = "on_change" if raw else "off"
    elif raw is None:
        raw_mode = None
    else:
        raw_mode = str(raw).strip().lower()

    if raw_mode is None:
        return default

    if raw_mode in {"always"}:
        return "always"
    if raw_mode in {"on_change", "on-change", "onchange", "true", "1", "yes"}:
        return "on_change"
    if raw_mode in {"off", "false", "0", "no"}:
        return "off"

    logger.warning("invalid settings reload mode %r; falling back to %r", raw_mode, default)
    return default
