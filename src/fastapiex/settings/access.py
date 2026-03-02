from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SettingsRef:
    """Dynamic reference to a settings query."""

    target: str | type[object] | None
    field: str | None = None
    default: object = _NO_DEFAULT

    def get(self) -> Any:
        from .manager import get_settings_manager

        return get_settings_manager().resolve_settings(
            target=self.target,
            field=self.field,
            default=self.default,
            has_default=self.default is not _NO_DEFAULT,
        )

    @property
    def value(self) -> Any:
        return self.get()

    def __call__(self) -> Any:
        return self.get()


__all__ = [
    "GetSettings",
    "GetSettingsMap",
    "SettingsRef",
]
