from __future__ import annotations

from .types import ReloadMode, SourceName

# control defaults
DEFAULT_ENV_PREFIX = ""
DEFAULT_CASE_SENSITIVE = False
DEFAULT_RELOAD_MODE: ReloadMode = "off"

# env/runtime naming
ENV_KEY_SEPARATOR = "__"
DOTENV_FILENAME = ".env"
DOTENV_EXPORT_PREFIX = "export "
SETTINGS_FILENAME = "settings.yaml"

# scalar tokens
TRUE_TEXT_VALUES = frozenset({"1", "true", "yes", "on"})
FALSE_TEXT_VALUES = frozenset({"0", "false", "no", "off"})
NULL_TEXT_VALUES = frozenset({"null", "none"})

# reload-mode normalization
RELOAD_MODE_ALWAYS_TOKENS = frozenset({"always"})
RELOAD_MODE_ON_CHANGE_TOKENS = frozenset({"on_change", "on-change", "onchange", "true", "1", "yes"})
RELOAD_MODE_OFF_TOKENS = frozenset({"off", "false", "0", "no"})

# source priority and order
SOURCE_PRIORITY: dict[SourceName, int] = {
    "yaml": 1,
    "dotenv": 2,
    "env": 3,
}
SOURCE_ORDER: tuple[SourceName, ...] = (
    "yaml",
    "dotenv",
    "env",
)

__all__ = [
    "DEFAULT_ENV_PREFIX",
    "DEFAULT_CASE_SENSITIVE",
    "DEFAULT_RELOAD_MODE",
    "DOTENV_EXPORT_PREFIX",
    "DOTENV_FILENAME",
    "ENV_KEY_SEPARATOR",
    "FALSE_TEXT_VALUES",
    "NULL_TEXT_VALUES",
    "RELOAD_MODE_ALWAYS_TOKENS",
    "RELOAD_MODE_OFF_TOKENS",
    "RELOAD_MODE_ON_CHANGE_TOKENS",
    "SETTINGS_FILENAME",
    "SOURCE_ORDER",
    "SOURCE_PRIORITY",
    "TRUE_TEXT_VALUES",
]
