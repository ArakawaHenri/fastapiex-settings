from __future__ import annotations

from typing import Annotated, Any, get_args, get_origin

from pydantic import BaseModel

from .base import BaseSettings
from .constants import ENV_KEY_SEPARATOR
from .specs import SectionSpec, describe_section
from .types import SectionKind


class CoreSettings(BaseSettings):
    """Internal declaration base with class-derived path helpers."""

    @classmethod
    def section_spec(cls, *, kind: SectionKind = "object") -> SectionSpec:
        return describe_section(cls, kind=kind)

    @classmethod
    def section_name(cls) -> str:
        return cls.section_spec().raw_path

    @classmethod
    def section_path(cls) -> tuple[str, ...]:
        return cls.section_spec().path

    @classmethod
    def section_root(cls) -> str:
        return cls.section_spec().root

    @classmethod
    def dotted_path(cls, *suffix: str) -> str:
        return cls.section_spec().dotted(*suffix)

    @classmethod
    def env_key(cls, *suffix: str, separator: str = ENV_KEY_SEPARATOR) -> str:
        return cls.section_spec().env_key(*suffix, separator=separator)

    @classmethod
    def nested_field_name(cls, nested_model: type[BaseModel]) -> str:
        matches = [
            field_name
            for field_name, field in cls.model_fields.items()
            if _annotation_matches_model(field.annotation, nested_model)
        ]

        if not matches:
            raise ValueError(
                f"{cls.__module__}.{cls.__qualname__} does not contain a nested field for "
                f"{nested_model.__module__}.{nested_model.__qualname__}"
            )
        if len(matches) > 1:
            joined = ", ".join(sorted(matches))
            raise ValueError(
                f"{cls.__module__}.{cls.__qualname__} contains multiple nested fields for "
                f"{nested_model.__module__}.{nested_model.__qualname__}: {joined}"
            )

        return matches[0]

    @classmethod
    def nested_path(cls, nested_model: type[BaseModel], *suffix: str) -> tuple[str, ...]:
        return cls.section_spec().path_with(cls.nested_field_name(nested_model), *suffix)

    @classmethod
    def nested_dotted_path(cls, nested_model: type[BaseModel], *suffix: str) -> str:
        return ".".join(cls.nested_path(nested_model, *suffix))

    @classmethod
    def nested_env_key(
        cls,
        nested_model: type[BaseModel],
        *suffix: str,
        separator: str = ENV_KEY_SEPARATOR,
    ) -> str:
        return separator.join(part.upper() for part in cls.nested_path(nested_model, *suffix))


def _annotation_matches_model(annotation: Any, model_type: type[BaseModel]) -> bool:
    candidate = _unwrap_annotation(annotation)
    return isinstance(candidate, type) and issubclass(candidate, BaseModel) and candidate is model_type


def _unwrap_annotation(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Annotated:
        args = get_args(annotation)
        if args:
            return _unwrap_annotation(args[0])

    args = get_args(annotation)
    if not args:
        return annotation

    non_none = [arg for arg in args if arg is not type(None)]
    if len(non_none) == 1 and len(non_none) != len(args):
        return _unwrap_annotation(non_none[0])

    return annotation
