from __future__ import annotations

import re

from .errors import SettingsRegistrationError


def to_snake_case(name: str) -> str:
    stage1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    stage2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stage1)
    return stage2.lower()


def split_dotted_path(raw_path: str) -> tuple[str, ...]:
    parts = [part.strip() for part in raw_path.split(".")]
    if not parts or any(not part for part in parts):
        raise SettingsRegistrationError(f"invalid section path: {raw_path!r}")
    return tuple(parts)
