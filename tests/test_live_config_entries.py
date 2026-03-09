from __future__ import annotations

import sys
from collections.abc import Iterator, Mapping

import pytest

from fastapiex.settings.live_config import EntrySource, build_entries_from_mappings
from fastapiex.settings.projection import materialize_effective_snapshot


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


def _materialize(sources: list[EntrySource]) -> dict[str, object]:
    entries = build_entries_from_mappings(sources)
    return materialize_effective_snapshot(entries, env_prefix="", case_sensitive=False)


def test_entries_projection_uses_startup_precedence_env_over_dotenv_over_yaml() -> None:
    raw = _materialize(
        [
            EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=1, mapping={"app": {"name": "yaml"}}),
            EntrySource(
                source="dotenv",
                priority=2,
                kind="mapping",
                include_in_control=True,
                rev=2,
                mapping={"app": {"name": "dotenv"}},
            ),
            EntrySource(source="env", priority=3, kind="mapping", include_in_control=True, rev=3, mapping={"app": {"name": "env"}}),
        ]
    )

    assert raw["app"]["name"] == "env"


def test_entries_projection_is_lww_even_against_higher_priority_source() -> None:
    raw = _materialize(
        [
            EntrySource(source="env", priority=3, kind="mapping", include_in_control=True, rev=3, mapping={"app": {"name": "env-v1"}}),
            EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=4, mapping={"app": {"name": "yaml-v2"}}),
        ]
    )

    assert raw["app"]["name"] == "yaml-v2"


def test_entries_projection_resolves_ties_by_source_priority() -> None:
    raw = _materialize(
        [
            EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=10, mapping={"app": {"name": "yaml"}}),
            EntrySource(source="dotenv", priority=2, kind="mapping", include_in_control=True, rev=10, mapping={"app": {"name": "dotenv"}}),
        ]
    )

    assert raw["app"]["name"] == "dotenv"


def test_build_entries_rejects_cyclic_mapping() -> None:
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic

    with pytest.raises(ValueError, match="cyclic mapping detected"):
        build_entries_from_mappings(
            [
                EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=1, mapping=cyclic)
            ]
        )


def test_build_entries_handles_deeply_nested_mapping_without_recursion() -> None:
    depth = sys.getrecursionlimit() + 50
    nested: object = "leaf"
    for index in range(depth, 0, -1):
        nested = {f"level_{index}": nested}

    raw = _materialize(
        [
            EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=1, mapping=nested),
        ]
    )

    cursor: object = raw
    for index in range(1, depth + 1):
        assert isinstance(cursor, dict)
        cursor = cursor[f"level_{index}"]

    assert cursor == "leaf"


def test_build_entries_handles_unstable_mapping_items_via_snapshot_fallback() -> None:
    unstable = _ItemsFlakyMapping({"app": {"name": "demo"}}, item_failures=2)
    raw = _materialize(
        [
            EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=1, mapping=unstable),
        ]
    )

    assert raw["app"]["name"] == "demo"


def test_build_entries_ignores_keys_that_disappear_between_snapshot_and_read() -> None:
    unstable = _TransientKeyMapping({"app": {"name": "demo"}}, missing_key="ghost")
    raw = _materialize(
        [
            EntrySource(source="yaml", priority=1, kind="mapping", include_in_control=True, rev=1, mapping=unstable),
        ]
    )

    assert raw == {"app": {"name": "demo"}}
