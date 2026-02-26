from __future__ import annotations

import logging
import os
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .section_naming import resolve_section_name
from .section_path import split_dotted_path

DEFAULT_ENV_PREFIX = ""
DEFAULT_CASE_SENSITIVE = False
ReloadMode = Literal["off", "on_change", "always"]
DEFAULT_RELOAD_MODE: ReloadMode = "off"
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
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
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
        raw_mode = "on_change" if raw else "off"
    elif isinstance(raw, (int, float)):
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


class _SettingsControlModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

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


class Fastapiex(BaseModel):
    model_config = ConfigDict(extra="ignore")

    settings: _SettingsControlModel = Field(default_factory=_SettingsControlModel)
    base_dir: str | None = None

    @field_validator("base_dir", mode="before")
    @classmethod
    def _validate_base_dir(cls, value: object | None) -> str | None:
        return _normalize_optional_str(value)


ControlModel: TypeAlias = Fastapiex


def _resolve_control_root(model: type[BaseModel]) -> str:
    resolved = resolve_section_name(model, explicit=None)
    parts = split_dotted_path(resolved)
    if len(parts) != 1:
        raise ValueError(f"control root must be a single path segment, got {resolved!r}")
    return parts[0]


CONTROL_ROOT = _resolve_control_root(ControlModel)
CONTROL_ENV_PREFIX = f"{CONTROL_ROOT.upper()}__"
SETTINGS_ENV_PREFIX_ENV_KEY = f"{CONTROL_ENV_PREFIX}SETTINGS__ENV_PREFIX"
