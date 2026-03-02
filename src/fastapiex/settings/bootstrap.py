from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from .manager import get_settings_manager


def init_settings(
    *,
    settings_path: str | Path | None = None,
    env_prefix: str | None = None,
) -> BaseModel:
    return get_settings_manager().init(
        settings_path=settings_path,
        env_prefix=env_prefix,
    )


def reload_settings(*, reason: str = "manual") -> BaseModel:
    return get_settings_manager().reload(reason=reason)
