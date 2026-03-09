from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar, overload

from pydantic import BaseModel

from .control_contract import CONTROL_SPEC
from .declaration_contract import Declaration, RegistrySnapshot
from .exceptions import SettingsRegistrationError
from .lifecycle import build_declaration_owner, is_declaration_live
from .specs import SectionSpec, describe_section
from .types import SectionKind

_ModelClassT = TypeVar("_ModelClassT", bound=type[BaseModel])


def build_section_spec(
    *,
    model: type[BaseModel],
    kind: SectionKind,
    raw_path: str | None = None,
) -> SectionSpec:
    try:
        spec = describe_section(model, kind=kind, explicit=raw_path)
    except ValueError as exc:
        raise SettingsRegistrationError(str(exc)) from exc

    if spec.root.casefold() == CONTROL_SPEC.root.casefold():
        reserved = CONTROL_SPEC.root.upper()
        raise SettingsRegistrationError(f"section path '{spec.raw_path}' uses reserved prefix '{reserved}.*'")

    return spec


class SettingsRegistry:
    """Process-global declaration registry with owner-based lifecycle."""

    def __init__(self) -> None:
        self._declarations_by_model: dict[type[BaseModel], Declaration] = {}
        self._sections_by_path: dict[tuple[str, ...], SectionSpec] = {}
        self._ordered_sections: tuple[SectionSpec, ...] = ()
        self._version = 0
        self._lock = threading.RLock()

    def register_section(
        self,
        *,
        spec: SectionSpec,
        owner_module: str,
    ) -> None:
        with self._lock:
            kind = spec.kind
            model = spec.model
            if not isinstance(model, type) or not issubclass(model, BaseModel):
                raise SettingsRegistrationError("settings section model must be a BaseModel subclass")

            if kind not in {"object", "map"}:
                raise SettingsRegistrationError(f"unsupported section kind: {kind!r}")

            previous_declarations = dict(self._declarations_by_model)
            previous_sections = self._sections_by_path
            previous_ordered_sections = self._ordered_sections
            previous_version = self._version

            try:
                changed = self._drop_stale_declarations_for_owner_locked(owner_module=owner_module)
                changed = self._drop_redefined_declarations_for_owner_locked(
                    owner_module=owner_module,
                    model=model,
                    spec=spec,
                ) or changed

                existing = self._declarations_by_model.get(model)
                candidate = Declaration(
                    spec=spec,
                    owner=build_declaration_owner(owner_module),
                )
                if existing == candidate:
                    if changed:
                        self._reindex_locked()
                    return

                self._declarations_by_model[model] = candidate
                self._reindex_locked()
            except SettingsRegistrationError:
                self._declarations_by_model = previous_declarations
                self._sections_by_path = previous_sections
                self._ordered_sections = previous_ordered_sections
                self._version = previous_version
                raise

    def reconcile_runtime_modules(self) -> bool:
        with self._lock:
            changed = False
            for model, declaration in list(self._declarations_by_model.items()):
                if self._record_is_live_locked(model=model, record=declaration):
                    continue
                del self._declarations_by_model[model]
                changed = True

            if changed:
                self._reindex_locked()
            return changed

    def unregister_owner(self, owner_module: str) -> None:
        with self._lock:
            removed = False
            for model, declaration in list(self._declarations_by_model.items()):
                if declaration.owner.module_name != owner_module:
                    continue
                del self._declarations_by_model[model]
                removed = True

            if removed:
                self._reindex_locked()

    def snapshot(self) -> RegistrySnapshot:
        with self._lock:
            return RegistrySnapshot(version=self._version, sections=self._ordered_sections)

    def sections(self) -> list[SectionSpec]:
        return list(self.snapshot().sections)

    def version(self) -> int:
        with self._lock:
            return self._version

    def _reindex_locked(self) -> None:
        new_sections: dict[tuple[str, ...], SectionSpec] = {}

        for declaration in self._declarations_by_model.values():
            section = declaration.spec
            existing = new_sections.get(section.path)
            if existing is not None and existing.model is not section.model:
                raise SettingsRegistrationError(
                    f"duplicate section '{section.path_text}' for "
                    f"{existing.model.__module__}.{existing.model.__qualname__} and "
                    f"{section.model.__module__}.{section.model.__qualname__}"
                )
            new_sections[section.path] = section

        self._sections_by_path = new_sections
        self._ordered_sections = tuple(new_sections[key] for key in sorted(new_sections))
        self._version += 1

    def _drop_stale_declarations_for_owner_locked(self, *, owner_module: str) -> bool:
        removed = False
        for model, declaration in list(self._declarations_by_model.items()):
            if declaration.owner.module_name != owner_module:
                continue
            if self._record_is_live_locked(model=model, record=declaration):
                continue
            del self._declarations_by_model[model]
            removed = True
        return removed

    def _drop_redefined_declarations_for_owner_locked(
        self,
        *,
        owner_module: str,
        model: type[BaseModel],
        spec: SectionSpec,
    ) -> bool:
        removed = False
        for existing_model, declaration in list(self._declarations_by_model.items()):
            if declaration.owner.module_name != owner_module:
                continue
            if existing_model is model:
                continue
            if declaration.spec.path != spec.path:
                continue
            if existing_model.__name__ != model.__name__:
                continue
            del self._declarations_by_model[existing_model]
            removed = True
        return removed

    @staticmethod
    def _record_is_live_locked(*, model: type[BaseModel], record: Declaration) -> bool:
        return is_declaration_live(model=model, declaration=record)


_GLOBAL_REGISTRY = SettingsRegistry()


def get_settings_registry() -> SettingsRegistry:
    return _GLOBAL_REGISTRY


def _register_declared_model(
    cls: _ModelClassT,
    *,
    section: str | None,
    kind: SectionKind,
) -> _ModelClassT:
    if not issubclass(cls, BaseModel):
        raise SettingsRegistrationError("@Settings declarations require a BaseModel subclass")

    spec = build_section_spec(model=cls, kind=kind, raw_path=section)

    registry = get_settings_registry()
    registry.register_section(
        spec=spec,
        owner_module=cls.__module__,
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

    return _decorate_settings(model_or_path, kind="object")


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

    return _decorate_settings(model_or_path, kind="map")


__all__ = [
    "Settings",
    "SettingsMap",
    "SettingsRegistry",
    "get_settings_registry",
]
