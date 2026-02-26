from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .loader import load_env_overrides


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


def snapshot_fingerprint(snapshot: dict[str, int]) -> int:
    return hash(frozenset(snapshot.items()))


def file_state(path: Path | None) -> tuple[str, bool, int, int]:
    if path is None:
        return ("", False, 0, 0)
    resolved = path.expanduser().resolve()
    try:
        stat_result = resolved.stat()
    except FileNotFoundError:
        return (str(resolved), False, 0, 0)
    return (str(resolved), True, stat_result.st_mtime_ns, stat_result.st_size)


__all__ = [
    "build_env_controls_snapshot",
    "file_state",
    "normalize_override_path",
    "snapshot_fingerprint",
]
