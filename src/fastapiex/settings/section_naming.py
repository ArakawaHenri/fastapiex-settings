from __future__ import annotations

from pydantic import BaseModel

from .section_path import to_snake_case


def resolve_section_name(model: type[BaseModel], explicit: str | None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    declared = getattr(model, "__section__", None)
    if isinstance(declared, str) and declared.strip():
        return declared.strip()

    return to_snake_case(model.__name__)
