from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .loader import load_env_overrides
from .runtime_options import RuntimeOptions, parse_case_sensitive_mode, parse_reload_mode

SETTINGS_PATH_KEYS = ("fastapiex", "settings", "path")
BASE_DIR_KEYS = ("fastapiex", "base_dir")
ENV_PREFIX_KEYS = ("fastapiex", "settings", "env_prefix")
CASE_SENSITIVE_KEYS = ("fastapiex", "settings", "case_sensitive")
RELOAD_KEYS = ("fastapiex", "settings", "reload")


def normalize_override_path(raw: str | Path | None, *, as_directory: bool = False) -> Path | None:
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
        return path.resolve()

    if path.suffix.lower() in {".yaml", ".yml"}:
        return path.resolve()

    return (path / "settings.yaml").resolve()


def build_env_controls_snapshot() -> Mapping[Any, Any]:
    return load_env_overrides(prefix="", case_sensitive=False)


def runtime_options_from_controls(controls: Mapping[Any, Any]) -> RuntimeOptions:
    case_sensitive_raw = read_nested_value(controls, CASE_SENSITIVE_KEYS)
    reload_raw = read_nested_value(controls, RELOAD_KEYS)
    return RuntimeOptions(
        case_sensitive=parse_case_sensitive_mode(case_sensitive_raw, default=False),
        reload_mode=parse_reload_mode(reload_raw, default="off"),
    )


def read_nested_value(mapping: Mapping[Any, Any], keys: tuple[str, ...]) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        matched = _find_mapping_key(current, key)
        if matched is None:
            return None
        current = current[matched]
    return current


def read_nested_str(mapping: Mapping[Any, Any], keys: tuple[str, ...]) -> str | None:
    current = read_nested_value(mapping, keys)

    if not isinstance(current, str):
        return None
    stripped = current.strip()
    return stripped or None


def snapshot_fingerprint(snapshot: dict[str, int]) -> int:
    return hash(tuple(sorted(snapshot.items())))


def file_state(path: Path | None) -> tuple[str, bool, int, int]:
    if path is None:
        return ("", False, 0, 0)
    resolved = path.expanduser().resolve()
    try:
        stat_result = resolved.stat()
    except FileNotFoundError:
        return (str(resolved), False, 0, 0)
    return (str(resolved), True, stat_result.st_mtime_ns, stat_result.st_size)


def _find_mapping_key(mapping: Mapping[Any, Any], expected: str) -> Any:
    lowered = expected.lower()
    for key in mapping.keys():
        if isinstance(key, str) and key.lower() == lowered:
            return key
    return None


__all__ = [
    "BASE_DIR_KEYS",
    "ENV_PREFIX_KEYS",
    "SETTINGS_PATH_KEYS",
    "build_env_controls_snapshot",
    "file_state",
    "normalize_override_path",
    "read_nested_str",
    "runtime_options_from_controls",
    "snapshot_fingerprint",
]
