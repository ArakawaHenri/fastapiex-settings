from __future__ import annotations

from pathlib import Path

from .constants import DOTENV_FILENAME
from .context import ConfigContext
from .exceptions import SettingsValidationError
from .loader import (
    file_state,
    load_dotenv_file_snapshot,
    load_env_snapshot_raw,
    load_yaml_file_snapshot,
)
from .source_contract import LoadedSource, SourceBinding, SourcePolicy, SourceSpec


def builtin_source_specs() -> tuple[SourceSpec, ...]:
    return (
        SourceSpec(
            name="yaml",
            priority=1,
            projection_kind="mapping",
            policy=SourcePolicy(
                auto_refresh=True,
                manual_refresh=True,
                follow_context=True,
            ),
            bind=_bind_yaml,
            probe=_probe_file_binding,
            load=_load_yaml_source,
            validate_final_binding=_validate_yaml_explicit_file,
        ),
        SourceSpec(
            name="dotenv",
            priority=2,
            projection_kind="env_like",
            policy=SourcePolicy(
                auto_refresh=False,
                manual_refresh=False,
                follow_context=False,
            ),
            bind=_bind_dotenv,
            probe=_probe_file_binding,
            load=_load_dotenv_source,
        ),
        SourceSpec(
            name="env",
            priority=3,
            projection_kind="env_like",
            policy=SourcePolicy(
                auto_refresh=False,
                manual_refresh=False,
                follow_context=False,
            ),
            bind=_bind_env,
            probe=_probe_process_env,
            load=_load_env_source,
        ),
    )


def _bind_yaml(context: ConfigContext) -> SourceBinding:
    return SourceBinding(source="yaml", descriptor=context.settings_path)


def _bind_dotenv(context: ConfigContext) -> SourceBinding:
    return SourceBinding(source="dotenv", descriptor=(context.anchor_dir / DOTENV_FILENAME).resolve())


def _bind_env(_: ConfigContext) -> SourceBinding:
    return SourceBinding(source="env", descriptor="process-env")


def _probe_file_binding(binding: SourceBinding) -> object:
    descriptor = binding.descriptor
    if not isinstance(descriptor, Path):
        raise TypeError(f"{binding.source} descriptor must be a Path")
    return file_state(descriptor)


def _load_yaml_source(binding: SourceBinding) -> LoadedSource:
    descriptor = binding.descriptor
    if not isinstance(descriptor, Path):
        raise TypeError("yaml descriptor must be a Path")
    payload, token = load_yaml_file_snapshot(descriptor)
    return LoadedSource(token=token, payload=payload)


def _load_dotenv_source(binding: SourceBinding) -> LoadedSource:
    descriptor = binding.descriptor
    if not isinstance(descriptor, Path):
        raise TypeError("dotenv descriptor must be a Path")
    payload, token = load_dotenv_file_snapshot(descriptor)
    return LoadedSource(token=token, payload=payload)


def _probe_process_env(_: SourceBinding) -> object:
    return tuple(sorted(load_env_snapshot_raw().items()))


def _load_env_source(_: SourceBinding) -> LoadedSource:
    raw = load_env_snapshot_raw()
    return LoadedSource(token=tuple(sorted(raw.items())), payload=raw)


def _validate_yaml_explicit_file(context: ConfigContext, binding: SourceBinding) -> None:
    if context.path_mode != "explicit_file":
        return

    descriptor = binding.descriptor
    if not isinstance(descriptor, Path):
        raise SettingsValidationError(f"explicit settings file is missing: {context.settings_path}")

    path_state = file_state(descriptor)
    exists = False if path_state is None else bool(path_state[1])
    if not exists:
        raise SettingsValidationError(f"explicit settings file is missing: {context.settings_path}")


__all__ = [
    "builtin_source_specs",
]
