from __future__ import annotations

from fastapiex.settings.env_value_parser import parse_dotenv_value, parse_env_value


def test_parse_env_value_parses_scalars() -> None:
    assert parse_env_value("yes") is True
    assert parse_env_value("off") is False
    assert parse_env_value("none") is None
    assert parse_env_value("1_024") == 1024
    assert parse_env_value("6.02e3") == 6020.0


def test_parse_env_value_parses_json_literals() -> None:
    assert parse_env_value("[1, 2, 3]") == [1, 2, 3]
    assert parse_env_value('{"a": 1}') == {"a": 1}


def test_parse_env_value_keeps_invalid_json_text() -> None:
    assert parse_env_value("{invalid json}") == "{invalid json}"


def test_parse_dotenv_value_strips_inline_comments_but_preserves_quoted_hash() -> None:
    assert parse_dotenv_value("abc # comment") == "abc"
    assert parse_dotenv_value('"abc # still value" # comment') == "abc # still value"
