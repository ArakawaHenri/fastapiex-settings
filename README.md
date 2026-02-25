# fastapiex-settings

Process-global settings declaration and resolution runtime based on Pydantic v2.

## Installation

```bash
uv add fastapiex-settings
```

## Public API (Only These Are Exported)

```python
from fastapiex.settings import (
    BaseSettings,
    Settings,
    SettingsMap,
    GetSettings,
    GetSettingsMap,
    SettingsRef,
    init_settings,
    reload_settings,
    exceptions,
)
```

No other symbol is part of the package root public API.

## Quick Start

```python
from pydantic import Field
from fastapiex.settings import (
    BaseSettings,
    Settings,
    SettingsMap,
    GetSettings,
    GetSettingsMap,
    init_settings,
    reload_settings,
)


@Settings("app")
class AppSettings(BaseSettings):
    title: str = "demo"
    debug: bool = False


@SettingsMap("services")
class ServiceSettings(BaseSettings):
    host: str
    port: int = Field(ge=1, le=65535)


init_settings(settings_path="settings.yaml")

title = GetSettings("app", field="title")
services = GetSettingsMap(ServiceSettings)  # dict[str, ServiceSettings]
api_host = GetSettings("services.api", field="host")
reload_settings(reason="manual-refresh")
```

## Public API Reference

### `BaseSettings`

```python
class BaseSettings(pydantic.BaseModel): ...
```

- Base class for declaration models.
- Inheriting this class does not register anything by itself.

### `Settings`

```python
@overload
def Settings(model: type[BaseSettings], /) -> type[BaseSettings]: ...

@overload
def Settings(path: str | None = None, /) -> Callable[[type[BaseSettings]], type[BaseSettings]]: ...
```

Role:

- Declare an object section.

Section name resolution order:

1. explicit decorator path
2. model `__section__` if non-empty
3. snake_case class name

Accepted forms:

- `@Settings`
- `@Settings("father.son")`
- `Settings(MyModel)` (functional form)

### `SettingsMap`

```python
@overload
def SettingsMap(model: type[BaseSettings], /) -> type[BaseSettings]: ...

@overload
def SettingsMap(path: str | None = None, /) -> Callable[[type[BaseSettings]], type[BaseSettings]]: ...
```

Role:

- Declare a map section (shape like `dict[str, Model]`).

Accepted forms and section naming:

- Same behavior as `Settings`.

### `GetSettings`

```python
def GetSettings(
    target: str | type[object] | None = None,
    *,
    field: str | None = None,
    default: object = _NO_DEFAULT,
) -> Any
```

Role:

- Resolve settings values from the current typed snapshot.

Parameters:

- `target`:
  - `str`: dotted path, for example `"app"` / `"father.son"` / `"services.api"`.
  - `type`: type-category injection; must match exactly one declared section.
  - `None`: only useful with `default` (otherwise unresolved).
- `field`:
  - optional dotted sub-path applied after `target` is resolved.
  - blank string is invalid.
- `default`:
  - returned as the whole query fallback value.
  - not projected by `field`.

Important semantics:

- Read chain: `registered lookup -> rediscover+lookup -> default -> error`.
- Incomplete path returns the current node as-is (model/dict/scalar/list element).
- Mapping type target (`dict`, `Mapping`) resolves only when exactly one `@SettingsMap` section exists.
- Returned objects are live runtime references (mutable); changes affect subsequent reads in the same process.

### `GetSettingsMap`

```python
def GetSettingsMap(
    target: str | type[object] | None = None,
    *,
    default: object = _NO_DEFAULT,
) -> Mapping[str, Any]
```

Role:

- Resolve settings as mapping-only API.

Parameters:

- `target`:
  - same semantics as `GetSettings`.
- `default`:
  - whole-query fallback value.
  - must be mapping when fallback path is used.

Behavior:

- Final value must be mapping; otherwise `SettingsResolveError`.
- Returned mapping is a live runtime reference (mutable), not a defensive copy.

