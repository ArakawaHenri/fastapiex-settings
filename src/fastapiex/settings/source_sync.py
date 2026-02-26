from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from .control_model import ReloadMode
from .live_config import LiveConfigStore, SourceName, source_order

SourceSyncMode = Literal["none", "auto", "reload", "full"]
SourceState = tuple[str, bool, int, int] | None
SnapshotReader = Callable[[], tuple[dict[str, Any], SourceState]]


@dataclass(frozen=True)
class SourceSyncSpec:
    read_snapshot: SnapshotReader
    sync_on_reload: bool
    sync_on_path_switch: bool


class SourceSyncCoordinator:
    def __init__(self) -> None:
        self._source_states: dict[SourceName, SourceState] = {}
        self._source_sync_specs: dict[SourceName, SourceSyncSpec] = {}

    def register(
        self,
        source: SourceName,
        *,
        read_snapshot: SnapshotReader | None = None,
        sync_on_reload: bool | None = None,
        sync_on_path_switch: bool | None = None,
    ) -> None:
        if source not in source_order():
            allowed = ", ".join(source_order())
            raise ValueError(f"unknown source '{source}'; expected one of: {allowed}")

        current = self._source_sync_specs.get(source)
        if read_snapshot is None:
            if current is None:
                raise ValueError(f"source '{source}' is not registered; read_snapshot is required")
            resolved_reader = current.read_snapshot
        else:
            resolved_reader = read_snapshot

        resolved_reload = current.sync_on_reload if (current and sync_on_reload is None) else bool(sync_on_reload)
        resolved_path_switch = (
            current.sync_on_path_switch if (current and sync_on_path_switch is None) else bool(sync_on_path_switch)
        )
        self._source_sync_specs[source] = SourceSyncSpec(
            read_snapshot=resolved_reader,
            sync_on_reload=resolved_reload,
            sync_on_path_switch=resolved_path_switch,
        )

    def sync_for_mode(
        self,
        *,
        mode: SourceSyncMode,
        reload_mode: ReloadMode,
        live_config: LiveConfigStore | None,
    ) -> tuple[LiveConfigStore | None, bool]:
        if mode == "none":
            return live_config, False

        if mode == "full" or live_config is None:
            return self.reload_all(live_config=live_config)

        if mode == "auto":
            if reload_mode == "off":
                return live_config, False
            if reload_mode == "always":
                return live_config, self.sync_reload(live_config=live_config, force=True)
            return live_config, self.sync_reload(live_config=live_config, force=False)

        return live_config, self.sync_reload(live_config=live_config, force=True)

    def reload_all(self, *, live_config: LiveConfigStore | None) -> tuple[LiveConfigStore, bool]:
        source_payloads: dict[SourceName, dict[str, Any]] = {}
        source_states: dict[SourceName, SourceState] = {}

        for source in source_order():
            payload, state = self._read_source_snapshot(source)
            source_payloads[source] = payload
            source_states[source] = state

        resolved_live_config = live_config if live_config is not None else LiveConfigStore()
        changed = resolved_live_config.reset(source_payloads)
        self._source_states = source_states
        return resolved_live_config, changed

    def sync_reload(self, *, live_config: LiveConfigStore, force: bool) -> bool:
        return self._sync_selected(
            live_config=live_config,
            force=force,
            selector=lambda spec: spec.sync_on_reload,
        )

    def sync_path_switch(self, *, live_config: LiveConfigStore) -> bool:
        return self._sync_selected(
            live_config=live_config,
            force=True,
            selector=lambda spec: spec.sync_on_path_switch,
        )

    def _sync_selected(
        self,
        *,
        live_config: LiveConfigStore,
        force: bool,
        selector: Callable[[SourceSyncSpec], bool],
    ) -> bool:
        changed = False
        for source in source_order():
            spec = self._source_sync_specs.get(source)
            if spec is None or not selector(spec):
                continue
            changed = self._sync_source(
                live_config=live_config,
                source=source,
                force=force,
            ) or changed
        return changed

    def _sync_source(
        self,
        *,
        live_config: LiveConfigStore,
        source: SourceName,
        force: bool,
    ) -> bool:
        payload, state = self._read_source_snapshot(source)
        if not force and state is not None:
            previous_state = self._source_states.get(source)
            if previous_state == state:
                return False

        changed = live_config.replace_source(source, payload)
        self._source_states[source] = state
        return changed

    def _read_source_snapshot(self, source: SourceName) -> tuple[dict[str, Any], SourceState]:
        spec = self._source_sync_specs.get(source)
        if spec is None:
            return {}, None
        return spec.read_snapshot()
