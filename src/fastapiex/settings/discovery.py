from __future__ import annotations

import sys
from dataclasses import dataclass
from types import ModuleType
from typing import Mapping

from pydantic import BaseModel

from .registry import build_section_spec, get_settings_registry
from .types import SectionKind


@dataclass(frozen=True)
class ModuleDelta:
    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[str, ...]


def snapshot_fingerprint(snapshot: Mapping[str, int]) -> int:
    return hash(frozenset(snapshot.items()))


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


class ModuleRediscovery:
    def __init__(self) -> None:
        self._snapshot: dict[str, int] = {}
        self._fingerprint: int = 0

    @property
    def snapshot(self) -> dict[str, int]:
        return self._snapshot

    @property
    def fingerprint(self) -> int:
        return self._fingerprint

    def set_snapshot(self, snapshot: dict[str, int]) -> None:
        copied = dict(snapshot)
        self._snapshot = copied
        self._fingerprint = snapshot_fingerprint(copied)

    def maybe_rediscover(self) -> bool:
        current_snapshot = snapshot_imported_modules()
        if current_snapshot == self._snapshot:
            return False

        self.rediscover_delta(current_snapshot=current_snapshot)
        return True

    def rediscover_delta(
        self,
        *,
        current_snapshot: dict[str, int] | None = None,
    ) -> bool:
        registry = get_settings_registry()
        before_version = registry.version()

        if current_snapshot is None:
            current_snapshot = snapshot_imported_modules()
        if not self._snapshot:
            self.set_snapshot(current_snapshot)
            return False

        previous_snapshot = self._snapshot
        delta = diff_module_snapshots(previous_snapshot, current_snapshot)

        for module_name in delta.removed:
            registry.unregister_owner(module_name)

        for module_name in delta.changed:
            old_identity = previous_snapshot.get(module_name)
            registry.unregister_owner(module_name, owner_identity=old_identity)

        for module_name in (*delta.added, *delta.changed):
            module = sys.modules.get(module_name)
            if not isinstance(module, ModuleType):
                continue
            declarations = discover_module_declarations(module_name=module_name, module=module)
            for raw_path, model, kind, owner_module, owner_identity in declarations:
                registry.register_section(
                    spec=build_section_spec(model=model, kind=kind, raw_path=raw_path),
                    owner_module=owner_module,
                    owner_identity=owner_identity,
                )

        self.set_snapshot(current_snapshot)
        return registry.version() != before_version
