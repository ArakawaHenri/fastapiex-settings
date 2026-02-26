from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from .control_model import CONTROL_ROOT
from .errors import SettingsRegistrationError
from .section_path import split_dotted_path
from .types import SectionKind

_RESERVED_ROOT = CONTROL_ROOT.upper()


@dataclass(frozen=True)
class SettingsSection:
    raw_path: str
    path: tuple[str, ...]
    model: type[BaseModel]
    kind: SectionKind
    owner_module: str
    owner_identity: int

    @property
    def path_text(self) -> str:
        return ".".join(self.path)


@dataclass(frozen=True)
class _SectionRecord:
    raw_path: str
    model: type[BaseModel]
    kind: SectionKind
    owner_module: str
    owner_identity: int


def canonicalize_path(raw_path: str) -> tuple[str, ...]:
    raw_parts = split_dotted_path(raw_path)

    if raw_parts[0].casefold() == _RESERVED_ROOT.casefold():
        raise SettingsRegistrationError(f"section path '{raw_path}' uses reserved prefix '{_RESERVED_ROOT}.*'")

    return raw_parts


class SettingsRegistry:
    """Process-global declaration registry with owner-based lifecycle."""

    def __init__(self) -> None:
        self._records_by_model: dict[type[BaseModel], _SectionRecord] = {}
        self._sections_by_path: dict[tuple[str, ...], SettingsSection] = {}
        self._version = 0

    def register_section(
        self,
        *,
        raw_path: str,
        cls: type[object],
        kind: SectionKind,
        owner_module: str,
        owner_identity: int,
    ) -> None:
        if not isinstance(cls, type) or not issubclass(cls, BaseModel):
            raise SettingsRegistrationError("settings section model must be a BaseModel subclass")

        if kind not in {"object", "map"}:
            raise SettingsRegistrationError(f"unsupported section kind: {kind!r}")

        model = cls
        previous_records = dict(self._records_by_model)
        previous_sections = self._sections_by_path
        previous_version = self._version

        try:
            for existing_model, existing_record in list(self._records_by_model.items()):
                if existing_record.owner_module != owner_module:
                    continue
                if existing_record.owner_identity == owner_identity:
                    continue
                del self._records_by_model[existing_model]

            existing = self._records_by_model.get(model)
            candidate = _SectionRecord(
                raw_path=raw_path,
                model=model,
                kind=kind,
                owner_module=owner_module,
                owner_identity=owner_identity,
            )
            if existing == candidate:
                return

            self._records_by_model[model] = candidate
            self._reindex()
        except SettingsRegistrationError:
            self._records_by_model = previous_records
            self._sections_by_path = previous_sections
            self._version = previous_version
            raise

    def unregister_owner(self, owner_module: str, *, owner_identity: int | None = None) -> None:
        removed = False
        for model, record in list(self._records_by_model.items()):
            if record.owner_module != owner_module:
                continue
            if owner_identity is not None and record.owner_identity != owner_identity:
                continue
            del self._records_by_model[model]
            removed = True

        if removed:
            self._reindex()

    def sections(self) -> list[SettingsSection]:
        return [self._sections_by_path[key] for key in sorted(self._sections_by_path)]

    def version(self) -> int:
        return self._version

    def _reindex(self) -> None:
        new_sections: dict[tuple[str, ...], SettingsSection] = {}

        for record in self._records_by_model.values():
            path = canonicalize_path(record.raw_path)
            section = SettingsSection(
                raw_path=record.raw_path,
                path=path,
                model=record.model,
                kind=record.kind,
                owner_module=record.owner_module,
                owner_identity=record.owner_identity,
            )

            existing = new_sections.get(path)
            if existing is not None and existing.model is not record.model:
                raise SettingsRegistrationError(
                    f"duplicate section '{'.'.join(path)}' for "
                    f"{existing.model.__module__}.{existing.model.__qualname__} and "
                    f"{record.model.__module__}.{record.model.__qualname__}"
                )
            new_sections[path] = section

        self._sections_by_path = new_sections
        self._version += 1


_GLOBAL_REGISTRY = SettingsRegistry()


def get_settings_registry() -> SettingsRegistry:
    return _GLOBAL_REGISTRY
