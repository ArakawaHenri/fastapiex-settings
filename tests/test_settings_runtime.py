from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path

import pytest
from pydantic import Field

from fastapiex.settings import (
    BaseSettings,
    GetSettings,
    GetSettingsMap,
    Settings,
    SettingsMap,
    exceptions,
    init_settings,
    reload_settings,
)
from fastapiex.settings import manager as manager_module
from fastapiex.settings import registry as registry_module
from fastapiex.settings.manager import get_settings_manager

SettingsRegistrationError = exceptions.SettingsRegistrationError
SettingsResolveError = exceptions.SettingsResolveError

DYNAMIC_MODULE = "tests.dynamic_settings_runtime"


@pytest.fixture(autouse=True)
def _reset_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "_GLOBAL_MANAGER", manager_module.SettingsManager())
    monkeypatch.setattr(registry_module, "_GLOBAL_REGISTRY", registry_module.SettingsRegistry())
    sys.modules.pop(DYNAMIC_MODULE, None)

    for key in list(os.environ):
        if key.startswith("FASTAPIEX__") or key.startswith("TEST__"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("FASTAPIEX__SETTINGS__ENV_PREFIX", "TEST__")


def test_nested_sections_are_composed(tmp_path: Path) -> None:
    @Settings("father")
    class FatherSettings(BaseSettings):
        a: int = Field(default=1, ge=1)

    @Settings("father.son")
    class SonSettings(BaseSettings):
        a: int = Field(default=2, ge=1)

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("father:\n  a: 7\n  son:\n    a: 9\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target=FatherSettings, field="a") == 7
    assert GetSettings(target=SonSettings, field="a") == 9
    assert GetSettings(target="father.son", field="a") == 9


def test_settingsmap_and_settings_read_same_map_section(tmp_path: Path) -> None:
    @SettingsMap("services")
    class ServiceSettings(BaseSettings):
        host: str
        port: int

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "services:\n  api:\n    host: 127.0.0.1\n    port: 8000\n  admin:\n    host: 127.0.0.2\n    port: 9000\n",
        encoding="utf-8",
    )
    init_settings(settings_path=settings_file)

    services = GetSettingsMap(target=ServiceSettings)
    assert services["api"].host == "127.0.0.1"

    assert GetSettings(target="services.api", field="host") == "127.0.0.1"
    assert GetSettings(target=ServiceSettings, field="api.host") == "127.0.0.1"
    same_services = GetSettings(target=ServiceSettings)
    assert isinstance(same_services, dict)
    assert same_services["admin"].host == "127.0.0.2"


def test_settings_singleton_map_resolves_to_mapping_without_special_unwrap(tmp_path: Path) -> None:
    @SettingsMap("services")
    class ServiceSettings(BaseSettings):
        host: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("services:\n  api:\n    host: localhost\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    services = GetSettings(target=ServiceSettings)
    assert isinstance(services, dict)
    assert services["api"].host == "localhost"

    with pytest.raises(SettingsResolveError):
        GetSettings(target=ServiceSettings, field="host")


def test_target_none_with_default_returns_default_as_is_even_with_field() -> None:
    assert GetSettings(target=None, field="x.y", default={"x": {"y": 3}}) == {"x": {"y": 3}}
    assert GetSettingsMap(target=None, default={"k": 1})["k"] == 1


def test_target_none_without_default_raises() -> None:
    with pytest.raises(SettingsResolveError):
        GetSettings(target=None, field="x.y")


def test_declaration_decorators_reject_invalid_arguments() -> None:
    class Plain:
        pass

    with pytest.raises(TypeError):
        Settings(target="app")  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        SettingsMap(target="app")  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="dotted path string, model class, or no argument"):
        Settings(123)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="BaseModel subclasses"):
        Settings(Plain)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="dotted path string, model class, or no argument"):
        SettingsMap(123)  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="BaseModel subclasses"):
        SettingsMap(Plain)  # type: ignore[arg-type]


