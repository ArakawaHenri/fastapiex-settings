from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from .control_contract import SETTINGS_PATH_ENV_KEY
from .manager import get_settings_manager


def init_settings(
    *,
    settings_path: str | Path | None = None,
) -> BaseModel:
    if settings_path is not None:
        os.environ[SETTINGS_PATH_ENV_KEY] = os.fspath(settings_path)
    return get_settings_manager().init()


def reload_settings(*, reason: str = "manual") -> BaseModel:
    return get_settings_manager().reload(reason=reason)
