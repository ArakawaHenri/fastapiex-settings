from __future__ import annotations

from typing import Literal, TypeAlias

ReloadMode = Literal["off", "on_change", "always"]
ResolveAPI = Literal["settings", "map"]
SectionKind = Literal["object", "map"]
SourceName = Literal["yaml", "dotenv", "env"]
SourceState: TypeAlias = tuple[str, bool, int, int] | None
SourceSyncMode = Literal["none", "auto", "reload", "full"]

__all__ = [
    "ReloadMode",
    "ResolveAPI",
    "SectionKind",
    "SourceName",
    "SourceState",
    "SourceSyncMode",
]
