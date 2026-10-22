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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class ConfigError(Exception):
    """The gateway configuration is invalid. The gateway must not start."""


class Settings(BaseSettings):
    """Settings read from environment variables."""

    gateway_config_path: Path = Path("config/gateway.yaml")
    # Default: the PostgreSQL started by docker compose, seen from the host.
    database_url: str = "postgresql+asyncpg://gateway:gateway@localhost:5432/gateway"
    # Seconds to wait for PostgreSQL to connect or answer a query. A usage log
    # write gives up after that, instead of hanging when the database is stuck.
    database_timeout: float = Field(default=5.0, gt=0)
    # Default: the Redis started by docker compose, seen from the host.
    redis_url: str = "redis://localhost:6379/0"
    # Seconds to wait for Redis before routing without it (degraded mode, ADR 0002).
    redis_timeout: float = Field(default=0.25, gt=0)
    # Seconds a verified API key is trusted without a new database check. A revoked
    # key or a new tenant limit takes effect within that time (ADR 0004).
    auth_cache_ttl: float = Field(default=60.0, gt=0)
    # Seconds a verified API key keeps working while PostgreSQL is unavailable. A key
    # not verified within that time is refused until the database is back (ADR 0004).
    auth_grace_period: float = Field(default=900.0, gt=0)


# --- File format (what `gateway.yaml` looks like) ---


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyReset(_FileModel):
    """Time of day when a provider resets its daily quota."""

    time: dt.time = dt.time(0, 0)
    timezone: str = "UTC"

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value


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


class CooldownSection(_FileModel):
    """How long a target is skipped after a 429 or a misconfiguration error, in seconds."""

    initial: float = Field(default=60.0, gt=0)
    """First cooldown after a 429 without a retry delay. It doubles on each consecutive 429."""
    max: float = Field(default=3600.0, gt=0)
    """Upper bound of the progressive cooldown."""
    misconfigured: float = Field(default=600.0, gt=0)
    """Cooldown after a 401, 403 or 404: a bad key or a removed model does not fix itself."""

    @model_validator(mode="after")
    def _max_not_below_initial(self) -> "CooldownSection":
        if self.max < self.initial:
            raise ValueError("cooldown max must not be lower than cooldown initial")
        return self


class BreakerSection(_FileModel):
    """Circuit breaker settings, shared by every target."""

    failures: int = Field(default=5, gt=0)
    """Failures (5xx, network error, timeout) within `window` that open the breaker."""
    window: float = Field(default=60.0, gt=0)
    """Sliding window, in seconds, in which failures are counted."""
    open: float = Field(default=30.0, gt=0)
    """Seconds the breaker stays open before it lets a single trial call through."""


class StreamSection(_FileModel):
    """Limits of a streamed answer after its first content, in seconds.

    Before the first content, the model timeout and the request deadline apply as
    usual. After it, the deadline would cut long answers, so these replace it.
    """

    idle_timeout: float = Field(default=30.0, gt=0)
    """Longest silence allowed between two events of the provider."""
    max_duration: float = Field(default=600.0, gt=0)
    """Longest time a stream may last after its first content."""


class GatewaySection(_FileModel):
    deadline: float = Field(default=60.0, gt=0)
    min_attempt_time: float = Field(default=1.0, gt=0)
    default_completion_tokens: int = Field(default=512, gt=0)
    cooldown: CooldownSection = CooldownSection()
    breaker: BreakerSection = BreakerSection()
    stream: StreamSection = StreamSection()

    @model_validator(mode="after")
    def _attempts_fit_in_deadline(self) -> "GatewaySection":
        # Otherwise no request could ever start an attempt.
        if self.min_attempt_time >= self.deadline:
            raise ValueError("min_attempt_time must be lower than deadline")
        return self


class TenantLimits(_FileModel):
    """Quotas of a tenant. A missing limit means "no limit"."""

    rpm: int | None = Field(default=None, gt=0)
    """Requests per minute, over a 60 s sliding window."""
    tokens_per_day: int | None = Field(default=None, gt=0)
    """Daily token budget (prompt and completion), reset at 00:00 UTC."""


class TenantsSection(_FileModel):
    default_limits: TenantLimits = TenantLimits()
    """Limits of every tenant that has no limits of its own (set with `set-limits`)."""


class FileConfig(_FileModel):
    gateway: GatewaySection = GatewaySection()
    tenants: TenantsSection = TenantsSection()
    providers: dict[str, ProviderConfig]
    routes: dict[str, list[str]]


# --- Resolved configuration (what the rest of the gateway uses) ---


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    base_url: str
    api_key: SecretStr | None
    daily_reset: DailyReset


@dataclass(frozen=True)
class Target:
    """One real `provider/model` pair that can serve an alias."""

    provider: ProviderSettings
    model: str
    limits: ModelConfig

    @property
    def name(self) -> str:
        return f"{self.provider.name}/{self.model}"


@dataclass(frozen=True)
class GatewayConfig:
    deadline: float
    """Maximum time in seconds for a whole request, failovers included."""
    min_attempt_time: float
    """No new attempt starts when less than this many seconds remain before the deadline."""
    default_completion_tokens: int
    cooldown: CooldownSection
    breaker: BreakerSection
    stream: StreamSection
    tenant_default_limits: TenantLimits
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
        min_attempt_time=file_config.gateway.min_attempt_time,
        default_completion_tokens=file_config.gateway.default_completion_tokens,
        cooldown=file_config.gateway.cooldown,
        breaker=file_config.gateway.breaker,
        stream=file_config.gateway.stream,
        tenant_default_limits=file_config.tenants.default_limits,
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
) -> tuple[dict[str, ProviderSettings], list[str]]:
    """Return enabled providers by name, and the names of disabled ones.

    A provider is disabled when it needs an API key and the key is not set.
    """
    providers: dict[str, ProviderSettings] = {}
    disabled: list[str] = []
    for name, provider_config in file_config.providers.items():
        api_key = _api_key(provider_config, environ)
        if provider_config.api_key_env is not None and api_key is None:
            logger.warning(
                "provider '%s' disabled: %s is not set", name, provider_config.api_key_env
            )
            disabled.append(name)
            continue
        providers[name] = ProviderSettings(
            name=name,
            base_url=provider_config.base_url,
            api_key=api_key,
            daily_reset=provider_config.daily_reset,
        )
    return providers, disabled


def _resolve_routes(
    file_config: FileConfig, providers: Mapping[str, ProviderSettings]
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
