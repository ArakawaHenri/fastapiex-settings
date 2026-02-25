from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_NO_DEFAULT = object()


def GetSettings(
    target: str | type[object] | None = None,
    *,
    field: str | None = None,
    default: object = _NO_DEFAULT,
) -> Any:
    from .manager import get_settings_manager

    return get_settings_manager().resolve_settings(
        target=target,
        field=field,
        default=default,
        has_default=default is not _NO_DEFAULT,
    )


def GetSettingsMap(
    target: str | type[object] | None = None,
    *,
    default: object = _NO_DEFAULT,
) -> Mapping[str, Any]:
    from .manager import get_settings_manager

    return get_settings_manager().resolve_settings_map(
        target=target,
        default=default,
        has_default=default is not _NO_DEFAULT,
    )


__all__ = [
    "GetSettings",
    "GetSettingsMap",
    "_NO_DEFAULT",
]
