from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, create_model

from .exceptions import SettingsRegistrationError
from .registry import SettingsSection


@dataclass(frozen=True)
class BuiltSchema:
    root_model: type[BaseModel]
    sections: tuple[SettingsSection, ...]


@dataclass
class _TreeNode:
    name: str
    decl: SettingsSection | None = None
    children: dict[str, "_TreeNode"] = field(default_factory=dict)


def build_root_settings_model(
    sections: list[SettingsSection],
    *,
    model_name: str = "FastAPIExRootSettings",
) -> BuiltSchema:
    root = _TreeNode(name="__root__")
    for section in sorted(sections, key=lambda item: item.path):
        _insert_section(root, section)

    field_defs: dict[str, tuple[Any, Any]] = {}
    for child_name, child in sorted(root.children.items()):
        if child.decl is not None and child.decl.kind == "map":
            field_defs[child_name] = _build_map_field_def(child.decl.model)
            continue

        child_model = _build_object_model(child, model_name=f"{model_name}_{child_name}")
        field_defs[child_name] = (child_model, Field(default_factory=child_model))

    # Reserved runtime controls are plain keys and remain readable via GetSettings.
    if "fastapiex" not in field_defs:
        field_defs["fastapiex"] = (dict[str, Any], Field(default_factory=dict))

    root_model = _create_dynamic_model(
        model_name=model_name,
        base_model=BaseModel,
        field_defs=field_defs,
    )
    return BuiltSchema(root_model=root_model, sections=tuple(sorted(sections, key=lambda item: item.path)))


def _insert_section(root: _TreeNode, section: SettingsSection) -> None:
    current = root
    for part in section.path:
        if current.decl is not None and current.decl.kind == "map":
            raise SettingsRegistrationError(
                f"map section '{current.decl.path_text}' cannot have nested section '{section.path_text}'"
            )
        child = current.children.get(part)
        if child is None:
            child = _TreeNode(name=part)
            current.children[part] = child
        current = child

    if current.children and section.kind == "map":
        raise SettingsRegistrationError(
            f"map section '{section.path_text}' conflicts with existing nested declarations"
        )

    existing = current.decl
    if existing is not None and (existing.model is not section.model or existing.kind != section.kind):
        raise SettingsRegistrationError(f"section '{section.path_text}' is declared by multiple incompatible models")
    current.decl = section


def _build_object_model(node: _TreeNode, *, model_name: str) -> type[BaseModel]:
    if node.decl is not None and node.decl.kind == "map":
        raise SettingsRegistrationError(
            f"internal error: map node '{node.decl.path_text}' must be emitted as mapping field"
        )

    base_model: type[BaseModel] = node.decl.model if node.decl is not None else BaseModel

    field_defs: dict[str, tuple[Any, Any]] = {}
    for child_name, child in sorted(node.children.items()):
        if base_model is not BaseModel and child_name in base_model.model_fields:
            owner = node.decl.path_text if node.decl is not None else model_name
            raise SettingsRegistrationError(
                f"nested declaration '{owner}.{child_name}' conflicts with existing field '{child_name}'"
            )

        if child.decl is not None and child.decl.kind == "map":
            field_defs[child_name] = _build_map_field_def(child.decl.model)
            continue

        child_model = _build_object_model(child, model_name=f"{model_name}_{child_name}")
        field_defs[child_name] = (child_model, Field(default_factory=child_model))

    return _create_dynamic_model(
        model_name=model_name,
        base_model=base_model,
        field_defs=field_defs,
    )


def _build_map_field_def(map_model: type[BaseModel]) -> tuple[Any, Any]:
    return (dict[str, map_model], Field(default_factory=dict))  # type: ignore[valid-type]


def _create_dynamic_model(
    *,
    model_name: str,
    base_model: type[BaseModel],
    field_defs: dict[str, tuple[Any, Any]],
) -> type[BaseModel]:
    return cast(
        type[BaseModel],
        create_model(  # type: ignore[call-overload]
            model_name,
            __base__=base_model,
            __config__=ConfigDict(extra="ignore"),
            **field_defs,
        ),
    )
