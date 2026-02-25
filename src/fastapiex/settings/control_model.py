from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .runtime_options import ReloadMode

CONTROL_ROOT = "fastapiex"
CONTROL_ENV_PREFIX = "FASTAPIEX__"

SETTINGS_PATH_KEYS = (CONTROL_ROOT, "settings", "path")
BASE_DIR_KEYS = (CONTROL_ROOT, "base_dir")
ENV_PREFIX_KEYS = (CONTROL_ROOT, "settings", "env_prefix")
CASE_SENSITIVE_KEYS = (CONTROL_ROOT, "settings", "case_sensitive")
RELOAD_KEYS = (CONTROL_ROOT, "settings", "reload")
ENV_PREFIX_ENV_KEYS = ("FASTAPIEX__SETTINGS__ENV_PREFIX",)

DEFAULT_ENV_PREFIX = ""
DEFAULT_CASE_SENSITIVE = False
DEFAULT_RELOAD_MODE: ReloadMode = "off"


@dataclass(frozen=True)
class ControlModel:
    settings_path: str | None = None
    base_dir: str | None = None
    env_prefix: str = DEFAULT_ENV_PREFIX
    case_sensitive: Any = DEFAULT_CASE_SENSITIVE
    reload_mode: Any = DEFAULT_RELOAD_MODE
