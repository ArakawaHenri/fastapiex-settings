from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from .controls import (
    BASE_DIR_KEYS,
    ENV_PREFIX_KEYS,
    SETTINGS_PATH_KEYS,
    build_env_controls_snapshot,
    file_state,
    normalize_override_path,
    read_nested_str,
    runtime_options_from_controls,
    snapshot_fingerprint,
)
from .discovery import (
    diff_module_snapshots,
    discover_module_declarations,
    snapshot_imported_modules,
)
from .exceptions import SettingsResolveError, SettingsValidationError
from .live_config import LiveConfigStore, SourceName, source_order
from .loader import (
    find_dotenv_path,
    load_dotenv_overrides,
    load_env_overrides,
    load_yaml_settings,
    resolve_env_prefix,
)
from .path_lookup import resolve_lookup_path, section_matches_target_type
from .registry import SettingsSection, get_settings_registry
from .runtime_options import ReloadMode
from .schema_builder import BuiltSchema, build_root_settings_model

logger = logging.getLogger(__name__)

_NO_DEFAULT = object()

ResolveAPI = Literal["settings", "map"]
SourceSyncMode = Literal["none", "auto", "reload", "full"]
_SOURCE_STATE = tuple[str, bool, int, int] | None
_SNAPSHOT_READER = Callable[[], tuple[dict[str, Any], _SOURCE_STATE]]


@dataclass(frozen=True)
class _SourceSyncSpec:
    read_snapshot: _SNAPSHOT_READER
    sync_on_reload: bool
    sync_on_path_switch: bool


@dataclass(frozen=True)
class SettingsSource:
    settings_path: Path
    env_prefix: str
    case_sensitive: bool
    reload_mode: ReloadMode


@dataclass(frozen=True)
class _ResolveRequest:
    api: ResolveAPI
    target: str | type[object] | None
    field: str | None
    default: object
    has_default: bool

    def cache_key(self) -> str:
        target_repr: str
        if isinstance(self.target, str):
            target_repr = f"str:{self.target}"
        elif isinstance(self.target, type):
            target_repr = f"type:{self.target.__module__}.{self.target.__qualname__}"
        else:
            target_repr = "none"
        return f"{self.api}|{target_repr}|field={self.field}"


class _QueryMiss(Exception):
    pass


