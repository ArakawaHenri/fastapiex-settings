from __future__ import annotations

from typing import Literal, TypeAlias

ReloadMode = Literal["off", "on_change", "always"]
ResolveAPI = Literal["settings", "map"]
SectionKind = Literal["object", "map"]
ProjectionKind = Literal["mapping", "env_like"]
SourceName: TypeAlias = str
SettingsPathMode = Literal["explicit_file", "directory_anchor"]
SourceState: TypeAlias = tuple[str, bool, int, int] | None
SourceDescriptor: TypeAlias = object
SourceToken: TypeAlias = object | None
SourceSyncMode = Literal["none", "auto", "reload", "full"]

__all__ = [
    "ReloadMode",
    "ResolveAPI",
    "SectionKind",
    "ProjectionKind",
    "SettingsPathMode",
    "SourceDescriptor",
    "SourceName",
    "SourceState",
    "SourceSyncMode",
    "SourceToken",
]
