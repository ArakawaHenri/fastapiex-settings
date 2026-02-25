from __future__ import annotations

from typing import Any

import pytest

from fastapiex.settings.declarations import BaseSettings
from fastapiex.settings.exceptions import SettingsResolveError
from fastapiex.settings.query_engine import (
    QueryMiss,
    ResolveRequest,
    evaluate_request,
    resolve_default,
    resolve_type_target,
)
from fastapiex.settings.registry import SectionKind, SettingsSection


def _section(
    *,
    path: tuple[str, ...],
    model: type[BaseSettings],
    kind: SectionKind,
) -> SettingsSection:
    return SettingsSection(
        raw_path=".".join(path),
        path=path,
        model=model,
        kind=kind,
        owner_module=__name__,
        owner_identity=1,
    )


def test_query_engine_evaluates_target_and_field() -> None:
    class AppSettings(BaseSettings):
        name: str

    class RootSettings(BaseSettings):
        app: AppSettings

    root = RootSettings(app=AppSettings(name="demo"))
    request = ResolveRequest(
        api="settings",
        target="app",
        field="name",
        default=object(),
        has_default=False,
    )

    value = evaluate_request(
        request=request,
        settings=root,
        sections=[_section(path=("app",), model=AppSettings, kind="object")],
        case_sensitive=False,
    )

    assert value == "demo"


def test_query_engine_rejects_non_mapping_for_map_api() -> None:
    class AppSettings(BaseSettings):
        name: str

    class RootSettings(BaseSettings):
        app: AppSettings

    root = RootSettings(app=AppSettings(name="demo"))
    request = ResolveRequest(
        api="map",
        target="app",
        field=None,
        default=object(),
        has_default=False,
    )

    with pytest.raises(QueryMiss, match="not a mapping"):
        evaluate_request(
            request=request,
            settings=root,
            sections=[_section(path=("app",), model=AppSettings, kind="object")],
            case_sensitive=False,
        )


def test_query_engine_requires_unique_type_target() -> None:
    class SharedMarker:
        pass

    class AppSettings(BaseSettings, SharedMarker):
        value: int

    class WorkerSettings(BaseSettings, SharedMarker):
        value: int

    sections = [
        _section(path=("app",), model=AppSettings, kind="object"),
        _section(path=("worker",), model=WorkerSettings, kind="object"),
    ]

    with pytest.raises(QueryMiss, match="matched multiple sections"):
        resolve_type_target(target_type=SharedMarker, sections=sections)


def test_query_engine_default_for_map_must_be_mapping() -> None:
    request = ResolveRequest(
        api="map",
        target=None,
        field=None,
        default=[],
        has_default=True,
    )

    with pytest.raises(SettingsResolveError, match="must be a mapping"):
        resolve_default(request)

    mapping_default: dict[str, Any] = {"ok": 1}
    request_ok = ResolveRequest(
        api="map",
        target=None,
        field=None,
        default=mapping_default,
        has_default=True,
    )
    assert resolve_default(request_ok) is mapping_default
