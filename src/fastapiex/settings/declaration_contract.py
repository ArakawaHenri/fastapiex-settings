from __future__ import annotations

import weakref
from dataclasses import dataclass
from types import ModuleType

from .specs import SectionSpec


@dataclass(frozen=True, slots=True)
class DeclarationOwner:
    module_name: str
    module_ref: weakref.ReferenceType[ModuleType] | None


@dataclass(frozen=True, slots=True)
class Declaration:
    spec: SectionSpec
    owner: DeclarationOwner


@dataclass(frozen=True, slots=True)
class RegistrySnapshot:
    version: int
    sections: tuple[SectionSpec, ...]

__all__ = [
    "Declaration",
    "DeclarationOwner",
    "RegistrySnapshot",
]
