from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType

from pydantic import BaseModel

from .registry import SectionKind


@dataclass(frozen=True)
class ModuleDelta:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]


def snapshot_imported_modules() -> dict[str, int]:
    try:
        return {
            name: id(module)
            for name, module in sys.modules.items()
            if module is not None
        }
    except RuntimeError:
        # Fall back to a copied view when sys.modules mutates during iteration.
        snapshot: dict[str, int] = {}
        for name, module in list(sys.modules.items()):
            if module is None:
                continue
            snapshot[name] = id(module)
        return snapshot


def diff_module_snapshots(previous: dict[str, int], current: dict[str, int]) -> ModuleDelta:
    prev_names = set(previous)
    curr_names = set(current)

    added = tuple(sorted(curr_names - prev_names))
    removed = tuple(sorted(prev_names - curr_names))

    changed_names: list[str] = []
    for name in sorted(prev_names & curr_names):
        if previous[name] != current[name]:
            changed_names.append(name)

    return ModuleDelta(
        added=added,
        removed=removed,
        changed=tuple(changed_names),
    )


def discover_module_declarations(
    *,
    module_name: str,
    module: ModuleType,
) -> tuple[tuple[str, type[BaseModel], SectionKind, str, int], ...]:
    owner_identity = id(module)
    discovered: list[tuple[str, type[BaseModel], SectionKind, str, int]] = []

    namespace = getattr(module, "__dict__", None)
    if not isinstance(namespace, dict):
        return ()

    for value in namespace.values():
        if not isinstance(value, type):
            continue
        if value.__module__ != module_name:
            continue
        if getattr(value, "__fastapiex_settings_model__", False) is not True:
            continue
        if not issubclass(value, BaseModel):
            continue

        raw_path = getattr(value, "__section__", None)
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue

        is_map = bool(getattr(value, "__fastapiex_settings_is_map__", False))
        kind: SectionKind = "map" if is_map else "object"
        discovered.append((raw_path, value, kind, module_name, owner_identity))

    return tuple(discovered)
