from __future__ import annotations

import re

from pydantic import BaseModel


def to_snake_case(name: str) -> str:
    stage1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    stage2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stage1)
    return stage2.lower()


def split_dotted_path(raw_path: str) -> tuple[str, ...]:
    parts = tuple(part.strip() for part in raw_path.split("."))
    if not parts or any(not part for part in parts):
        raise ValueError(f"invalid section path: {raw_path!r}")
    return parts


def resolve_section_name(model: type[BaseModel], explicit: str | None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    declared = getattr(model, "__section__", None)
    if isinstance(declared, str) and declared.strip():
        return declared.strip()

    return to_snake_case(model.__name__)