### `SettingsRef`

```python
@dataclass(frozen=True)
class SettingsRef:
    target: str | type[object] | None
    field: str | None = None
    default: object = _NO_DEFAULT

    def get(self) -> Any: ...
    @property
    def value(self) -> Any: ...
    def __call__(self) -> Any: ...
```

Role:

- Lazy settings query descriptor.

Behavior:

- `get()`, `.value`, and `()` perform the same runtime resolve.
- Resolution semantics are identical to `GetSettings`.

### `init_settings`

```python
def init_settings(
    *,
    settings_path: str | Path | None = None,
    env_prefix: str | None = None,
) -> BaseModel
```

Role:

- Initialize process-global source and snapshot.

Parameter behavior:

- `settings_path`:
  - explicit bootstrap path.
  - only overrides the initial read of `FASTAPIEX__SETTINGS__PATH`.
  - does not lock source selection after bootstrap.
- `env_prefix`:
  - business env prefix override.
  - `None` means read from `FASTAPIEX__SETTINGS__ENV_PREFIX`.
  - non-empty value is treated as raw string prefix and removed from env key names.

Bootstrap source order:

- `settings_path` arg
- `FASTAPIEX__SETTINGS__PATH`
- `FASTAPIEX__BASE_DIR` + `/settings.yaml`
- `./settings.yaml`

Runtime source switch:

- after each yaml read, manager checks merged live snapshot key `FastAPIEx.settings.path` (`fastapiex.settings.path`) and switches yaml source to that path when changed.
- this key is treated as an ordinary snapshot key (LWW + priority), not a dedicated control state branch.

Re-init behavior:

- Re-initializing with a different resolved source raises `RuntimeError`.

### `reload_settings`

```python
def reload_settings(*, reason: str = "manual") -> BaseModel
```

Role:

- Trigger a manual runtime refresh of current settings source.

Behavior:

- Calls manager-level reload flow.
- `reason` is logging context string.

### `exceptions`

```python
from fastapiex.settings import exceptions
```

Module members:

- `exceptions.SettingsError`
- `exceptions.SettingsRegistrationError`
- `exceptions.SettingsValidationError`
- `exceptions.SettingsResolveError`

## Runtime Semantics

### Registration

- Only `@Settings` / `@SettingsMap` register sections.
- Undecorated `BaseSettings` subclasses are ignored by registry discovery.
- Section paths under `FASTAPIEX.*` are reserved and rejected (case-insensitive).
- Registration stores section paths as declared (case-preserving), independent from runtime `CASE_SENSITIVE`.
- If multiple declared paths differ only by case, case-insensitive string lookups are ambiguous and fail; type-target lookups remain exact.

### Source Loading

Sources:

- `yaml` (`settings.yaml`)
- `.env` file
- process `os.environ`

Merge strategy:

- LWW (last-write-wins by source update time)
- if timestamps tie: `env > .env > yaml`

Runtime reload:

- yaml may refresh by mode.
- `.env` and process env are loaded once at init time and not re-ingested by runtime yaml reload.
- when yaml source switches by `FastAPIEx.settings.path`, only yaml source is switched/reloaded; `.env` stays from the bootstrap directory.
- this is intentional by convention: `.env` is treated as an environment-variable generator, and runtime business env should be stable unless explicitly opted in.

Opt-in `.env` runtime sync (advanced):

- This is not part of the package-root public API. Use manager helper explicitly:

```python
from fastapiex.settings import reload_settings
from fastapiex.settings.manager import register_source_sync

# include `.env` in runtime reload passes
register_source_sync("dotenv", sync_on_reload=True)

# optional: also follow `fastapiex.settings.path` source switches
register_source_sync("dotenv", sync_on_path_switch=True)

# optional: force one immediate re-ingest after enabling sync
reload_settings(reason="enable-dotenv-sync")
```

Parameter meaning:

