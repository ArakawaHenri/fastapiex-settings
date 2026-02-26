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

from .control_model import ControlModel, ReloadMode
from .control_resolver import read_control_model
from .controls import build_env_controls_snapshot, file_state, normalize_override_path, snapshot_fingerprint
from .discovery import (
    diff_module_snapshots,
    discover_module_declarations,
    snapshot_imported_modules,
)
from .exceptions import SettingsResolveError, SettingsValidationError
from .live_config import LiveConfigStore, SourceName, source_order
from .loader import (
    find_dotenv_path,
    load_dotenv_snapshot_raw,
    load_env_snapshot_raw,
    load_yaml_settings,
    resolve_env_prefix,
)
from .query_engine import QueryMiss, ResolveRequest, evaluate_request, resolve_default
from .raw_projection import materialize_control_snapshot, materialize_effective_snapshot
from .registry import get_settings_registry
from .schema_builder import BuiltSchema, build_root_settings_model
from .snapshot_projection import project_snapshot_for_validation

logger = logging.getLogger(__name__)

_NO_DEFAULT = object()

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
class _ResolveAttempt:
    resolved: bool
    value: Any = None
    query_error: QueryMiss | None = None
    validation_error: SettingsValidationError | None = None


@dataclass(frozen=True)
class _RefreshPlan:
    should_refresh: bool
    registry_version: int
    live_version: int
    schema_outdated: bool


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
            return self._active_settings_locked()

    def get(self) -> BaseModel:
        with self._lock:
            self._prepare_runtime_locked(
                reason="get",
                implicit_init=True,
                source_sync="auto",
            )
            return self._active_settings_locked()

    def resolve_settings(
        self,
        *,
        target: str | type[object] | None,
        field: str | None,
        default: object = _NO_DEFAULT,
        has_default: bool = False,
    ) -> Any:
        request = ResolveRequest(
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
        request = ResolveRequest(
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
            settings = self._active_settings_locked()
            logger.info("settings reloaded reason=%s", reason)
            return settings

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
        needs_control_convergence = force_refresh or source_force_refresh or self._settings is None
        controls_changed = self._converge_controls_locked() if needs_control_convergence else False
        module_changed = self._maybe_rediscover_modules_locked() if rediscover_modules else False
        self._refresh_runtime_locked(
            reason=reason,
            force=force_refresh or source_force_refresh or controls_changed or module_changed,
        )

    def _sync_sources_for_mode_locked(self, *, mode: SourceSyncMode) -> bool:
        if mode == "none":
            return False
        if mode == "auto":
            return self._maybe_auto_reload_locked()
        if mode == "reload":
            return self._sync_reload_sources_locked(force=True)
        return self._reload_live_sources_locked()

    def _resolve_request(self, request: ResolveRequest) -> Any:
        with self._lock:
            initial_attempt = self._attempt_resolve_locked(
                request=request,
                reason="resolve:registered",
                rediscover_modules=True,
            )
            if initial_attempt.resolved:
                return initial_attempt.value

            cache_key = request.cache_key()
            query_error = initial_attempt.query_error
            validation_error = initial_attempt.validation_error

            if not self._should_skip_rediscovery_locked(cache_key):
                self._rediscover_delta_locked()
                retry_attempt = self._attempt_resolve_locked(
                    request=request,
                    reason="resolve:rediscover",
                    rediscover_modules=False,
                )
                if retry_attempt.resolved:
                    self._missing_cache.pop(cache_key, None)
                    return retry_attempt.value

                if retry_attempt.query_error is not None:
                    query_error = retry_attempt.query_error
                    self._mark_missing_cache_locked(cache_key)
                if retry_attempt.validation_error is not None:
                    validation_error = retry_attempt.validation_error

            return self._finalize_resolve_failure_locked(
                request=request,
                query_error=query_error,
                validation_error=validation_error,
            )

    def _attempt_resolve_locked(
        self,
        *,
        request: ResolveRequest,
        reason: str,
        rediscover_modules: bool,
    ) -> _ResolveAttempt:
        try:
            self._prepare_runtime_locked(
                reason=reason,
                implicit_init=True,
                source_sync="auto",
                rediscover_modules=rediscover_modules,
            )
            value = self._evaluate_request_locked(request)
            return _ResolveAttempt(resolved=True, value=value)
        except QueryMiss as exc:
            return _ResolveAttempt(resolved=False, query_error=exc)
        except (KeyError, IndexError, AttributeError) as exc:
            return _ResolveAttempt(resolved=False, query_error=QueryMiss(str(exc)))
        except SettingsValidationError as exc:
            return _ResolveAttempt(resolved=False, validation_error=exc)

    def _mark_missing_cache_locked(self, cache_key: str) -> None:
        self._missing_cache[cache_key] = (
            get_settings_registry().version(),
            self._module_fingerprint,
        )

    def _finalize_resolve_failure_locked(
        self,
        *,
        request: ResolveRequest,
        query_error: QueryMiss | None,
        validation_error: SettingsValidationError | None,
    ) -> Any:
        if request.has_default:
            if validation_error is not None:
                self._warn_validation_fallback_once_locked(request, validation_error)
            return resolve_default(request)

        if validation_error is not None:
            raise validation_error
        if query_error is not None:
            raise SettingsResolveError(str(query_error)) from query_error
        raise SettingsResolveError("settings value could not be resolved")

    def _evaluate_request_locked(self, request: ResolveRequest) -> Any:
        settings = self._active_settings_locked()
        source = self._active_source_locked()

        return evaluate_request(
            request=request,
            settings=settings,
            sections=get_settings_registry().sections(),
            case_sensitive=source.case_sensitive,
        )

    def _should_skip_rediscovery_locked(self, cache_key: str) -> bool:
        marker = self._missing_cache.get(cache_key)
        if marker is None:
            return False
        current = (get_settings_registry().version(), self._module_fingerprint)
        return marker == current

    def _warn_validation_fallback_once_locked(
        self,
        request: ResolveRequest,
        error: SettingsValidationError,
    ) -> None:
        source = self._active_source_locked()
        warning_key = f"{source.settings_path}|{request.cache_key()}|{error.__class__.__name__}|{str(error)}"
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

    def _active_source_locked(self) -> SettingsSource:
        source = self._source
        if source is None:
            raise RuntimeError("settings source is not initialized")
        return source

    def _active_live_config_locked(self) -> LiveConfigStore:
        live_config = self._live_config
        if live_config is None:
            raise RuntimeError("live config store is not initialized")
        return live_config

    def _active_settings_locked(self) -> BaseModel:
        settings = self._settings
        if settings is None:
            raise RuntimeError("settings snapshot is not initialized")
        return settings

    def _active_schema_locked(self) -> BuiltSchema:
        schema = self._schema
        if schema is None:
            raise RuntimeError("settings schema is not initialized")
        return schema

    def _converge_controls_locked(self) -> bool:
        source = self._active_source_locked()
        self._active_live_config_locked()
        changed = False
        visited_paths: set[Path] = {source.settings_path}

        while True:
            control_snapshot = self._materialize_control_snapshot_locked()
            next_source = self._build_source_from_controls_locked(control_snapshot)
            step_changed, should_continue = self._apply_control_source_step_locked(
                next_source=next_source,
                visited_paths=visited_paths,
            )
            changed = changed or step_changed
            if not should_continue:
                return changed

    def _apply_control_source_step_locked(
        self,
        *,
        next_source: SettingsSource,
        visited_paths: set[Path],
    ) -> tuple[bool, bool]:
        current_source = self._active_source_locked()

        if next_source.settings_path != current_source.settings_path:
            if next_source.settings_path in visited_paths:
                logger.warning("settings path control cycle detected; keeping path=%s", current_source.settings_path)
                stabilized = replace(next_source, settings_path=current_source.settings_path)
                changed = stabilized != current_source
                self._source = stabilized
                return changed, False

            visited_paths.add(next_source.settings_path)
            self._source = next_source
            self._sync_selected_sources_locked(
                force=True,
                selector=lambda spec: spec.sync_on_path_switch,
            )
            return True, True

        if next_source != current_source:
            self._source = next_source
            return True, False

        return False, False

    def _maybe_auto_reload_locked(self) -> bool:
        mode = self._active_source_locked().reload_mode
        if mode == "off":
            return False

        if mode == "always":
            self._sync_reload_sources_locked(force=True)
            return True

        return self._sync_reload_sources_locked(force=False)

    def _reload_live_sources_locked(self) -> bool:
        self._active_source_locked()

        source_payloads: dict[SourceName, dict[str, Any]] = {}
        source_states: dict[SourceName, _SOURCE_STATE] = {}
        for source in source_order():
            payload, state = self._read_source_snapshot_locked(source)
            source_payloads[source] = payload
            source_states[source] = state

        if self._live_config is None:
            self._live_config = LiveConfigStore()

        changed = self._active_live_config_locked().reset(source_payloads)
        self._source_states = source_states
        return changed

    def _sync_reload_sources_locked(self, *, force: bool) -> bool:
        self._active_source_locked()
        self._active_live_config_locked()
        return self._sync_selected_sources_locked(
            force=force,
            selector=lambda spec: spec.sync_on_reload,
        )

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
        live_config = self._active_live_config_locked()
        payload, state = self._read_source_snapshot_locked(source)
        if not force and state is not None:
            previous_state = self._source_states.get(source)
            if previous_state == state:
                return False

        changed = live_config.replace_source(source, payload)
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
        path = self._active_source_locked().settings_path
        return load_yaml_settings(path), file_state(path)

    def _read_dotenv_snapshot_locked(self) -> tuple[dict[str, Any], _SOURCE_STATE]:
        start_dir = self._active_source_locked().settings_path.parent
        mapping = load_dotenv_snapshot_raw(start_dir=start_dir)
        return mapping, file_state(find_dotenv_path(start_dir))

    def _read_env_snapshot_locked(self) -> tuple[dict[str, Any], _SOURCE_STATE]:
        return load_env_snapshot_raw(), None

    def _build_source_from_controls_locked(self, control_snapshot: Mapping[str, Any]) -> SettingsSource:
        control = read_control_model(control_snapshot)
        return self._build_settings_source_from_control_locked(
            control=control,
            explicit_settings_path=None,
            explicit_env_prefix=None,
            fallback_settings_path=self._active_source_locked().settings_path,
        )

    def _materialize_control_snapshot_locked(self) -> dict[str, Any]:
        return materialize_control_snapshot(self._active_live_config_locked().entries())

    def _materialize_effective_snapshot_locked(self) -> dict[str, Any]:
        source = self._active_source_locked()
        live_config = self._active_live_config_locked()
        return materialize_effective_snapshot(
            live_config.entries(),
            env_prefix=source.env_prefix,
            case_sensitive=source.case_sensitive,
        )

    def _maybe_rediscover_modules_locked(self) -> bool:
        current_snapshot = snapshot_imported_modules()
        if current_snapshot == self._module_snapshot:
            return False

        self._rediscover_delta_locked(current_snapshot=current_snapshot)
        return True

    def _refresh_runtime_locked(self, *, reason: str, force: bool = False) -> None:
        source = self._active_source_locked()
        live_config = self._active_live_config_locked()
        refresh_plan = self._build_refresh_plan_locked(
            force=force,
            live_config=live_config,
        )
        if not refresh_plan.should_refresh:
            return

        schema = self._ensure_schema_locked(refresh_plan=refresh_plan)
        self._settings = self._validate_effective_snapshot_locked(
            schema=schema,
            case_sensitive=source.case_sensitive,
        )

        logger.info(
            "settings refreshed reason=%s registry_version=%s live_version=%s",
            reason,
            refresh_plan.registry_version,
            refresh_plan.live_version,
        )
        self._snapshot_live_version = refresh_plan.live_version

    def _build_refresh_plan_locked(
        self,
        *,
        force: bool,
        live_config: LiveConfigStore,
    ) -> _RefreshPlan:
        registry_version = get_settings_registry().version()
        schema_outdated = self._schema is None or registry_version != self._registry_version
        live_version = live_config.version()
        live_outdated = live_version != self._snapshot_live_version
        settings_missing = self._settings is None
        should_refresh = force or schema_outdated or live_outdated or settings_missing
        return _RefreshPlan(
            should_refresh=should_refresh,
            registry_version=registry_version,
            live_version=live_version,
            schema_outdated=schema_outdated,
        )

    def _ensure_schema_locked(self, *, refresh_plan: _RefreshPlan) -> BuiltSchema:
        if refresh_plan.schema_outdated:
            self._schema = build_root_settings_model(get_settings_registry().sections())
            self._registry_version = refresh_plan.registry_version
        return self._active_schema_locked()

    def _validate_effective_snapshot_locked(
        self,
        *,
        schema: BuiltSchema,
        case_sensitive: bool,
    ) -> BaseModel:
        raw = self._materialize_effective_snapshot_locked()
        projected = project_snapshot_for_validation(
            raw,
            root_model=schema.root_model,
            case_sensitive=case_sensitive,
        )
        try:
            return schema.root_model.model_validate(projected)
        except ValidationError as exc:
            raise SettingsValidationError(str(exc)) from exc

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
        control = read_control_model(controls)
        return self._build_settings_source_from_control_locked(
            control=control,
            explicit_settings_path=normalize_override_path(settings_path),
            explicit_env_prefix=env_prefix,
            fallback_settings_path=None,
        )

    def _build_settings_source_from_control_locked(
        self,
        *,
        control: ControlModel,
        explicit_settings_path: Path | None,
        explicit_env_prefix: str | None,
        fallback_settings_path: Path | None,
    ) -> SettingsSource:
        resolved_path = self._resolve_settings_path_from_control(
            explicit_settings_path=explicit_settings_path,
            control_settings_path=control.settings.path,
            control_base_dir=control.base_dir,
            fallback_settings_path=fallback_settings_path,
        )
        resolved_env_prefix = resolve_env_prefix(
            explicit_env_prefix if explicit_env_prefix is not None else control.settings.env_prefix
        )
        return SettingsSource(
            settings_path=resolved_path,
            env_prefix=resolved_env_prefix,
            case_sensitive=control.settings.case_sensitive,
            reload_mode=control.settings.reload,
        )

    @staticmethod
    def _resolve_settings_path_from_control(
        *,
        explicit_settings_path: Path | None,
        control_settings_path: str | None,
        control_base_dir: str | None,
        fallback_settings_path: Path | None,
    ) -> Path:
        if explicit_settings_path is not None:
            return explicit_settings_path

        from_control = normalize_override_path(control_settings_path)
        if from_control is not None:
            return from_control

        from_base_dir = normalize_override_path(control_base_dir, as_directory=True)
        if from_base_dir is not None:
            return (from_base_dir / "settings.yaml").resolve()

        if fallback_settings_path is not None:
            return fallback_settings_path
        return (Path.cwd().resolve() / "settings.yaml").resolve()

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
