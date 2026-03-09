from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from .builtin_sources import builtin_source_specs
from .context import ConfigContext, build_config_context
from .controls import build_env_controls_snapshot, read_control_model
from .exceptions import SettingsResolveError, SettingsValidationError
from .projection import materialize_effective_snapshot, project_snapshot_for_validation
from .query import QueryMiss, ResolveRequest, evaluate_request, resolve_default
from .refresh_engine import (
    CandidateRuntime,
    build_candidate_runtime,
    build_entries_from_runtime_snapshots,
    validate_final_source_bindings,
)
from .registry import get_settings_registry
from .runtime_state import RuntimeInspection, RuntimeState, inspect_runtime_state
from .schema import BuiltSchema, build_root_settings_model
from .source_contract import SourceRegistry, SourceSpec
from .types import ReloadMode, SourceName, SourceSyncMode

logger = logging.getLogger(__name__)

_NO_DEFAULT = object()


class SettingsManager:
    def __init__(self) -> None:
        self._runtime: RuntimeState | None = None
        self._schema: BuiltSchema | None = None
        self._registry_version: int = -1
        self._lock = threading.RLock()
        self._sources = SourceRegistry()
        self._missing_cache: dict[str, int] = {}
        self._validation_fallback_warnings: set[str] = set()
        self._auto_refresh_failure_warnings: set[str] = set()

        self._register_builtin_sources()

    def _register_builtin_sources(self) -> None:
        for spec in builtin_source_specs():
            self._sources.register(spec)

    def register_source(self, spec: SourceSpec) -> None:
        with self._lock:
            self._sources.register(spec)

    def unregister_source(self, name: SourceName) -> None:
        with self._lock:
            self._sources.unregister(name)

    def get_source(self, name: SourceName) -> SourceSpec | None:
        with self._lock:
            return self._sources.get(name)

    def inspect_runtime(self) -> RuntimeInspection | None:
        with self._lock:
            return inspect_runtime_state(self._runtime)

    def init(self) -> BaseModel:
        context = self._resolve_context()

        with self._lock:
            runtime = self._runtime
            if runtime is not None and runtime.context != context:
                raise RuntimeError(
                    "settings source is already initialized with a different source "
                    f"(current={runtime.context}, requested={context})"
                )

            current_snapshots = {} if runtime is None else runtime.snapshots
            candidate = self._build_candidate_locked(
                initial_context=context,
                current_snapshots=current_snapshots,
                current_last_rev=0 if runtime is None else runtime.last_rev,
                mode="full",
            )
            self._commit_candidate_locked(candidate=candidate, reason="init")
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
        sync_module_lifecycle: bool = True,
    ) -> None:
        self._ensure_runtime_locked(implicit=implicit_init)
        runtime = self._active_runtime_locked()
        sources_changed = runtime.sources_version != self._sources.version()

        candidate = CandidateRuntime(
            last_rev=runtime.last_rev,
            context=runtime.context,
            snapshots=runtime.snapshots,
            changed=False,
        )

        refresh_mode = "full" if sources_changed else source_sync
        if self._should_attempt_source_refresh(mode=refresh_mode, reload_mode=runtime.context.reload_mode):
            try:
                candidate = self._build_candidate_locked(
                    initial_context=runtime.context,
                    current_snapshots=runtime.snapshots,
                    current_last_rev=runtime.last_rev,
                    mode=refresh_mode,
                )
            except Exception as exc:
                if refresh_mode == "auto":
                    self._warn_auto_refresh_failure_locked(runtime.context, exc)
                else:
                    raise

        module_changed = self._sync_module_lifecycle_locked() if sync_module_lifecycle else False
        schema_outdated = self._is_schema_outdated_locked()
        should_commit = force_refresh or sources_changed or candidate.changed or module_changed or schema_outdated
        if not should_commit:
            return

        try:
            self._commit_candidate_locked(candidate=candidate, reason=reason)
        except Exception as exc:
            if refresh_mode == "auto":
                self._warn_auto_refresh_failure_locked(candidate.context, exc)
                return
            raise

    @staticmethod
    def _should_attempt_source_refresh(*, mode: SourceSyncMode, reload_mode: ReloadMode) -> bool:
        if mode == "none":
            return False
        if mode == "auto" and reload_mode == "off":
            return False
        return True

    def _resolve_request(self, request: ResolveRequest) -> Any:
        initial_attempt = self._attempt_resolve(
            request=request,
            reason="resolve:registered",
            sync_module_lifecycle=True,
        )
        if initial_attempt[0]:
            return initial_attempt[1]

        cache_key = request.cache_key()
        query_error = initial_attempt[2]
        validation_error = initial_attempt[3]

        if not self._should_skip_reconcile(cache_key):
            self._sync_module_lifecycle()
            retry_attempt = self._attempt_resolve(
                request=request,
                reason="resolve:reconcile",
                sync_module_lifecycle=False,
            )
            if retry_attempt[0]:
                self._missing_cache.pop(cache_key, None)
                return retry_attempt[1]

            if retry_attempt[2] is not None:
                query_error = retry_attempt[2]
                self._mark_missing_cache(cache_key)
            if retry_attempt[3] is not None:
                validation_error = retry_attempt[3]

        return self._finalize_resolve_failure(
            request=request,
            query_error=query_error,
            validation_error=validation_error,
        )

    def _attempt_resolve(
        self,
        *,
        request: ResolveRequest,
        reason: str,
        sync_module_lifecycle: bool,
    ) -> tuple[bool, Any | None, QueryMiss | None, SettingsValidationError | None]:
        try:
            with self._lock:
                self._prepare_runtime_locked(
                    reason=reason,
                    implicit_init=True,
                    source_sync="auto",
                    sync_module_lifecycle=sync_module_lifecycle,
                )
                value = self._evaluate_request_locked(request)
            return (True, value, None, None)
        except QueryMiss as exc:
            return (False, None, exc, None)
        except (KeyError, IndexError, AttributeError) as exc:
            return (False, None, QueryMiss(str(exc)), None)
        except SettingsValidationError as exc:
            return (False, None, None, exc)

    def _mark_missing_cache(self, cache_key: str) -> None:
        with self._lock:
            self._missing_cache[cache_key] = get_settings_registry().snapshot().version

    def _finalize_resolve_failure(
        self,
        *,
        request: ResolveRequest,
        query_error: QueryMiss | None,
        validation_error: SettingsValidationError | None,
    ) -> Any:
        if request.has_default:
            if validation_error is not None:
                with self._lock:
                    self._warn_validation_fallback_once_locked(request, validation_error)
            return resolve_default(request)

        if validation_error is not None:
            raise validation_error
        if query_error is not None:
            raise SettingsResolveError(str(query_error)) from query_error
        raise SettingsResolveError("settings value could not be resolved")

    def _evaluate_request_locked(self, request: ResolveRequest) -> Any:
        registry_snapshot = get_settings_registry().snapshot()
        settings = self._active_settings_locked()
        context = self._active_context_locked()
        return evaluate_request(
            request=request,
            settings=settings,
            sections=registry_snapshot.sections,
            case_sensitive=context.case_sensitive,
        )

    def _should_skip_reconcile(self, cache_key: str) -> bool:
        with self._lock:
            marker = self._missing_cache.get(cache_key)
            if marker is None:
                return False
            current = get_settings_registry().snapshot().version
            return marker == current

    def _warn_validation_fallback_once_locked(
        self,
        request: ResolveRequest,
        error: SettingsValidationError,
    ) -> None:
        runtime = self._runtime
        context_path = "<uninitialized>" if runtime is None else str(runtime.context.settings_path)
        warning_key = f"{context_path}|{request.cache_key()}|{error.__class__.__name__}|{str(error)}"
        if warning_key in self._validation_fallback_warnings:
            return

        self._validation_fallback_warnings.add(warning_key)
        logger.warning(
            "settings validation failed; falling back to default target=%r field=%r error=%s",
            request.target,
            request.field,
            error,
        )

    def _warn_auto_refresh_failure_locked(self, context: ConfigContext, error: Exception) -> None:
        warning_key = f"{context.settings_path}|{error.__class__.__name__}|{str(error)}"
        if warning_key in self._auto_refresh_failure_warnings:
            return
        self._auto_refresh_failure_warnings.add(warning_key)
        logger.warning(
            "auto settings refresh failed; keeping previous committed snapshot path=%s error=%s",
            context.settings_path,
            error,
        )

    def _ensure_runtime_locked(self, *, implicit: bool) -> None:
        if self._runtime is not None:
            return

        if not implicit:
            raise RuntimeError("settings are not initialized")

        context = self._resolve_context()
        candidate = self._build_candidate_locked(
            initial_context=context,
            current_snapshots={},
            current_last_rev=0,
            mode="full",
        )
        self._commit_candidate_locked(candidate=candidate, reason="implicit-init")
        logger.info("settings initialized implicitly context=%s", context)

    def _active_runtime_locked(self) -> RuntimeState:
        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("settings runtime is not initialized")
        return runtime

    def _active_context_locked(self) -> ConfigContext:
        return self._active_runtime_locked().context

    def _active_settings_locked(self) -> BaseModel:
        return self._active_runtime_locked().settings

    def _active_schema_locked(self) -> BuiltSchema:
        schema = self._schema
        if schema is None:
            raise RuntimeError("settings schema is not initialized")
        return schema

    def _sync_module_lifecycle(self) -> bool:
        with self._lock:
            return self._sync_module_lifecycle_locked()

    def _sync_module_lifecycle_locked(self) -> bool:
        changed = get_settings_registry().reconcile_runtime_modules()
        if changed:
            self._missing_cache.clear()
        return changed

    def _is_schema_outdated_locked(self) -> bool:
        return self._schema is None or get_settings_registry().snapshot().version != self._registry_version

    def _commit_candidate_locked(
        self,
        *,
        candidate: CandidateRuntime,
        reason: str,
    ) -> None:
        validate_final_source_bindings(
            context=candidate.context,
            snapshots=candidate.snapshots,
            sources=self._sources,
        )
        schema = self._ensure_schema_locked()
        settings = self._validate_snapshots_locked(
            context=candidate.context,
            snapshots=candidate.snapshots,
            schema=schema,
        )
        self._runtime = RuntimeState(
            sources_version=self._sources.version(),
            last_rev=candidate.last_rev,
            context=candidate.context,
            snapshots=candidate.snapshots,
            settings=settings,
        )
        logger.info(
            "settings refreshed reason=%s registry_version=%s path=%s",
            reason,
            self._registry_version,
            candidate.context.settings_path,
        )

    def _build_candidate_locked(
        self,
        *,
        initial_context: ConfigContext,
        current_snapshots: Mapping[str, Any],
        current_last_rev: int,
        mode: SourceSyncMode,
    ) -> CandidateRuntime:
        return build_candidate_runtime(
            initial_context=initial_context,
            current_snapshots=current_snapshots,
            current_last_rev=current_last_rev,
            mode=mode,
            sources=self._sources,
            build_context_from_controls=self._build_context_from_controls_locked,
            logger=logger,
        )

    def _validate_snapshots_locked(
        self,
        *,
        context: ConfigContext,
        snapshots: Mapping[str, Any],
        schema: BuiltSchema,
    ) -> BaseModel:
        raw = materialize_effective_snapshot(
            build_entries_from_runtime_snapshots(snapshots, sources=self._sources),
            env_prefix=context.env_prefix,
            case_sensitive=context.case_sensitive,
        )
        projected = project_snapshot_for_validation(
            raw,
            root_model=schema.root_model,
            case_sensitive=context.case_sensitive,
        )
        try:
            return schema.root_model.model_validate(projected)
        except ValidationError as exc:
            raise SettingsValidationError(str(exc)) from exc

    def _ensure_schema_locked(self) -> BuiltSchema:
        registry_snapshot = get_settings_registry().snapshot()
        if self._schema is None or registry_snapshot.version != self._registry_version:
            self._schema = build_root_settings_model(registry_snapshot.sections)
            self._registry_version = registry_snapshot.version
        return self._active_schema_locked()

    def _resolve_context(self) -> ConfigContext:
        controls = build_env_controls_snapshot()
        control = read_control_model(controls)
        return build_config_context(
            control=control,
            fallback_context=None,
        )

    def _build_context_from_controls_locked(
        self,
        control_snapshot: Mapping[str, Any],
        fallback_context: ConfigContext,
    ) -> ConfigContext:
        control = read_control_model(control_snapshot)
        return build_config_context(
            control=control,
            fallback_context=fallback_context,
        )


_GLOBAL_MANAGER = SettingsManager()


def get_settings_manager() -> SettingsManager:
    return _GLOBAL_MANAGER


def register_source(spec: SourceSpec) -> None:
    get_settings_manager().register_source(spec)


def get_source(name: SourceName) -> SourceSpec | None:
    return get_settings_manager().get_source(name)


def inspect_runtime() -> RuntimeInspection | None:
    return get_settings_manager().inspect_runtime()


def unregister_source(name: SourceName) -> None:
    get_settings_manager().unregister_source(name)
