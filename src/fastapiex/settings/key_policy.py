from __future__ import annotations

from .control_model import CONTROL_ROOT


def is_control_root(segment: str) -> bool:
    return segment.casefold() == CONTROL_ROOT.casefold()


def startswith_prefix(value: str, prefix: str, *, case_sensitive: bool) -> bool:
    if case_sensitive:
        return value.startswith(prefix)
    return value.casefold().startswith(prefix.casefold())

