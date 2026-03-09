from __future__ import annotations

import pytest

from fastapiex.settings import BaseSettings
from fastapiex.settings.exceptions import SettingsRegistrationError
from fastapiex.settings.registry import SettingsRegistry, build_section_spec


def test_snapshot_sections_are_kept_sorted_after_reindex() -> None:
    registry = SettingsRegistry()

    class SectionB(BaseSettings):
        value: int = 1

    class SectionA(BaseSettings):
        value: int = 2

    registry.register_section(
        spec=build_section_spec(model=SectionB, kind="object", raw_path="b"),
        owner_module=__name__,
    )
    registry.register_section(
        spec=build_section_spec(model=SectionA, kind="object", raw_path="a"),
        owner_module=__name__,
    )

    snapshot = registry.snapshot()
    assert [section.path_text for section in snapshot.sections] == ["a", "b"]
    assert registry.sections() == list(snapshot.sections)
    assert registry.version() == snapshot.version


def test_failed_registration_rolls_back_snapshot_and_version() -> None:
    registry = SettingsRegistry()

    class ExistingSection(BaseSettings):
        value: int = 1

    class DuplicateSection(BaseSettings):
        value: int = 2

    registry.register_section(
        spec=build_section_spec(model=ExistingSection, kind="object", raw_path="dup"),
        owner_module=__name__,
    )
    before = registry.snapshot()

    with pytest.raises(SettingsRegistrationError):
        registry.register_section(
            spec=build_section_spec(model=DuplicateSection, kind="object", raw_path="dup"),
            owner_module=__name__,
        )

    after = registry.snapshot()
    assert after.version == before.version
    assert after.sections == before.sections
    assert len(after.sections) == 1
    assert after.sections[0].model is ExistingSection
