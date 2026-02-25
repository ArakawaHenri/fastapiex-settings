from __future__ import annotations

from fastapiex.settings.live_config import LiveConfigStore


def test_reset_uses_startup_precedence_env_over_dotenv_over_yaml() -> None:
    store = LiveConfigStore()
    changed = store.reset(
        {
            "yaml": {"app": {"name": "yaml"}},
            "dotenv": {"app": {"name": "dotenv"}},
            "env": {"app": {"name": "env"}},
        }
    )

    assert changed is True
    assert store.materialize()["app"]["name"] == "env"


def test_single_source_update_is_lww_even_against_higher_priority_source() -> None:
    store = LiveConfigStore()
    store.reset(
        {
            "yaml": {"app": {"name": "yaml-v1"}},
            "dotenv": {},
            "env": {"app": {"name": "env-v1"}},
        }
    )
    assert store.materialize()["app"]["name"] == "env-v1"

    changed = store.replace_source("yaml", {"app": {"name": "yaml-v2"}})
    assert changed is True
    assert store.materialize()["app"]["name"] == "yaml-v2"


def test_multi_source_batch_update_assigns_revs_by_source_priority_order() -> None:
    store = LiveConfigStore()
    store.reset(
        {
            "yaml": {"app": {"name": "yaml-v1"}},
            "dotenv": {"app": {"name": "dotenv-v1"}},
            "env": {},
        }
    )

    changed = store.replace_sources(
        {
            "yaml": {"app": {"name": "yaml-v2"}},
            "dotenv": {"app": {"name": "dotenv-v2"}},
        }
    )
    assert changed is True
    assert store.materialize()["app"]["name"] == "dotenv-v2"


def test_replace_source_without_effect_returns_false() -> None:
    store = LiveConfigStore()
    store.reset(
        {
            "yaml": {"app": {"name": "yaml-v1"}},
            "dotenv": {},
            "env": {},
        }
    )

    assert store.replace_source("yaml", {"app": {"name": "yaml-v1"}}) is False
