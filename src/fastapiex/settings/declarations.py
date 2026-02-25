from __future__ import annotations

import sys
from collections.abc import Callable
from typing import ClassVar, TypeVar, overload

from pydantic import BaseModel

from .exceptions import SettingsRegistrationError
from .registry import SectionKind, get_settings_registry, to_snake_case

_ModelClassT = TypeVar("_ModelClassT", bound=type[BaseModel])


class BaseSettings(BaseModel):
    """Base class for settings declaration models."""

    __section__: ClassVar[str]


def _resolve_section_name(model: type[BaseModel], explicit: str | None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    declared = getattr(model, "__section__", None)
    if isinstance(declared, str) and declared.strip():
        return declared.strip()

    return to_snake_case(model.__name__)


def _module_identity(module_name: str) -> int:
    module = sys.modules.get(module_name)
    if module is None:
        return -1
    return id(module)


def _register_declared_model(
    cls: _ModelClassT,
    *,
    section: str | None,
    kind: SectionKind,
) -> _ModelClassT:
    if not issubclass(cls, BaseModel):
        raise SettingsRegistrationError("@Settings declarations require a BaseModel subclass")

    resolved_section = _resolve_section_name(cls, section)

    cls.__section__ = resolved_section  # type: ignore[attr-defined]
    cls.__fastapiex_settings_model__ = True  # type: ignore[attr-defined]
    cls.__fastapiex_settings_is_map__ = kind == "map"  # type: ignore[attr-defined]

    registry = get_settings_registry()
    registry.register_section(
        raw_path=resolved_section,
        cls=cls,
        kind=kind,
        owner_module=cls.__module__,
        owner_identity=_module_identity(cls.__module__),
    )
    return cls


def _decorate_settings(section: str | None, *, kind: SectionKind) -> Callable[[_ModelClassT], _ModelClassT]:
    def _decorator(cls: _ModelClassT) -> _ModelClassT:
        return _register_declared_model(cls, section=section, kind=kind)

    return _decorator


@overload
def Settings(model: _ModelClassT, /) -> _ModelClassT: ...


@overload
def Settings(path: str | None = None, /) -> Callable[[_ModelClassT], _ModelClassT]: ...


def Settings(
    model_or_path: _ModelClassT | str | None = None,
    /,
) -> _ModelClassT | Callable[[_ModelClassT], _ModelClassT]:
    """Object section declaration decorator."""

    if isinstance(model_or_path, type):
        if not issubclass(model_or_path, BaseModel):
            raise TypeError("@Settings can only decorate BaseModel subclasses")
        return _register_declared_model(model_or_path, section=None, kind="object")

    if model_or_path is not None and not isinstance(model_or_path, str):
        raise TypeError("@Settings expects a dotted path string, model class, or no argument")

    section = model_or_path
    return _decorate_settings(section, kind="object")


@overload
def SettingsMap(model: _ModelClassT, /) -> _ModelClassT: ...


@overload
def SettingsMap(path: str | None = None, /) -> Callable[[_ModelClassT], _ModelClassT]: ...


def SettingsMap(
    model_or_path: _ModelClassT | str | None = None,
    /,
) -> _ModelClassT | Callable[[_ModelClassT], _ModelClassT]:
    """Map section declaration decorator."""

    if isinstance(model_or_path, type):
        if not issubclass(model_or_path, BaseModel):
            raise TypeError("@SettingsMap can only decorate BaseModel subclasses")
        return _register_declared_model(model_or_path, section=None, kind="map")

    if model_or_path is not None and not isinstance(model_or_path, str):
        raise TypeError("@SettingsMap expects a dotted path string, model class, or no argument")

    section = model_or_path
    return _decorate_settings(section, kind="map")


__all__ = [
    "BaseSettings",
    "Settings",
    "SettingsMap",
]
