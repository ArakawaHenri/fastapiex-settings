from __future__ import annotations

import logging
from typing import Any

from fastapiex.settings.env_keypath import key_to_parts, set_nested_mapping


def test_key_to_parts_keeps_reserved_namespace_case_insensitive() -> None:
    parts = key_to_parts("FASTAPIEX__SETTINGS__PATH", prefix="TEST__", case_sensitive=True)
    assert parts == ["fastapiex", "settings", "path"]


def test_key_to_parts_matches_prefix_case_insensitive_when_mode_is_case_insensitive() -> None:
    parts = key_to_parts("test__APP__NAME", prefix="TEST__", case_sensitive=False)
    assert parts == ["app", "name"]


def test_key_to_parts_rejects_prefixed_reserved_namespace_and_warns(caplog) -> None:
    caplog.set_level(logging.WARNING)
    parts = key_to_parts("TEST__FASTAPIEX__SETTINGS__PATH", prefix="TEST__", case_sensitive=False)
    assert parts is None
    assert any("must not carry" in record.getMessage() for record in caplog.records)


def test_set_nested_mapping_creates_nested_mapping() -> None:
    target: dict[str, Any] = {}
    set_nested_mapping(target, ["app", "name"], "demo")
    assert target["app"]["name"] == "demo"
