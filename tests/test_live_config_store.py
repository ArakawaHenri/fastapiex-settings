from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping

import pytest

from fastapiex.settings.live_config import LiveConfigStore


class _ItemsFlakyMapping(Mapping[str, object]):
    def __init__(self, data: Mapping[str, object], *, item_failures: int) -> None:
        self._data = dict(data)
        self._item_failures = item_failures

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def items(self) -> object:
        if self._item_failures > 0:
            self._item_failures -= 1
            raise RuntimeError("unstable mapping.items")
        return self._data.items()


class _TransientKeyMapping(Mapping[str, object]):
    def __init__(self, data: Mapping[str, object], *, missing_key: str) -> None:
        self._data = dict(data)
        self._missing_key = missing_key

    def __getitem__(self, key: str) -> object:
        if key == self._missing_key:
            raise KeyError(key)
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._data
        yield self._missing_key

    def __len__(self) -> int:
        return len(self._data) + 1

    def items(self) -> object:
        raise RuntimeError("unstable mapping.items")


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


def test_reset_rejects_cyclic_mapping() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    store = LiveConfigStore()

    with pytest.raises(ValueError, match="cyclic mapping detected"):
        store.reset(
            {
                "yaml": cyclic,
                "dotenv": {},
                "env": {},
            }
        )


def test_reset_handles_deeply_nested_mapping_without_recursion() -> None:
    depth = sys.getrecursionlimit() + 50
    nested: object = "leaf"
    for index in range(depth, 0, -1):
        nested = {f"level_{index}": nested}

    store = LiveConfigStore()
    changed = store.reset(
        {
            "yaml": nested,
            "dotenv": {},
            "env": {},
        }
    )

    assert changed is True

    cursor: object = store.materialize()
    for index in range(1, depth + 1):
        assert isinstance(cursor, dict)
        cursor = cursor[f"level_{index}"]

    assert cursor == "leaf"


def test_reset_handles_unstable_mapping_items_via_snapshot_fallback() -> None:
    store = LiveConfigStore()
    unstable = _ItemsFlakyMapping({"app": {"name": "demo"}}, item_failures=2)

    changed = store.reset(
        {
            "yaml": unstable,
            "dotenv": {},
            "env": {},
        }
    )

    assert changed is True
    assert store.materialize()["app"]["name"] == "demo"


def test_reset_ignores_keys_that_disappear_between_snapshot_and_read() -> None:
    store = LiveConfigStore()
    unstable = _TransientKeyMapping({"app": {"name": "demo"}}, missing_key="ghost")

    changed = store.reset(
        {
            "yaml": unstable,
            "dotenv": {},
            "env": {},
        }
    )

    assert changed is True
    assert store.materialize() == {"app": {"name": "demo"}}
