from __future__ import annotations

import logging
import os
from typing import TypeAlias

from pydantic import ConfigDict, Field, field_validator

from .constants import (
    DEFAULT_CASE_SENSITIVE,
    DEFAULT_ENV_PREFIX,
    DEFAULT_RELOAD_MODE,
    ENV_KEY_SEPARATOR,
    FALSE_TEXT_VALUES,
    RELOAD_MODE_ALWAYS_TOKENS,
    RELOAD_MODE_OFF_TOKENS,
    RELOAD_MODE_ON_CHANGE_TOKENS,
    TRUE_TEXT_VALUES,
)
from .core_settings import CoreSettings
from .specs import SectionSpec
from .types import ReloadMode

logger = logging.getLogger(__name__)


def _normalize_optional_str(raw: object | None) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _parse_bool(raw: object | None, *, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)

    value = str(raw).strip().lower()
    if value in TRUE_TEXT_VALUES:
        return True
    if value in FALSE_TEXT_VALUES:
        return False
    return default


def _parse_case_sensitive_mode(raw: object | None, *, default: bool = DEFAULT_CASE_SENSITIVE) -> bool:
    mode = _parse_bool(raw, default=default)
    if os.name == "nt" and mode:
        logger.warning("CASE_SENSITIVE=true is ignored on Windows; falling back to case-insensitive mode")
        return False
    return mode


def _parse_reload_mode(raw: object | None, *, default: ReloadMode = DEFAULT_RELOAD_MODE) -> ReloadMode:
    if isinstance(raw, bool):
        return "on_change" if raw else "off"
    if isinstance(raw, (int, float)):
        return "on_change" if raw else "off"

    raw_mode = None if raw is None else str(raw).strip().lower()
    if raw_mode is None:
        return default
    if raw_mode in RELOAD_MODE_ALWAYS_TOKENS:
        return "always"
    if raw_mode in RELOAD_MODE_ON_CHANGE_TOKENS:
        return "on_change"
    if raw_mode in RELOAD_MODE_OFF_TOKENS:
        return "off"

    logger.warning("invalid settings reload mode %r; falling back to %r", raw_mode, default)
    return default


class SettingsControls(CoreSettings):
    model_config = ConfigDict(extra="ignore")
    __section__ = "settings"

    path: str | None = None
    env_prefix: str = DEFAULT_ENV_PREFIX
    case_sensitive: bool = DEFAULT_CASE_SENSITIVE
    reload: ReloadMode = DEFAULT_RELOAD_MODE

    @field_validator("path", mode="before")
    @classmethod
    def _validate_path(cls, value: object | None) -> str | None:
        return _normalize_optional_str(value)

    @field_validator("env_prefix", mode="before")
    @classmethod
    def _validate_env_prefix(cls, value: object | None) -> str:
        if value is None:
            return DEFAULT_ENV_PREFIX
        text = str(value).strip()
        return text or DEFAULT_ENV_PREFIX

    @field_validator("case_sensitive", mode="before")
    @classmethod
    def _validate_case_sensitive(cls, value: object | None) -> bool:
        return _parse_case_sensitive_mode(value)

    @field_validator("reload", mode="before")
    @classmethod
    def _validate_reload_mode(cls, value: object | None) -> ReloadMode:
        return _parse_reload_mode(value)


class Fastapiex(CoreSettings):
    model_config = ConfigDict(extra="ignore")

    settings: SettingsControls = Field(default_factory=SettingsControls)
    base_dir: str | None = None

    @field_validator("base_dir", mode="before")
    @classmethod
    def _validate_base_dir(cls, value: object | None) -> str | None:
        return _normalize_optional_str(value)


ControlModel: TypeAlias = Fastapiex

CONTROL_SPEC: SectionSpec = ControlModel.section_spec()
CONTROL_ROOT = CONTROL_SPEC.root
CONTROL_ENV_PREFIX = f"{ControlModel.env_key(separator=ENV_KEY_SEPARATOR)}{ENV_KEY_SEPARATOR}"
SETTINGS_ENV_PREFIX_ENV_KEY = ControlModel.nested_env_key(
    SettingsControls,
    "env_prefix",
    separator=ENV_KEY_SEPARATOR,
)
SETTINGS_PATH_ENV_KEY = ControlModel.nested_env_key(
    SettingsControls,
    "path",
    separator=ENV_KEY_SEPARATOR,
)


def is_control_root(segment: str) -> bool:
    return segment.casefold() == CONTROL_ROOT.casefold()


__all__ = [
    "CONTROL_ENV_PREFIX",
    "CONTROL_ROOT",
    "CONTROL_SPEC",
    "ControlModel",
    "Fastapiex",
    "SETTINGS_PATH_ENV_KEY",
    "SETTINGS_ENV_PREFIX_ENV_KEY",
    "SettingsControls",
    "is_control_root",
]
