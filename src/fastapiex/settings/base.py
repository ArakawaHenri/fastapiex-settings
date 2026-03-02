from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel


class BaseSettings(BaseModel):
    """Base class for settings declaration models."""

    __section__: ClassVar[str]