class SettingsManager:
    def __init__(self) -> None:
        self._source: SettingsSource | None = None
        self._live_config: LiveConfigStore | None = None
        self._schema: BuiltSchema | None = None
        self._registry_version: int = -1
        self._snapshot_live_version: int = -1
        self._settings: BaseModel | None = None
        self._lock = threading.RLock()
        self._source_states: dict[SourceName, _SOURCE_STATE] = {}
        self._source_sync_specs: dict[SourceName, _SourceSyncSpec] = {}

        self._module_snapshot: dict[str, int] = {}
        self._module_fingerprint: int = 0
        self._missing_cache: dict[str, tuple[int, int]] = {}
        self._validation_fallback_warnings: set[str] = set()

        self._register_default_source_syncs()

    def _register_default_source_syncs(self) -> None:
        self.register_source_sync(
            "yaml",
            read_snapshot=self._read_yaml_snapshot_locked,
            sync_on_reload=True,
            sync_on_path_switch=True,
        )
        self.register_source_sync("dotenv", read_snapshot=self._read_dotenv_snapshot_locked)
        self.register_source_sync("env", read_snapshot=self._read_env_snapshot_locked)

    def register_source_sync(
        self,
        source: SourceName,
        *,
        read_snapshot: _SNAPSHOT_READER | None = None,
        sync_on_reload: bool | None = None,
        sync_on_path_switch: bool | None = None,
    ) -> None:
        with self._lock:
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
            self._source_sync_specs[source] = _SourceSyncSpec(
                read_snapshot=resolved_reader,
                sync_on_reload=resolved_reload,
                sync_on_path_switch=resolved_path_switch,
            )

    def init(
        self,
        *,
        settings_path: str | Path | None = None,
        env_prefix: str | None = None,
    ) -> BaseModel:
        source = self._resolve_source(
            settings_path=settings_path,
            env_prefix=env_prefix,
        )

        with self._lock:
            if self._source is not None and self._source != source:
                raise RuntimeError(
                    "settings source is already initialized with a different source "
                    f"(current={self._source}, requested={source})"
                )

            self._source = source
            if not self._module_snapshot:
                self._set_module_snapshot_locked(snapshot_imported_modules())
            self._prepare_runtime_locked(
                reason="init",
                implicit_init=False,
                source_sync="full",
                force_refresh=True,
                rediscover_modules=False,
            )
            assert self._settings is not None
            return self._settings

    def get(self) -> BaseModel:
        with self._lock:
            self._prepare_runtime_locked(
                reason="get",
                implicit_init=True,
                source_sync="auto",
            )
            assert self._settings is not None
            return self._settings

    def resolve_settings(
        self,
        *,
        target: str | type[object] | None,
        field: str | None,
        default: object = _NO_DEFAULT,
        has_default: bool = False,
    ) -> Any:
        request = _ResolveRequest(
            api="settings",
            target=target,
            field=field,
            default=default,
            has_default=has_default,
        )
        return self._resolve_request(request)

    def resolve_settings_map(
        self,
        *,
        target: str | type[object] | None,
        default: object = _NO_DEFAULT,
        has_default: bool = False,
    ) -> Mapping[str, Any]:
        request = _ResolveRequest(
            api="map",
            target=target,
            field=None,
            default=default,
            has_default=has_default,
        )
        result = self._resolve_request(request)
        if not isinstance(result, Mapping):
            raise SettingsResolveError("resolved value is not a mapping")
        return result

    def reload(self, *, reason: str = "manual") -> BaseModel:
        with self._lock:
            self._prepare_runtime_locked(
                reason=f"reload:{reason}",
                implicit_init=False,
                source_sync="reload",
                force_refresh=True,
                rediscover_modules=False,
            )
            assert self._settings is not None
            logger.info("settings reloaded reason=%s", reason)
            return self._settings

    def _prepare_runtime_locked(
        self,
        *,
        reason: str,
        implicit_init: bool,
        source_sync: SourceSyncMode,
        force_refresh: bool = False,
        rediscover_modules: bool = True,
    ) -> None:
        self._ensure_source_locked(implicit=implicit_init)
        source_force_refresh = self._sync_sources_for_mode_locked(mode=source_sync)
        runtime_changed = self._sync_runtime_options_locked()
        module_changed = self._maybe_rediscover_modules_locked() if rediscover_modules else False
        self._refresh_runtime_locked(
            reason=reason,
            force=force_refresh or source_force_refresh or runtime_changed or module_changed,
        )

    def _sync_sources_for_mode_locked(self, *, mode: SourceSyncMode) -> bool:
        if mode == "none":
            return False
        if mode == "auto":
            return self._maybe_auto_reload_locked()
        if mode == "reload":
            return self._sync_reload_sources_locked(force=True)
        return self._reload_live_sources_locked()

    def _resolve_request(self, request: _ResolveRequest) -> Any:
        with self._lock:
            query_error: Exception | None = None
            validation_error: SettingsValidationError | None = None

            try:
                self._prepare_runtime_locked(
                    reason="resolve:registered",
                    implicit_init=True,
                    source_sync="auto",
                )
                return self._evaluate_request_locked(request)
            except _QueryMiss as exc:
                query_error = exc
            except (KeyError, IndexError, AttributeError) as exc:
                query_error = _QueryMiss(str(exc))
            except SettingsValidationError as exc:
                validation_error = exc

            cache_key = request.cache_key()
            if not self._should_skip_rediscovery_locked(cache_key):
                self._rediscover_delta_locked()
                try:
                    self._prepare_runtime_locked(
                        reason="resolve:rediscover",
                        implicit_init=True,
                        source_sync="auto",
                        rediscover_modules=False,
                    )
                    value = self._evaluate_request_locked(request)
                    self._missing_cache.pop(cache_key, None)
                    return value
                except _QueryMiss as exc:
                    query_error = exc
                    self._missing_cache[cache_key] = (
                        get_settings_registry().version(),
                        self._module_fingerprint,
                    )
                except (KeyError, IndexError, AttributeError) as exc:
                    query_error = _QueryMiss(str(exc))
                    self._missing_cache[cache_key] = (
                        get_settings_registry().version(),
                        self._module_fingerprint,
                    )
                except SettingsValidationError as exc:
                    validation_error = exc

            if request.has_default:
                if validation_error is not None:
                    self._warn_validation_fallback_once_locked(request, validation_error)
                return self._resolve_from_default_locked(request)

            if validation_error is not None:
                raise validation_error
            if query_error is not None:
                raise SettingsResolveError(str(query_error)) from query_error
            raise SettingsResolveError("settings value could not be resolved")

    def _evaluate_request_locked(self, request: _ResolveRequest) -> Any:
        assert self._settings is not None
        assert self._source is not None

        case_sensitive = self._source.case_sensitive
        value = self._resolve_target_value_locked(target=request.target, case_sensitive=case_sensitive)

        if request.field is not None:
            field = request.field.strip()
            if not field:
                raise _QueryMiss("field is empty")
            value = resolve_lookup_path(value, field, case_sensitive=case_sensitive)

        if request.api == "map" and not isinstance(value, Mapping):
            raise _QueryMiss("resolved value is not a mapping")

        return value

    def _resolve_target_value_locked(
        self,
        *,
        target: str | type[object] | None,
        case_sensitive: bool,
    ) -> Any:
        assert self._settings is not None

        if target is None:
            raise _QueryMiss("target is not provided")

        if isinstance(target, str):
            target_text = target.strip()
            if not target_text:
                raise _QueryMiss("target is empty")
            return resolve_lookup_path(self._settings, target_text, case_sensitive=case_sensitive)

        if not isinstance(target, type):
            raise _QueryMiss("target must be a string path or class")

        section = self._resolve_type_target_locked(target_type=target)
        # Type-target injection should resolve the declared section exactly, independent of read mode.
        return resolve_lookup_path(self._settings, section.path_text, case_sensitive=True)

    def _resolve_type_target_locked(self, *, target_type: type[object]) -> SettingsSection:
        sections = get_settings_registry().sections()
        target_name = f"{target_type.__module__}.{target_type.__qualname__}"
        candidates = [section for section in sections if section_matches_target_type(section, target_type)]

        return self._select_unique_type_target_locked(
            target_name=target_name,
            candidates=candidates,
        )

    def _select_unique_type_target_locked(
        self,
        *,
        target_name: str,
        candidates: list[SettingsSection],
    ) -> SettingsSection:
        if not candidates:
            raise _QueryMiss(f"target type '{target_name}' did not match any declared section")

        if len(candidates) > 1:
            matched_paths = ", ".join(sorted(section.path_text for section in candidates))
            raise _QueryMiss(f"target type '{target_name}' matched multiple sections: {matched_paths}")

        return candidates[0]

    def _resolve_from_default_locked(self, request: _ResolveRequest) -> Any:
        if request.api == "map" and not isinstance(request.default, Mapping):
            raise SettingsResolveError("default value for SettingsMap must be a mapping")
        return request.default

    def _should_skip_rediscovery_locked(self, cache_key: str) -> bool:
        marker = self._missing_cache.get(cache_key)
        if marker is None:
            return False
        current = (get_settings_registry().version(), self._module_fingerprint)
        return marker == current

    def _warn_validation_fallback_once_locked(
        self,
        request: _ResolveRequest,
        error: SettingsValidationError,
    ) -> None:
        assert self._source is not None
        warning_key = f"{self._source.settings_path}|{request.cache_key()}|{error.__class__.__name__}|{str(error)}"
        if warning_key in self._validation_fallback_warnings:
            return

        self._validation_fallback_warnings.add(warning_key)
        logger.warning(
            "settings validation failed; falling back to default target=%r field=%r error=%s",
            request.target,
            request.field,
            error,
        )

    def _ensure_source_locked(self, *, implicit: bool) -> None:
        if self._source is not None:
            return

        if not implicit:
            raise RuntimeError("settings are not initialized")

        self._source = self._resolve_source(
            settings_path=None,
            env_prefix=None,
        )
        self._set_module_snapshot_locked(snapshot_imported_modules())
        self._reload_live_sources_locked()
        logger.info("settings initialized implicitly source=%s", self._source)

    def _sync_runtime_options_locked(self) -> bool:
        assert self._source is not None
        controls = self._read_controls_snapshot_locked()
        runtime_options = runtime_options_from_controls(controls)
        updated = SettingsSource(
            settings_path=self._source.settings_path,
            env_prefix=self._source.env_prefix,
            case_sensitive=runtime_options.case_sensitive,
            reload_mode=runtime_options.reload_mode,
        )
        changed = updated != self._source
        self._source = updated
        return changed

    def _maybe_auto_reload_locked(self) -> bool:
        assert self._source is not None
        mode = self._source.reload_mode
        if mode == "off":
            return False

        if mode == "always":
            self._sync_reload_sources_locked(force=True)
            return True

        self._sync_reload_sources_locked(force=False)
        return False

    def _reload_live_sources_locked(self) -> bool:
        assert self._source is not None

        source_payloads: dict[SourceName, dict[str, Any]] = {}
        source_states: dict[SourceName, _SOURCE_STATE] = {}
        for source in source_order():
            payload, state = self._read_source_snapshot_locked(source)
            source_payloads[source] = payload
            source_states[source] = state

        if self._live_config is None:
            self._live_config = LiveConfigStore()

        changed = self._live_config.reset(source_payloads)
        self._source_states = source_states
        switched = self._sync_settings_path_from_snapshot_locked()
        return changed or switched

    def _sync_reload_sources_locked(self, *, force: bool) -> bool:
        assert self._source is not None
        assert self._live_config is not None

        changed = self._sync_selected_sources_locked(
            force=force,
            selector=lambda spec: spec.sync_on_reload,
        )
        if not force and not changed:
            return False

        switched = self._sync_settings_path_from_snapshot_locked()
        return changed or switched

    def _sync_selected_sources_locked(
        self,
        *,
        force: bool,
        selector: Callable[[_SourceSyncSpec], bool],
    ) -> bool:
        changed = False
        for source in source_order():
            spec = self._source_sync_specs.get(source)
            if spec is None:
                continue
            if not selector(spec):
                continue
            changed = self._sync_source_locked(source, force=force) or changed
        return changed

    def _sync_source_locked(self, source: SourceName, *, force: bool) -> bool:
        assert self._live_config is not None

        payload, state = self._read_source_snapshot_locked(source)
        if not force and state is not None:
            previous_state = self._source_states.get(source)
            if previous_state == state:
                return False

        changed = self._live_config.replace_source(source, payload)
        self._source_states[source] = state
        return changed

    def _read_source_snapshot_locked(
        self,
        source: SourceName,
    ) -> tuple[dict[str, Any], _SOURCE_STATE]:
        spec = self._source_sync_specs.get(source)
        if spec is None:
            return {}, None
        return spec.read_snapshot()

    def _read_yaml_snapshot_locked(self) -> tuple[dict[str, Any], _SOURCE_STATE]:
        assert self._source is not None
        path = self._source.settings_path
        return load_yaml_settings(path), file_state(path)

    def _read_dotenv_snapshot_locked(self) -> tuple[dict[str, Any], _SOURCE_STATE]:
        assert self._source is not None
        start_dir = self._source.settings_path.parent
        mapping = load_dotenv_overrides(
            start_dir=start_dir,
            prefix=self._source.env_prefix,
            case_sensitive=self._source.case_sensitive,
        )
        return mapping, file_state(find_dotenv_path(start_dir))

    def _read_env_snapshot_locked(self) -> tuple[dict[str, Any], _SOURCE_STATE]:
        assert self._source is not None
        mapping = load_env_overrides(
            prefix=self._source.env_prefix,
            case_sensitive=self._source.case_sensitive,
        )
        return mapping, None

    def _sync_settings_path_from_snapshot_locked(self) -> bool:
        assert self._source is not None
        assert self._live_config is not None

        switched = False
        visited: set[Path] = {self._source.settings_path}
        while True:
            next_path = self._read_settings_path_from_snapshot_locked()
            if next_path is None or next_path == self._source.settings_path:
                return switched

            if next_path in visited:
                logger.warning("settings path control cycle detected; keeping path=%s", self._source.settings_path)
                return switched
            visited.add(next_path)

            self._source = replace(self._source, settings_path=next_path)
            changed = self._sync_selected_sources_locked(
                force=True,
                selector=lambda spec: spec.sync_on_path_switch,
            )
            switched = switched or changed or True

    def _read_settings_path_from_snapshot_locked(self) -> Path | None:
        assert self._live_config is not None
        snapshot = self._live_config.materialize()
        return normalize_override_path(read_nested_str(snapshot, SETTINGS_PATH_KEYS))

    def _maybe_rediscover_modules_locked(self) -> bool:
        current_snapshot = snapshot_imported_modules()
        current_fingerprint = snapshot_fingerprint(current_snapshot)
        if current_fingerprint == self._module_fingerprint:
            return False

        self._rediscover_delta_locked(current_snapshot=current_snapshot)
        return True

    def _refresh_runtime_locked(self, *, reason: str, force: bool = False) -> None:
        assert self._source is not None
        assert self._live_config is not None

        registry_version = get_settings_registry().version()
        schema_outdated = self._schema is None or registry_version != self._registry_version
        live_version = self._live_config.version()
        live_outdated = live_version != self._snapshot_live_version
        settings_missing = self._settings is None

        if not force and not schema_outdated and not live_outdated and not settings_missing:
            return

        if schema_outdated:
            self._schema = build_root_settings_model(get_settings_registry().sections())
            self._registry_version = registry_version
        assert self._schema is not None

        raw = self._live_config.materialize()
        try:
            self._settings = self._schema.root_model.model_validate(raw)
        except ValidationError as exc:
            raise SettingsValidationError(str(exc)) from exc

        logger.info(
            "settings refreshed reason=%s registry_version=%s live_version=%s",
            reason,
            registry_version,
            live_version,
        )
        self._snapshot_live_version = live_version

    def _rediscover_delta_locked(
        self,
        *,
        current_snapshot: dict[str, int] | None = None,
    ) -> bool:
        registry = get_settings_registry()
        before_version = registry.version()

        if current_snapshot is None:
            current_snapshot = snapshot_imported_modules()
        if not self._module_snapshot:
            self._set_module_snapshot_locked(current_snapshot)
            return False
        previous_snapshot = self._module_snapshot

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

        self._set_module_snapshot_locked(current_snapshot)

        changed = registry.version() != before_version
        if changed:
            self._missing_cache.clear()
        return changed

    def _set_module_snapshot_locked(self, snapshot: dict[str, int]) -> None:
        self._module_snapshot = snapshot
        self._module_fingerprint = snapshot_fingerprint(snapshot)

    def _resolve_source(
        self,
        *,
        settings_path: str | Path | None,
        env_prefix: str | None,
    ) -> SettingsSource:
        controls = build_env_controls_snapshot()
        arg_settings_path = normalize_override_path(settings_path)
        env_settings_path = normalize_override_path(read_nested_str(controls, SETTINGS_PATH_KEYS))
        env_base_dir = normalize_override_path(read_nested_str(controls, BASE_DIR_KEYS), as_directory=True)
        if arg_settings_path is not None:
            resolved_path = arg_settings_path
        elif env_settings_path is not None:
            resolved_path = env_settings_path
        elif env_base_dir is not None:
            resolved_path = (env_base_dir / "settings.yaml").resolve()
        else:
            resolved_path = (Path.cwd().resolve() / "settings.yaml").resolve()

        runtime_options = runtime_options_from_controls(controls)
        control_env_prefix = read_nested_str(controls, ENV_PREFIX_KEYS) or ""
        resolved_env_prefix = resolve_env_prefix(env_prefix if env_prefix is not None else control_env_prefix)
        return SettingsSource(
            settings_path=resolved_path,
            env_prefix=resolved_env_prefix,
            case_sensitive=runtime_options.case_sensitive,
            reload_mode=runtime_options.reload_mode,
        )

    def _read_controls_snapshot_locked(self) -> Mapping[Any, Any]:
        assert self._live_config is not None
        return self._live_config.materialize()


_GLOBAL_MANAGER = SettingsManager()


def get_settings_manager() -> SettingsManager:
    return _GLOBAL_MANAGER


def init_settings(
    *,
    settings_path: str | Path | None = None,
    env_prefix: str | None = None,
) -> BaseModel:
    return get_settings_manager().init(
        settings_path=settings_path,
        env_prefix=env_prefix,
    )


def reload_settings(*, reason: str = "manual") -> BaseModel:
    return get_settings_manager().reload(reason=reason)


def register_source_sync(
    source: SourceName,
    *,
    read_snapshot: _SNAPSHOT_READER | None = None,
    sync_on_reload: bool | None = None,
    sync_on_path_switch: bool | None = None,
) -> None:
    get_settings_manager().register_source_sync(
        source,
        read_snapshot=read_snapshot,
        sync_on_reload=sync_on_reload,
        sync_on_path_switch=sync_on_path_switch,
    )
