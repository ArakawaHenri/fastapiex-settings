from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .accessors import _NO_DEFAULT
from .manager import get_settings_manager


@dataclass(frozen=True)
class SettingsRef:
    """Dynamic reference to a settings query."""

    target: str | type[object] | None
    field: str | None = None
    default: object = _NO_DEFAULT

    def get(self) -> Any:
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
