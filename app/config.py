"""Load and validate the gateway configuration.

The configuration comes from two places:

- environment settings (paths and API keys), read with pydantic-settings;
- `gateway.yaml`, which declares providers, their models and the routes (aliases).
"""

import datetime as dt
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """The gateway configuration is invalid. The gateway must not start."""


class Settings(BaseSettings):
    """Settings read from environment variables."""

    gateway_config_path: Path = Path("config/gateway.yaml")


# --- File format (what `gateway.yaml` looks like) ---


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyReset(_FileModel):
    """Time of day when a provider resets its daily quota."""

    time: dt.time = dt.time(0, 0)
    timezone: str = "UTC"


class ModelConfig(_FileModel):
    """Limits and timeout of one model. A missing limit means "no limit"."""

    rpm: int | None = Field(default=None, gt=0)
    tpm: int | None = Field(default=None, gt=0)
    rpd: int | None = Field(default=None, gt=0)
    timeout: float = Field(default=30.0, gt=0)


class ProviderConfig(_FileModel):
    base_url: str = Field(min_length=1)
    api_key_env: str | None
    daily_reset: DailyReset = DailyReset()
    models: dict[str, ModelConfig]


class GatewaySection(_FileModel):
    deadline: float = Field(default=60.0, gt=0)
    default_completion_tokens: int = Field(default=512, gt=0)


class FileConfig(_FileModel):
    gateway: GatewaySection = GatewaySection()
    providers: dict[str, ProviderConfig]
    routes: dict[str, list[str]]


# --- Resolved configuration (what the rest of the gateway uses) ---


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: SecretStr | None
    daily_reset: DailyReset


@dataclass(frozen=True)
class Target:
    """One real `provider/model` pair that can serve an alias."""

    provider: Provider
    model: str
    limits: ModelConfig

    @property
    def name(self) -> str:
        return f"{self.provider.name}/{self.model}"


@dataclass(frozen=True)
class GatewayConfig:
    deadline: float
    default_completion_tokens: int
    routes: Mapping[str, tuple[Target, ...]]
    enabled_providers: tuple[str, ...]
    disabled_providers: tuple[str, ...]


def load_config(path: Path, environ: Mapping[str, str]) -> GatewayConfig:
    """Read, validate and resolve `gateway.yaml`.

    `environ` holds the environment variables used to find API keys.
    Raises `ConfigError` when the file is invalid.
    """
    file_config = _read_file(path)
    _check_route_references(file_config)
    providers, disabled = _resolve_providers(file_config, environ)

    return GatewayConfig(
        deadline=file_config.gateway.deadline,
        default_completion_tokens=file_config.gateway.default_completion_tokens,
        routes=_resolve_routes(file_config, providers),
        enabled_providers=tuple(providers),
        disabled_providers=tuple(disabled),
    )


def _read_file(path: Path) -> FileConfig:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read config file {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    try:
        return FileConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"invalid config in {path}:\n{exc}") from exc


def _check_route_references(file_config: FileConfig) -> None:
    """Fail when a route references a `provider/model` that is not declared."""
    errors = []
    for alias, references in file_config.routes.items():
        for reference in references:
            provider_name, model = _split_reference(reference)
            provider_config = file_config.providers.get(provider_name)
            if provider_config is None or model not in provider_config.models:
                errors.append(
                    f"route '{alias}' references '{reference}', which is not a declared "
                    "provider/model"
                )
    if errors:
        raise ConfigError("\n".join(errors))


def _resolve_providers(
    file_config: FileConfig, environ: Mapping[str, str]
) -> tuple[dict[str, Provider], list[str]]:
    """Return enabled providers by name, and the names of disabled ones.

    A provider is disabled when it needs an API key and the key is not set.
    """
    providers: dict[str, Provider] = {}
    disabled: list[str] = []
    for name, provider_config in file_config.providers.items():
        api_key = _api_key(provider_config, environ)
        if provider_config.api_key_env is not None and api_key is None:
            logger.warning(
                "provider '%s' disabled: %s is not set", name, provider_config.api_key_env
            )
            disabled.append(name)
            continue
        providers[name] = Provider(
            name=name,
            base_url=provider_config.base_url,
            api_key=api_key,
            daily_reset=provider_config.daily_reset,
        )
    return providers, disabled


def _resolve_routes(
    file_config: FileConfig, providers: Mapping[str, Provider]
) -> dict[str, tuple[Target, ...]]:
    """Turn route references into targets. Targets of disabled providers are dropped."""
    routes: dict[str, tuple[Target, ...]] = {}
    for alias, references in file_config.routes.items():
        targets = []
        for reference in references:
            provider_name, model = _split_reference(reference)
            if provider_name in providers:
                limits = file_config.providers[provider_name].models[model]
                targets.append(Target(providers[provider_name], model, limits))
        routes[alias] = tuple(targets)
    return routes


def _split_reference(reference: str) -> tuple[str, str]:
    """Split `provider/model` on the first slash.

    Model names may contain slashes themselves (for example on OpenRouter:
    `openrouter/meta-llama/llama-3.3-70b-instruct:free`).
    """
    provider_name, _, model = reference.partition("/")
    return provider_name, model


def _api_key(provider_config: ProviderConfig, environ: Mapping[str, str]) -> SecretStr | None:
    if provider_config.api_key_env is None:
        return None
    value = environ.get(provider_config.api_key_env, "")
    return SecretStr(value) if value else None
