from __future__ import annotations

from typing import Any

from pydantic import Field

from fastapiex.settings.declarations import BaseSettings
from fastapiex.settings.snapshot_projection import project_snapshot_for_validation


def test_snapshot_projection_projects_model_fields_case_insensitively() -> None:
    class AppSettings(BaseSettings):
        name: str

    class RootSettings(BaseSettings):
        app: AppSettings = Field(default_factory=lambda: AppSettings(name="default"))
        fastapiex: dict[str, Any] = Field(default_factory=dict)

    raw = {
        "APP": {"NAME": "demo"},
        "FastAPIEx": {"Settings": {"Reload": "always"}},
    }

    projected = project_snapshot_for_validation(
        raw,
        root_model=RootSettings,
        case_sensitive=False,
    )

    assert projected["app"]["name"] == "demo"
    assert projected["fastapiex"]["settings"]["reload"] == "always"


def test_snapshot_projection_projects_map_values_to_declared_model() -> None:
    class ServiceSettings(BaseSettings):
        host: str

    class RootSettings(BaseSettings):
        services: dict[str, ServiceSettings] = Field(default_factory=dict)
        fastapiex: dict[str, Any] = Field(default_factory=dict)

    raw = {"services": {"api": {"HOST": "127.0.0.1"}}}

    projected = project_snapshot_for_validation(
        raw,
        root_model=RootSettings,
        case_sensitive=False,
    )

    assert projected["services"]["api"]["host"] == "127.0.0.1"
