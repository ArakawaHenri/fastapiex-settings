from __future__ import annotations

from pydantic import BaseModel

from .pathing import to_snake_case


def resolve_declared_path(model: type[BaseModel], explicit: str | None) -> str:
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()

    local_declared = resolve_local_declared_section(model)
    if local_declared is not None:
        return local_declared

    return to_snake_case(model.__name__)


def resolve_local_declared_section(model: type[BaseModel]) -> str | None:
    declared = model.__dict__.get("__section__")
    if not isinstance(declared, str):
        return None

    value = declared.strip()
    return value or None


__all__ = [
    "resolve_declared_path",
    "resolve_local_declared_section",
]
