from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .constants import SETTINGS_FILENAME
from .control_contract import ControlModel
from .loader import resolve_env_prefix
from .types import ReloadMode, SettingsPathMode


@dataclass(frozen=True)
class ResolvedSettingsTarget:
    settings_path: Path
    anchor_dir: Path
    path_mode: SettingsPathMode


@dataclass(frozen=True)
class ConfigContext:
    settings_path: Path
    anchor_dir: Path
    path_mode: SettingsPathMode
    env_prefix: str
    case_sensitive: bool
    reload_mode: ReloadMode

    def cycle_key(self) -> tuple[SettingsPathMode, Path]:
        return (self.path_mode, self.settings_path)


def resolve_settings_target(
    raw: str | Path | None,
    *,
    as_directory: bool = False,
) -> ResolvedSettingsTarget | None:
    if raw is None:
        return None

    if isinstance(raw, Path):
        path = raw.expanduser()
    else:
        text = raw.strip()
        if not text:
            return None
        path = Path(text).expanduser()

    if as_directory:
        anchor_dir = path.resolve()
        return ResolvedSettingsTarget(
            settings_path=(anchor_dir / SETTINGS_FILENAME).resolve(),
            anchor_dir=anchor_dir,
            path_mode="directory_anchor",
        )

    if path.suffix.lower() in {".yaml", ".yml"}:
        resolved = path.resolve()
        return ResolvedSettingsTarget(
            settings_path=resolved,
            anchor_dir=resolved.parent,
            path_mode="explicit_file",
        )

    anchor_dir = path.resolve()
    return ResolvedSettingsTarget(
        settings_path=(anchor_dir / SETTINGS_FILENAME).resolve(),
        anchor_dir=anchor_dir,
        path_mode="directory_anchor",
    )


def build_config_context(
    *,
    control: ControlModel,
    explicit_settings_target: ResolvedSettingsTarget | None,
    explicit_env_prefix: str | None,
    fallback_context: ConfigContext | None,
) -> ConfigContext:
    resolved_target = _resolve_settings_target_from_control(
        explicit_settings_target=explicit_settings_target,
        control_settings_path=control.settings.path,
        control_base_dir=control.base_dir,
        fallback_context=fallback_context,
    )
    resolved_env_prefix = resolve_env_prefix(
        explicit_env_prefix if explicit_env_prefix is not None else control.settings.env_prefix
    )
    return ConfigContext(
        settings_path=resolved_target.settings_path,
        anchor_dir=resolved_target.anchor_dir,
        path_mode=resolved_target.path_mode,
        env_prefix=resolved_env_prefix,
        case_sensitive=control.settings.case_sensitive,
        reload_mode=control.settings.reload,
    )


def _resolve_settings_target_from_control(
    *,
    explicit_settings_target: ResolvedSettingsTarget | None,
    control_settings_path: str | None,
    control_base_dir: str | None,
    fallback_context: ConfigContext | None,
) -> ResolvedSettingsTarget:
    if explicit_settings_target is not None:
        return explicit_settings_target

    from_control = resolve_settings_target(control_settings_path)
    if from_control is not None:
        return from_control

    from_base_dir = resolve_settings_target(control_base_dir, as_directory=True)
    if from_base_dir is not None:
        return from_base_dir

    if fallback_context is not None:
        return ResolvedSettingsTarget(
            settings_path=fallback_context.settings_path,
            anchor_dir=fallback_context.anchor_dir,
            path_mode=fallback_context.path_mode,
        )

    default_target = resolve_settings_target(Path.cwd(), as_directory=True)
    assert default_target is not None
    return default_target


__all__ = [
    "build_config_context",
    "ConfigContext",
    "ResolvedSettingsTarget",
    "resolve_settings_target",
]
