from __future__ import annotations

import os
from pathlib import Path

import pytest

from fastapiex.settings.live_config import LiveConfigStore
from fastapiex.settings.loader import (
    load_dotenv_overrides,
    load_env_overrides,
    load_yaml_settings,
    resolve_env_prefix,
)


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    controlled_prefixes = (
        "FASTAPIEX__",
        "TEST__",
        "UNITTEST__",
        "SOME_CUSTOM_PREFIX",
        "CODEX_TEST_",
    )
    for key in list(os.environ):
        if key.startswith(controlled_prefixes):
            monkeypatch.delenv(key, raising=False)


def _materialize_raw(*, path: Path, env_prefix: str, case_sensitive: bool) -> dict[str, object]:
    resolved_prefix = resolve_env_prefix(env_prefix)
    yaml_raw = load_yaml_settings(path)
    dotenv_raw = load_dotenv_overrides(
        start_dir=path.parent,
        prefix=resolved_prefix,
        case_sensitive=case_sensitive,
    )
    env_raw = load_env_overrides(prefix=resolved_prefix, case_sensitive=case_sensitive)
    store = LiveConfigStore()
    store.reset({"yaml": yaml_raw, "dotenv": dotenv_raw, "env": env_raw})
    return store.materialize()


def test_loader_stack_applies_env_dotenv_yaml_precedence_case_insensitive(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text(
        "app:\n  name: yaml\n  debug: false\n  port: 7000\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "TEST__APP__NAME=dotenv\nTEST__APP__DEBUG=true\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("TEST__APP__PORT", "8080")

    raw = _materialize_raw(path=settings_file, env_prefix="TEST__", case_sensitive=False)

    assert raw["app"]["name"] == "dotenv"
    assert raw["app"]["debug"] is True
    assert raw["app"]["port"] == 8080


def test_loader_stack_case_sensitive_env_mapping_preserves_case(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("App:\n  Name: yaml\n", encoding="utf-8")

    monkeypatch.setenv("TEST__App__Name", "env-value")

    raw = _materialize_raw(path=settings_file, env_prefix="TEST__", case_sensitive=True)

    assert raw["App"]["Name"] == "env-value"
    assert "app" not in raw


def test_runtime_control_env_keys_are_plain_snapshot_keys(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app:\n  name: yaml\n", encoding="utf-8")

    monkeypatch.setenv("FASTAPIEX__SETTINGS__CASE_SENSITIVE", "true")
    monkeypatch.setenv("FASTAPIEX__SETTINGS__RELOAD", "on_change")
    monkeypatch.setenv("FASTAPIEX__SETTINGS__PATH", "/tmp/settings.yaml")
    monkeypatch.setenv("FASTAPIEX__BASE_DIR", "/tmp")
    monkeypatch.setenv("FASTAPIEX__SETTINGS__ENV_PREFIX", "TEST__")

    raw = _materialize_raw(path=settings_file, env_prefix="", case_sensitive=False)

    assert raw["fastapiex"]["settings"]["case_sensitive"] is True
    assert raw["fastapiex"]["settings"]["reload"] == "on_change"
    assert raw["fastapiex"]["settings"]["path"] == "/tmp/settings.yaml"
    assert raw["fastapiex"]["base_dir"] == "/tmp"
    assert raw["fastapiex"]["settings"]["env_prefix"] == "TEST__"
    assert raw["app"]["name"] == "yaml"


def test_loader_stack_parses_extended_scalar_literals(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("app: {}\n", encoding="utf-8")

    monkeypatch.setenv("TEST__APP__TRUTHY", "yes")
    monkeypatch.setenv("TEST__APP__FALSY", "off")
    monkeypatch.setenv("TEST__APP__NONE", "none")
    monkeypatch.setenv("TEST__APP__COUNT", "1_000")
    monkeypatch.setenv("TEST__APP__RATE", "6.02e3")
    monkeypatch.setenv("TEST__APP__QUOTED", '"hello"')

    raw = _materialize_raw(path=settings_file, env_prefix="TEST__", case_sensitive=False)

    assert raw["app"]["truthy"] is True
    assert raw["app"]["falsy"] is False
    assert raw["app"]["none"] is None
    assert raw["app"]["count"] == 1000
    assert raw["app"]["rate"] == 6020.0
    assert raw["app"]["quoted"] == "hello"


def test_loader_stack_empty_prefix_reads_plain_env_key(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("CODEX_TEST_ONE", "1")
    raw = _materialize_raw(path=settings_file, env_prefix="", case_sensitive=False)

    assert raw["codex_test_one"] == 1


def test_loader_stack_rejects_reserved_env_prefix_value(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    try:
        _materialize_raw(path=settings_file, env_prefix="FASTAPIEX__", case_sensitive=False)
    except ValueError as exc:
        assert "FASTAPIEX__SETTINGS__ENV_PREFIX" in str(exc)
    else:
        raise AssertionError("expected reserved prefix rejection")


def test_loader_stack_strips_raw_prefix_without_forcing_separator(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("SOME_CUSTOM_PREFIX__ONE", "1")
    monkeypatch.setenv("SOME_CUSTOM_PREFIX_TWO", "2")
    monkeypatch.setenv("SOME_CUSTOM_PREFIXTHREE", "3")

    raw_a = _materialize_raw(path=settings_file, env_prefix="SOME_CUSTOM_PREFIX__", case_sensitive=False)
    raw_b = _materialize_raw(path=settings_file, env_prefix="SOME_CUSTOM_PREFIX_", case_sensitive=False)
    raw_c = _materialize_raw(path=settings_file, env_prefix="SOME_CUSTOM_PREFIX", case_sensitive=False)

    assert raw_a["one"] == 1
    assert raw_b["two"] == 2
    assert raw_c["three"] == 3


def test_loader_stack_allows_triple_underscore_segment(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("UNITTEST__FOO___BAR", "1")

    raw = _materialize_raw(path=settings_file, env_prefix="UNITTEST__", case_sensitive=False)

    assert raw["foo"]["_bar"] == 1


def test_loader_stack_ignores_quadruple_underscore_from_env(monkeypatch, tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("UNITTEST__FOO____BAR", "1")

    raw = _materialize_raw(path=settings_file, env_prefix="UNITTEST__", case_sensitive=False)
    assert raw == {}


def test_loader_stack_ignores_quadruple_underscore_from_dotenv(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text("UNITTEST__FOO____BAR=1\n", encoding="utf-8")

    raw = _materialize_raw(path=settings_file, env_prefix="UNITTEST__", case_sensitive=False)
    assert raw == {}


def test_prefixed_fastapiex_key_is_ignored_and_warned_from_env(
    caplog,
    monkeypatch,
    tmp_path: Path,
) -> None:
    import logging

    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("TEST__FASTAPIEX__SETTINGS__PATH", "/should/be/ignored")

    caplog.set_level(logging.WARNING)
    raw = _materialize_raw(path=settings_file, env_prefix="TEST__", case_sensitive=False)

    assert "fastapiex" not in raw
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("must not carry" in msg and "TEST__FASTAPIEX__SETTINGS__PATH" in msg for msg in warning_messages)


def test_prefixed_fastapiex_key_is_ignored_from_dotenv(tmp_path: Path) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")
    (tmp_path / ".env").write_text("TEST__FASTAPIEX__SETTINGS__RELOAD=always\n", encoding="utf-8")

    raw = _materialize_raw(path=settings_file, env_prefix="TEST__", case_sensitive=False)
    assert "fastapiex" not in raw


def test_real_fastapiex_key_wins_when_prefixed_variant_also_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "settings.yaml"
    settings_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("FASTAPIEX__SETTINGS__PATH", "/real.yaml")
    monkeypatch.setenv("TEST__FASTAPIEX__SETTINGS__PATH", "/should/be/ignored")

    raw = _materialize_raw(path=settings_file, env_prefix="TEST__", case_sensitive=False)

    assert raw["fastapiex"]["settings"]["path"] == "/real.yaml"
