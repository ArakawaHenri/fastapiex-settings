from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol, TypeVar


class SupportsSettingsPath(Protocol):
    @property
    def settings_path(self) -> Path: ...


SourceT = TypeVar("SourceT", bound=SupportsSettingsPath)


def converge_control_source(
    *,
    initial_source: SourceT,
    materialize_control_snapshot: Callable[[], dict[str, Any]],
    build_source_from_controls: Callable[[Mapping[str, Any]], SourceT],
    on_path_switch: Callable[[SourceT], None],
    stabilize_path: Callable[[SourceT, Path], SourceT],
    logger: logging.Logger,
) -> tuple[SourceT, bool]:
    source = initial_source
    changed = False
    visited_paths: set[Path] = {source.settings_path}

    while True:
        control_snapshot = materialize_control_snapshot()
        next_source = build_source_from_controls(control_snapshot)

        if next_source.settings_path != source.settings_path:
            if next_source.settings_path in visited_paths:
                logger.warning("settings path control cycle detected; keeping path=%s", source.settings_path)
                stabilized = stabilize_path(next_source, source.settings_path)
                changed = changed or stabilized != source
                return stabilized, changed

            visited_paths.add(next_source.settings_path)
            source = next_source
            on_path_switch(source)
            changed = True
            continue

        if next_source != source:
            source = next_source
            changed = True

        return source, changed