- `source="dotenv"`: target `.env` source behavior.
- `sync_on_reload=True`: re-read `.env` during reload pass (`RELOAD=on_change|always`, and manual `reload_settings`).
- `sync_on_path_switch=True`: when runtime settings file path switches, also re-read `.env` from the new settings directory.
- `read_snapshot`: normally omitted; keep default reader unless you are replacing source IO behavior.

### Monkeypatch / Black Magic

`GetSettings` / `GetSettingsMap` expose mutable live objects by design.

Recommended safety flow when manually patching settings at runtime:

- before monkeypatching, set `FastAPIEx.settings.reload` (`fastapiex.settings.reload`) to `off`.
- perform the manual mutation.
- when done and you want to restore canonical values from configured sources, call `reload_settings(reason="...")`.

### Runtime Controls (`FASTAPIEX__*`)

Plain-key behavior:

- `FASTAPIEX__*` keys are ingested into live snapshot as plain keys under `fastapiex.*`.
- they are readable via `GetSettings("fastapiex....")`.
- declaration is still forbidden: users cannot declare `@Settings("fastapiex...")` / `@SettingsMap("fastapiex...")`.
- mixed-case keys from file/env (for example `FastAPIEx.Settings.Reload`) are normalized into canonical `fastapiex.*`.

Supported controls:

- `FASTAPIEX__SETTINGS__PATH`
- `FASTAPIEX__BASE_DIR`
- `FASTAPIEX__SETTINGS__ENV_PREFIX`
- `FASTAPIEX__SETTINGS__CASE_SENSITIVE`
- `FASTAPIEX__SETTINGS__RELOAD`

`FASTAPIEX__SETTINGS__ENV_PREFIX` rules:

- cannot start with `FASTAPIEX__`.
- empty prefix means plain keys are considered business keys.
- non-empty prefix is stripped as raw string.
- prefix matching follows runtime case mode: case-insensitive when `CASE_SENSITIVE=false`, exact when `CASE_SENSITIVE=true`.

Equivalent examples (all readable by `GetSettings("one")`):

- `FASTAPIEX__SETTINGS__ENV_PREFIX=SOME_CUSTOM_PREFIX__` + `SOME_CUSTOM_PREFIX__ONE=1`
- `FASTAPIEX__SETTINGS__ENV_PREFIX=SOME_CUSTOM_PREFIX_` + `SOME_CUSTOM_PREFIX_ONE=1`
- `FASTAPIEX__SETTINGS__ENV_PREFIX=SOME_CUSTOM_PREFIX` + `SOME_CUSTOM_PREFIXONE=1`
- empty prefix + `ONE=1`

Env split semantics:

- delimiter is `__`
- `FOO___BAR` -> `["FOO", "_BAR"]`
- keys that produce empty segments are ignored (for example `FOO____BAR`, `__X`, `X__`)

### Case Sensitivity

Control:

- `FASTAPIEX__SETTINGS__CASE_SENSITIVE=true|false` (default `false`)

Behavior:

- `false`: case-insensitive lookup for read/env business keys.
- `true`: case-sensitive.
- Windows (`os.name == "nt"`): `true` is ignored and behaves as `false`.
- `FastAPIEx` / `FastAPIEx.*` lookup is always case-insensitive (independent from `CASE_SENSITIVE`).
- When `false`, if sibling keys collapse to the same folded name (for example `APP` and `app`), string-path lookup is treated as ambiguous and raises resolve error.

### Reload Mode

Control:

- `FASTAPIEX__SETTINGS__RELOAD=off|on_change|always` (default `off`)

Behavior:

- `off`: no auto yaml sync.
- `on_change`: sync yaml when file state changes.
- `always`: sync yaml on each read.
- module delta changes still trigger declaration rediscovery/snapshot rebuild.
- runtime controls are resolved from current live snapshot (not direct env re-read).

## Intentionally Not Public at Package Root

These capabilities still exist internally, but are not exported from `fastapiex.settings`:

- manager/registry direct access helpers
