from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .context import ConfigContext
from .types import ProjectionKind, SourceDescriptor, SourceName, SourceToken


@dataclass(frozen=True)
class SourcePolicy:
    auto_refresh: bool
    manual_refresh: bool
    follow_context: bool
    participates_in_controls: bool = True


@dataclass(frozen=True)
class SourceBinding:
    source: SourceName
    descriptor: SourceDescriptor


@dataclass(frozen=True)
class LoadedSource:
    token: SourceToken
    payload: dict[str, Any]


BindingBuilder = Callable[[ConfigContext], SourceBinding]
SourceProbe = Callable[[SourceBinding], SourceToken]
SourceLoader = Callable[[SourceBinding], LoadedSource]
BindingValidator = Callable[[ConfigContext, SourceBinding], None]


@dataclass(frozen=True)
class SourceSpec:
    name: SourceName
    priority: int
    projection_kind: ProjectionKind
    policy: SourcePolicy
    bind: BindingBuilder
    probe: SourceProbe
    load: SourceLoader
    validate_final_binding: BindingValidator | None = None


class SourceRegistry:
    def __init__(self) -> None:
        self._specs: dict[SourceName, SourceSpec] = {}
        self._version = 0

    def register(self, spec: SourceSpec) -> None:
        current = self._specs.get(spec.name)
        if current == spec:
            return
        self._specs[spec.name] = spec
        self._version += 1

    def unregister(self, name: SourceName) -> None:
        if name not in self._specs:
            return
        del self._specs[name]
        self._version += 1

    def get(self, name: SourceName) -> SourceSpec | None:
        return self._specs.get(name)

    def ordered(self) -> tuple[SourceSpec, ...]:
        return tuple(sorted(self._specs.values(), key=lambda spec: (spec.priority, spec.name)))

    def version(self) -> int:
        return self._version


__all__ = [
    "BindingBuilder",
    "BindingValidator",
    "LoadedSource",
    "SourceBinding",
    "SourceLoader",
    "SourcePolicy",
    "SourceProbe",
    "SourceRegistry",
    "SourceSpec",
]
