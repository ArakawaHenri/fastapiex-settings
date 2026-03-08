from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from .context import ConfigContext
from .source_contract import SourceBinding
from .types import SourceName, SourceToken


@dataclass(frozen=True)
class SourceSnapshot:
    source: SourceName
    rev: int
    binding: SourceBinding
    token: SourceToken
    payload: dict[str, Any]


@dataclass(frozen=True)
class RuntimeState:
    sources_version: int
    last_rev: int
    context: ConfigContext
    snapshots: dict[SourceName, SourceSnapshot]
    settings: BaseModel


@dataclass(frozen=True)
class SnapshotInspection:
    source: SourceName
    rev: int
    binding: SourceBinding
    token: SourceToken
    payload: dict[str, Any]


@dataclass(frozen=True)
class RuntimeInspection:
    sources_version: int
    last_rev: int
    context: ConfigContext
    snapshots: tuple[SnapshotInspection, ...]


def inspect_runtime_state(runtime: RuntimeState | None) -> RuntimeInspection | None:
    if runtime is None:
        return None

    rows = tuple(
        SnapshotInspection(
            source=snapshot.source,
            rev=snapshot.rev,
            binding=snapshot.binding,
            token=deepcopy(snapshot.token),
            payload=deepcopy(snapshot.payload),
        )
        for snapshot in sorted(runtime.snapshots.values(), key=lambda item: item.source)
    )
    return RuntimeInspection(
        sources_version=runtime.sources_version,
        last_rev=runtime.last_rev,
        context=runtime.context,
        snapshots=rows,
    )


__all__ = [
    "ConfigContext",
    "inspect_runtime_state",
    "RuntimeInspection",
    "RuntimeState",
    "SnapshotInspection",
    "SourceSnapshot",
]
