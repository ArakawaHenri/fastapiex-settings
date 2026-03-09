from __future__ import annotations

import sys
import weakref
from types import ModuleType

from pydantic import BaseModel

from .declaration_contract import Declaration, DeclarationOwner


def build_declaration_owner(module_name: str) -> DeclarationOwner:
    module = sys.modules.get(module_name)
    if not isinstance(module, ModuleType):
        return DeclarationOwner(module_name=module_name, module_ref=None)
    return DeclarationOwner(module_name=module_name, module_ref=weakref.ref(module))


def is_declaration_live(*, model: type[BaseModel], declaration: Declaration) -> bool:
    module = resolve_owner_module(declaration.owner)
    if module is None:
        return False

    if "<locals>" in model.__qualname__:
        return True

    namespace = getattr(module, "__dict__", None)
    if not isinstance(namespace, dict):
        return False
    return namespace.get(model.__name__) is model


def resolve_owner_module(owner: DeclarationOwner) -> ModuleType | None:
    module = sys.modules.get(owner.module_name)
    if not isinstance(module, ModuleType):
        return None

    owner_module = owner.module_ref() if owner.module_ref is not None else None
    if owner_module is None or owner_module is not module:
        return None

    return module


__all__ = [
    "build_declaration_owner",
    "is_declaration_live",
    "resolve_owner_module",
]
