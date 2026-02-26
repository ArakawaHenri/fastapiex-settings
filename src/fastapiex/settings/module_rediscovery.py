from __future__ import annotations

import sys
from types import ModuleType

from .controls import snapshot_fingerprint
from .discovery import diff_module_snapshots, discover_module_declarations, snapshot_imported_modules
from .registry import get_settings_registry


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
                    raw_path=raw_path,
                    cls=model,
                    kind=kind,
                    owner_module=owner_module,
                    owner_identity=owner_identity,
                )

        self.set_snapshot(current_snapshot)
        return registry.version() != before_version
