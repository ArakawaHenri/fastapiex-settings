from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from .pathing import resolve_section_name, split_dotted_path
from .types import SectionKind


@dataclass(frozen=True, slots=True)
class SectionSpec:
    model: type[BaseModel]
    kind: SectionKind
    raw_path: str
    path: tuple[str, ...]

    @property
    def root(self) -> str:
        return self.path[0]

    @property
    def path_text(self) -> str:
        return ".".join(self.path)

    def path_with(self, *suffix: str) -> tuple[str, ...]:
        return (*self.path, *_normalize_suffix(suffix))

    def dotted(self, *suffix: str) -> str:
        return ".".join(self.path_with(*suffix))

    def env_key(self, *suffix: str, separator: str) -> str:
        return separator.join(part.upper() for part in self.path_with(*suffix))


def describe_section(
    model: type[BaseModel],
    *,
    kind: SectionKind,
    explicit: str | None = None,
) -> SectionSpec:
    raw_path = resolve_section_name(model, explicit)
    return SectionSpec(
        model=model,
        kind=kind,
        raw_path=raw_path,
        path=split_dotted_path(raw_path),
    )


def _normalize_suffix(suffix: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for part in suffix:
        normalized.extend(split_dotted_path(part))
    return tuple(normalized)