def test_basesettings_subclass_without_decorator_is_not_registered(tmp_path: Path) -> None:
    class UndeclaredSettings(BaseSettings):
        value: int = 1

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    with pytest.raises(SettingsResolveError, match="did not match any declared section"):
        GetSettings(target=UndeclaredSettings)

    assert GetSettings(target=UndeclaredSettings, default="fallback") == "fallback"


def test_validation_error_falls_back_to_default_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app: {}\n", encoding="utf-8")
    monkeypatch.setenv("FASTAPIEX__SETTINGS__PATH", str(settings_file))

    caplog.set_level(logging.WARNING)

    assert GetSettings(target="app", field="name", default="fallback") == "fallback"
    assert GetSettings(target="app", field="name", default="fallback") == "fallback"

    warning_messages = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    validation_warnings = [msg for msg in warning_messages if "validation failed" in msg]
    assert len(validation_warnings) == 1


def test_registration_allows_case_variant_section_names(tmp_path: Path) -> None:
    @Settings("APP")
    class UpperApp(BaseSettings):
        name: str

    @Settings("app")
    class LowerApp(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("APP:\n  name: upper\napp:\n  name: lower\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    # Type-target reads remain exact and do not become ambiguous in case-insensitive mode.
    assert GetSettings(target=UpperApp, field="name") == "upper"
    assert GetSettings(target=LowerApp, field="name") == "lower"


def test_case_insensitive_path_lookup_is_ambiguous_for_case_variant_sections(tmp_path: Path) -> None:
    @Settings("APP")
    class UpperApp(BaseSettings):
        name: str

    @Settings("app")
    class LowerApp(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("APP:\n  name: upper\napp:\n  name: lower\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    with pytest.raises(SettingsResolveError):
        GetSettings(target="app", field="name")


def test_case_insensitive_map_lookup_is_ambiguous_for_case_variant_keys(tmp_path: Path) -> None:
    @SettingsMap("services")
    class ServiceSettings(BaseSettings):
        host: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "services:\n  API:\n    host: upper\n  api:\n    host: lower\n",
        encoding="utf-8",
    )
    init_settings(settings_path=settings_file)

    with pytest.raises(SettingsResolveError):
        GetSettings(target="services.api", field="host")


def test_prefixed_settings_path_env_is_used_for_implicit_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: from-env-path\n", encoding="utf-8")
    monkeypatch.setenv("FASTAPIEX__SETTINGS__PATH", str(settings_file))

    assert GetSettings(target=AppSettings, field="name") == "from-env-path"


def test_implicit_init_applies_runtime_controls_from_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @Settings("App")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "fastapiex:\n  settings:\n    case_sensitive: true\n    reload: always\nApp:\n  name: v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FASTAPIEX__SETTINGS__PATH", str(settings_file))

    assert GetSettings(target=AppSettings, field="name") == "v1"

    settings_file.write_text(
        "fastapiex:\n  settings:\n    case_sensitive: true\n    reload: always\nApp:\n  name: v2\n",
        encoding="utf-8",
    )
    assert GetSettings(target=AppSettings, field="name") == "v2"


def test_prefixed_base_dir_env_is_used_for_implicit_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: from-base-dir\n", encoding="utf-8")
    monkeypatch.setenv("FASTAPIEX__BASE_DIR", str(tmp_path))

    assert GetSettings(target=AppSettings, field="name") == "from-base-dir"


def test_case_sensitive_true_on_posix_allows_distinct_section_names(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__CASE_SENSITIVE", "true")
    monkeypatch.setattr(os, "name", "posix", raising=False)

    @Settings("APP")
    class UpperApp(BaseSettings):
        name: str

    @Settings("app")
    class LowerApp(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("APP:\n  name: upper\napp:\n  name: lower\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target="APP", field="name") == "upper"
    assert GetSettings(target="app", field="name") == "lower"
    assert GetSettings(target=UpperApp, field="name") == "upper"
    assert GetSettings(target=LowerApp, field="name") == "lower"


def test_case_sensitive_true_is_ignored_on_windows(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__CASE_SENSITIVE", "true")
    monkeypatch.setattr(os, "name", "nt", raising=False)

    caplog.set_level(logging.WARNING)

    @Settings("APP")
    class UpperApp(BaseSettings):
        name: str

    @Settings("app")
    class LowerApp(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("APP:\n  name: upper\napp:\n  name: lower\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target=UpperApp, field="name") == "upper"
    assert GetSettings(target=LowerApp, field="name") == "lower"
    with pytest.raises(SettingsResolveError):
        GetSettings(target="app", field="name")

    warning_messages = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
    assert any("ignored on Windows" in message for message in warning_messages)


def test_reserved_prefix_is_rejected() -> None:
    with pytest.raises(SettingsRegistrationError):

        @Settings("FASTAPIEX.internal")
        class InternalSettings(BaseSettings):
            enabled: bool = True


def test_settings_prefix_is_not_reserved_anymore() -> None:
    @Settings("settings.runtime")
    class RuntimeSettings(BaseSettings):
        enabled: bool = True

    assert GetSettings(target=RuntimeSettings, field="enabled", default=False) is True


def test_manual_reload_forces_source_reread(tmp_path: Path) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target=AppSettings, field="name") == "v1"

    settings_file.write_text("app:\n  name: v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v1"

    reload_settings(reason="test")
    assert GetSettings(target=AppSettings, field="name") == "v2"


def test_snapshot_fastapiex_settings_path_can_switch_source_after_explicit_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    bootstrap = tmp_path / "bootstrap.yaml"
    env_file = tmp_path / "env.yaml"
    switched = tmp_path / "switched"
    switched.mkdir()
    switched_yaml = switched / "settings.yaml"

    env_file.write_text("app:\n  name: from-env\n", encoding="utf-8")
    switched_yaml.write_text(
        f'app:\n  name: from-switched\nfastapiex:\n  settings:\n    path: "{switched}"\n',
        encoding="utf-8",
    )
    bootstrap.write_text(
        f'app:\n  name: from-bootstrap\nfastapiex:\n  settings:\n    path: "{switched}"\n',
        encoding="utf-8",
    )

    monkeypatch.setenv("FASTAPIEX__SETTINGS__PATH", str(env_file))
    init_settings(settings_path=bootstrap)

    assert GetSettings(target=AppSettings, field="name") == "from-env"


def test_snapshot_fastapiex_settings_path_drives_runtime_source_switch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"

    first.write_text(
        f'app:\n  name: first\nfastapiex:\n  settings:\n    path: "{first}"\n',
        encoding="utf-8",
    )
    second.write_text(
        f'app:\n  name: second\nfastapiex:\n  settings:\n    path: "{second}"\n',
        encoding="utf-8",
    )
    init_settings(settings_path=first)

    assert GetSettings(target=AppSettings, field="name") == "first"

    first.write_text(
        f'app:\n  name: first-updated\nfastapiex:\n  settings:\n    path: "{second}"\n',
        encoding="utf-8",
    )

    assert GetSettings(target=AppSettings, field="name") == "second"


def test_runtime_reload_mode_from_snapshot_is_not_affected_by_env_flip_after_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)
    assert GetSettings(target=AppSettings, field="name") == "v1"

    settings_file.write_text("app:\n  name: v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v2"

    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "off")
    settings_file.write_text("app:\n  name: v3\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v3"

    settings_file.write_text("app:\n  name: v4\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v4"

    reload_settings(reason="apply-runtime-options")

    settings_file.write_text("app:\n  name: v5\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v5"


def test_reload_mode_change_in_snapshot_takes_effect_without_manual_reload(tmp_path: Path) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("fastapiex:\n  settings:\n    reload: always\napp:\n  name: v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)
    assert GetSettings(target=AppSettings, field="name") == "v1"

    settings_file.write_text("fastapiex:\n  settings:\n    reload: off\napp:\n  name: v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v2"

    settings_file.write_text("fastapiex:\n  settings:\n    reload: off\napp:\n  name: v3\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v2"


def test_reload_mode_off_in_snapshot_is_not_enabled_by_env_flip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "off")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)
    assert GetSettings(target=AppSettings, field="name") == "v1"

    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")
    settings_file.write_text("app:\n  name: v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v1"

    reload_settings(reason="enable-auto")
    assert GetSettings(target=AppSettings, field="name") == "v2"

    settings_file.write_text("app:\n  name: v3\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v2"


def test_fastapiex_namespace_lookup_is_always_case_insensitive(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__CASE_SENSITIVE", "true")
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "off")

    @Settings("APP")
    class UpperApp(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("APP:\n  name: upper\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target="FastAPIEx.Settings.Reload") is False
    assert GetSettings(target="FASTAPIEX.SETTINGS.CASE_SENSITIVE") is True
    assert GetSettings(target=UpperApp, field="name") == "upper"


def test_lww_yaml_change_overrides_older_env_value(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")
    monkeypatch.setenv("TEST__APP__NAME", "env-v1")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: yaml-v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target=AppSettings, field="name") == "env-v1"

    settings_file.write_text("app:\n  name: yaml-v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "yaml-v2"


def test_manual_reload_does_not_reingest_env_or_dotenv_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")
    monkeypatch.setenv("TEST__APP__NAME", "env-v1")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: yaml-v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)
    assert GetSettings(target=AppSettings, field="name") == "env-v1"

    settings_file.write_text("app:\n  name: yaml-v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "yaml-v2"

    monkeypatch.setenv("TEST__APP__NAME", "env-v2")
    reload_settings(reason="rebuild")
    assert GetSettings(target=AppSettings, field="name") == "yaml-v2"


def test_dotenv_changes_are_not_watched_but_yaml_changes_are(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: yaml-v1\n", encoding="utf-8")
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("TEST__APP__NAME=dotenv-v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target=AppSettings, field="name") == "dotenv-v1"

    dotenv_file.write_text("TEST__APP__NAME=dotenv-v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "dotenv-v1"

    settings_file.write_text("app:\n  name: yaml-v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "yaml-v2"


def test_dotenv_can_be_registered_as_runtime_sync_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: yaml-v1\n", encoding="utf-8")
    dotenv_file = tmp_path / ".env"
    dotenv_file.write_text("TEST__APP__NAME=dotenv-v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)
    assert GetSettings(target=AppSettings, field="name") == "dotenv-v1"

    dotenv_file.write_text("TEST__APP__NAME=dotenv-v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "dotenv-v1"

    manager = get_settings_manager()
    manager.register_source_sync("dotenv", sync_on_reload=True)

    dotenv_file.write_text("TEST__APP__NAME=dotenv-v3\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "dotenv-v3"


def test_dotenv_path_switch_sync_can_be_enabled_explicitly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")

    @Settings("app")
    class AppSettings(BaseSettings):
        name: str
        token: str | None = None

    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()

    first_yaml = first_dir / "settings.yaml"
    second_yaml = second_dir / "settings.yaml"
    (first_dir / ".env").write_text("TEST__APP__TOKEN=token-first\n", encoding="utf-8")
    (second_dir / ".env").write_text("TEST__APP__TOKEN=token-second\n", encoding="utf-8")

    first_yaml.write_text(
        f'app:\n  name: first\nfastapiex:\n  settings:\n    path: "{first_yaml}"\n',
        encoding="utf-8",
    )
    second_yaml.write_text("app:\n  name: second\n", encoding="utf-8")

    init_settings(settings_path=first_yaml)
    assert GetSettings(target=AppSettings, field="name") == "first"
    assert GetSettings(target=AppSettings, field="token") == "token-first"

    manager = get_settings_manager()
    manager.register_source_sync("dotenv", sync_on_path_switch=True)

    first_yaml.write_text(
        f'app:\n  name: first-updated\nfastapiex:\n  settings:\n    path: "{second_yaml}"\n',
        encoding="utf-8",
    )

    assert GetSettings(target=AppSettings, field="name") == "second"
    assert GetSettings(target=AppSettings, field="token") == "token-second"


def test_getsettings_allows_mapping_category_injection_for_single_settingsmap(tmp_path: Path) -> None:
    @SettingsMap("services")
    class ServiceSettings(BaseSettings):
        host: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("services:\n  api:\n    host: localhost\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    services = GetSettings(target=dict)
    assert isinstance(services, dict)
    assert services["api"].host == "localhost"


def test_getsettings_mapping_category_injection_requires_unique_map_section(tmp_path: Path) -> None:
    @SettingsMap("services")
    class ServiceSettings(BaseSettings):
        host: str

    @SettingsMap("databases")
    class DbSettings(BaseSettings):
        url: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "services:\n  api:\n    host: localhost\ndatabases:\n  main:\n    url: sqlite:///main.db\n",
        encoding="utf-8",
    )
    init_settings(settings_path=settings_file)

    with pytest.raises(SettingsResolveError, match="matched multiple sections"):
        GetSettings(target=dict)


def test_getsettings_supports_generic_type_injection_when_unique(tmp_path: Path) -> None:
    class ConfigMarker:
        pass

    @Settings("app")
    class AppSettings(BaseSettings, ConfigMarker):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: demo\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    settings_obj = GetSettings(target=ConfigMarker)
    assert isinstance(settings_obj, AppSettings)
    assert settings_obj.name == "demo"


def test_getsettings_generic_type_injection_requires_unique_section(tmp_path: Path) -> None:
    class SharedMarker:
        pass

    @Settings("app")
    class AppSettings(BaseSettings, SharedMarker):
        name: str

    @Settings("worker")
    class WorkerSettings(BaseSettings, SharedMarker):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "app:\n  name: api\nworker:\n  name: jobs\n",
        encoding="utf-8",
    )
    init_settings(settings_path=settings_file)

    with pytest.raises(SettingsResolveError, match="matched multiple sections"):
        GetSettings(target=SharedMarker)


def test_getsettings_generic_type_ambiguity_falls_back_to_default(tmp_path: Path) -> None:
    class SharedMarker:
        pass

    @Settings("app")
    class AppSettings(BaseSettings, SharedMarker):
        name: str

    @Settings("worker")
    class WorkerSettings(BaseSettings, SharedMarker):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "app:\n  name: api\nworker:\n  name: jobs\n",
        encoding="utf-8",
    )
    init_settings(settings_path=settings_file)

    default_obj = types.SimpleNamespace(name="fallback")
    assert GetSettings(target=SharedMarker, default=default_obj) is default_obj


def test_getsettings_generic_type_miss_falls_back_to_default(tmp_path: Path) -> None:
    class KnownMarker:
        pass

    class MissingMarker:
        pass

    @Settings("app")
    class AppSettings(BaseSettings, KnownMarker):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: api\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    default_obj = types.SimpleNamespace(name="fallback")
    assert GetSettings(target=MissingMarker, default=default_obj) is default_obj


def test_getsettings_supports_generic_type_injection_for_singleton_map_item(tmp_path: Path) -> None:
    class ServiceMarker:
        pass

    @SettingsMap("services")
    class ServiceSettings(BaseSettings, ServiceMarker):
        host: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("services:\n  api:\n    host: localhost\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    services = GetSettings(target=ServiceMarker)
    assert isinstance(services, dict)
    assert services["api"].host == "localhost"


def test_getsettings_can_read_intermediate_path_for_object_and_map_levels(tmp_path: Path) -> None:
    @Settings("father")
    class FatherSettings(BaseSettings):
        a: int

    @Settings("father.son.grandson")
    class GrandsonSettings(BaseSettings):
        age: int

    @SettingsMap("father.services")
    class ServiceSettings(BaseSettings):
        host: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "father:\n  a: 1\n  son:\n    grandson:\n      age: 7\n  services:\n    api:\n      host: 127.0.0.1\n",
        encoding="utf-8",
    )
    init_settings(settings_path=settings_file)

    son = GetSettings(target="father.son")
    assert son.grandson.age == 7

    services = GetSettings(target="father.services")
    assert isinstance(services, dict)
    assert services["api"].host == "127.0.0.1"


def test_default_with_field_returns_default_object_instead_of_projecting() -> None:
    default_obj = types.SimpleNamespace(val="test")
    assert GetSettings(target="some_unknown_path", field="val", default=default_obj) is default_obj


def test_manual_reload_restores_snapshot_after_monkeypatch(tmp_path: Path) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("fastapiex:\n  settings:\n    reload: off\napp:\n  name: stable\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    app = GetSettings(target=AppSettings)
    app.name = "patched"
    assert GetSettings(target=AppSettings, field="name") == "patched"

    reload_settings(reason="restore-after-monkeypatch")
    assert GetSettings(target=AppSettings, field="name") == "stable"


def test_modules_change_triggers_snapshot_refresh_from_live_raw_when_reload_off(
    tmp_path: Path,
) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: v1\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    manager = get_settings_manager()
    assert GetSettings(target=AppSettings, field="name") == "v1"

    settings_file.write_text("app:\n  name: v2\n", encoding="utf-8")
    assert GetSettings(target=AppSettings, field="name") == "v1"

    dynamic_name = "tests.module_change_trigger"
    sys.modules[dynamic_name] = types.ModuleType(dynamic_name)
    try:
        assert dynamic_name not in manager._module_snapshot
        assert GetSettings(target=AppSettings, field="name") == "v1"
        assert dynamic_name in manager._module_snapshot
    finally:
        sys.modules.pop(dynamic_name, None)


def test_rediscovery_removes_stale_section_after_module_replacement(tmp_path: Path) -> None:
    module_v1 = types.ModuleType(DYNAMIC_MODULE)
    sys.modules[DYNAMIC_MODULE] = module_v1
    exec(
        """
from fastapiex.settings import BaseSettings, Settings

@Settings("dyn")
class DynSettings(BaseSettings):
    a: int
""",
        module_v1.__dict__,
    )

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("dyn:\n  a: 5\n", encoding="utf-8")
    init_settings(settings_path=settings_file)

    assert GetSettings(target="dyn", field="a") == 5

    # Replace module with a same-name module that no longer declares settings.
    module_v2 = types.ModuleType(DYNAMIC_MODULE)
    module_v2.__dict__["__name__"] = DYNAMIC_MODULE
    sys.modules[DYNAMIC_MODULE] = module_v2

    # phase-A miss should trigger rediscovery and remove stale declarations.
    assert GetSettings(target="dyn", field="missing", default=-1) == -1

    with pytest.raises(SettingsResolveError):
        GetSettings(target="dyn", field="a")


def test_settings_source_is_process_global_and_singleton(tmp_path: Path) -> None:
    @Settings("app")
    class AppSettings(BaseSettings):
        name: str = "demo"

    file_a = tmp_path / "a.yaml"
    file_a.write_text("app:\n  name: a\n", encoding="utf-8")
    file_b = tmp_path / "b.yaml"
    file_b.write_text("app:\n  name: b\n", encoding="utf-8")

    init_settings(settings_path=file_a)

    with pytest.raises(RuntimeError, match="different source"):
        init_settings(settings_path=file_b)
