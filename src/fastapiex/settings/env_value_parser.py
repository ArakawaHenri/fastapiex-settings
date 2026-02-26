from __future__ import annotations

import json
import re
from typing import Any

from .constants import FALSE_TEXT_VALUES, NULL_TEXT_VALUES, TRUE_TEXT_VALUES

_INT_RE = re.compile(r"^[+-]?\d(?:_?\d)*$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:\d(?:_?\d)*)[eE][+-]?\d+$|"
    r"^[+-]?(?:(?:\d(?:_?\d)*)?\.\d(?:_?\d)*|\d(?:_?\d)*\.)(?:[eE][+-]?\d+)?$"
)


def parse_env_value(raw: str) -> Any:
    stripped = raw.strip()
    if stripped == "":
        return ""

    value = strip_matching_quotes(stripped)
    lowered = value.lower()
    if lowered in TRUE_TEXT_VALUES:
        return True
    if lowered in FALSE_TEXT_VALUES:
        return False
    if lowered in NULL_TEXT_VALUES:
        return None

    if (value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    try:
        normalized = value.replace("_", "")
        if _INT_RE.match(value):
            return int(normalized)
        if _FLOAT_RE.match(value):
            return float(normalized)
    except ValueError:
        return value
    return value


def parse_dotenv_value(raw: str) -> str:
    value = strip_inline_comment(raw.strip())
    return strip_matching_quotes(value)


def strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def strip_inline_comment(raw: str) -> str:
    quote: str | None = None
    escaped = False
    for idx, ch in enumerate(raw):
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch in {"'", '"'}:
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            continue
        if ch == "#" and quote is None:
            return raw[:idx].rstrip()
    return raw.rstrip()
