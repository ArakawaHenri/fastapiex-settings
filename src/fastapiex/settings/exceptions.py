from __future__ import annotations


class SettingsError(RuntimeError):
    """Base settings error."""


class SettingsRegistrationError(SettingsError):
    """Raised when settings declarations are invalid or conflicting."""


class SettingsValidationError(SettingsError):
    """Raised when loaded raw settings fail schema validation."""


class SettingsResolveError(SettingsError):
    """Raised when a settings read cannot be resolved and no default is provided."""
