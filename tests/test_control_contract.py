from __future__ import annotations

from pydantic import Field

from fastapiex.settings.constants import ENV_KEY_SEPARATOR
from fastapiex.settings.control_contract import CONTROL_SPEC, ControlModel, SETTINGS_ENV_PREFIX_ENV_KEY, SettingsControls
from fastapiex.settings.core_settings import CoreSettings


def test_control_contract_is_derived_from_control_model() -> None:
    assert CONTROL_SPEC.root == ControlModel.section_root()
    assert CONTROL_SPEC.path_text == ControlModel.section_name()
    assert SETTINGS_ENV_PREFIX_ENV_KEY == ControlModel.nested_env_key(
        SettingsControls,
        "env_prefix",
        separator=ENV_KEY_SEPARATOR,
    )


def test_core_settings_derives_nested_paths_from_class_contract() -> None:
    class RuntimeKnobs(CoreSettings):
        enabled: bool = True

    class RuntimeCore(CoreSettings):
        runtime: RuntimeKnobs = Field(default_factory=RuntimeKnobs)

    assert RuntimeCore.section_root() == "runtime_core"
    assert RuntimeCore.dotted_path() == "runtime_core"
    assert RuntimeCore.env_key(separator=ENV_KEY_SEPARATOR) == "RUNTIME_CORE"
    assert RuntimeCore.nested_field_name(RuntimeKnobs) == "runtime"
    assert RuntimeCore.nested_dotted_path(RuntimeKnobs, "enabled") == "runtime_core.runtime.enabled"
    assert RuntimeCore.nested_env_key(RuntimeKnobs, "enabled", separator=ENV_KEY_SEPARATOR) == (
        "RUNTIME_CORE__RUNTIME__ENABLED"
    )
