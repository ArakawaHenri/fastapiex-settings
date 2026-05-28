from __future__ import annotations

from pathlib import Path

from fastapiex.settings.context import resolve_settings_target


def test_resolve_settings_target_treats_unknown_suffix_as_explicit_file(tmp_path: Path) -> None:
    target = resolve_settings_target(tmp_path / "settings.toml")

    assert target is not None
    assert target.path_mode == "explicit_file"
    assert target.settings_path == (tmp_path / "settings.toml").resolve()
    assert target.anchor_dir == tmp_path.resolve()


def test_resolve_settings_target_keeps_existing_directory_as_directory_anchor(tmp_path: Path) -> None:
    directory = tmp_path / "settings.d"
    directory.mkdir()

    target = resolve_settings_target(directory)

    assert target is not None
    assert target.path_mode == "directory_anchor"
    assert target.settings_path == (directory / "settings.yaml").resolve()
    assert target.anchor_dir == directory.resolve()


def test_resolve_settings_target_keeps_missing_plain_path_as_directory_anchor(tmp_path: Path) -> None:
    directory = tmp_path / "settings"

    target = resolve_settings_target(directory)

    assert target is not None
    assert target.path_mode == "directory_anchor"
    assert target.settings_path == (directory / "settings.yaml").resolve()
    assert target.anchor_dir == directory.resolve()


def test_resolve_settings_target_trailing_separator_forces_directory_anchor(tmp_path: Path) -> None:
    target = resolve_settings_target(f"{tmp_path / 'settings.toml'}/")

    assert target is not None
    assert target.path_mode == "directory_anchor"
    assert target.settings_path == (tmp_path / "settings.toml" / "settings.yaml").resolve()
    assert target.anchor_dir == (tmp_path / "settings.toml").resolve()
