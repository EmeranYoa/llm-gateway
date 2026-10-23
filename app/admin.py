"""Admin command line: manage tenants, their gateway API keys and their cached answers,
and the admin keys of operators.

Usage:
    python -m app.admin create-key --tenant acme [--rpm 60] [--tokens-per-day 200000]
    python -m app.admin list-keys [--tenant acme]
    python -m app.admin revoke-key 12
    python -m app.admin set-limits --tenant acme [--rpm 120] [--tokens-per-day 500000]
    python -m app.admin clear-cache --tenant acme [--alias chat-fast]
    python -m app.admin clear-cache --all
    python -m app.admin create-admin-key --name alice
    python -m app.admin list-admin-keys
    python -m app.admin revoke-admin-key 3

A full key is printed only once, by create-key or create-admin-key. Other commands
show a short prefix. Admin keys (`gwa_`) open the admin API only, never the gateway;
they can only be created here, never through the web. Every change is recorded in
the history of admin actions, with `cli` as the actor.
It uses the same `DATABASE_URL` and `REDIS_URL` as the gateway.
"""

import argparse
import asyncio
import datetime as dt
import sys
from collections.abc import Sequence

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import create_async_engine

from app.cache.store import ResponseCache
from app.config import Settings
from app.storage.admin_actions import CLI, record_cache_clear
from app.storage.admin_keys import (
    AdminKeyInfo,
    create_admin_key,
    list_admin_keys,
    revoke_admin_key,
)
from app.storage.tenants import (
    ApiKeyInfo,
    Revocation,
    create_api_key,
    find_tenant_id,
    list_api_keys,
    revoke_api_key,
    set_tenant_limits,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one admin command. Returns the process exit code."""
    parser = argparse.ArgumentParser(
        prog="python -m app.admin", description="Manage tenants and gateway API keys."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "create-key", help="create an API key (and the tenant if needed), and print it once"
    )
    create.add_argument("--tenant", required=True, help="tenant name, for example acme")
    _add_limit_arguments(create)

    list_keys = commands.add_parser(
        "list-keys", help="list API keys with their prefix and status, never the full key"
    )
    list_keys.add_argument("--tenant", help="only list the keys of this tenant")

    revoke = commands.add_parser("revoke-key", help="revoke an API key: requests with it get 401")
    revoke.add_argument("id", type=int, help="key id, as shown by list-keys")

    set_limits = commands.add_parser(
        "set-limits", help="set the tenant's own limits, instead of the defaults of gateway.yaml"
    )
    set_limits.add_argument("--tenant", required=True, help="tenant name")
    _add_limit_arguments(set_limits)

    clear_cache = commands.add_parser(
        "clear-cache", help="remove cached answers of one tenant, or of every tenant"
    )
    scope = clear_cache.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tenant", help="tenant name: remove only the answers of this tenant")
    scope.add_argument("--all", action="store_true", help="remove the answers of every tenant")
    clear_cache.add_argument("--alias", help="with --tenant: remove only the answers of this alias")

    create_admin = commands.add_parser(
        "create-admin-key", help="create an admin key for an operator, and print it once"
    )
    create_admin.add_argument("--name", required=True, help="who the key is for, e.g. alice")

    commands.add_parser(
        "list-admin-keys", help="list admin keys with their prefix and status, never the full key"
    )

    revoke_admin = commands.add_parser(
        "revoke-admin-key", help="revoke an admin key: the admin API refuses it"
    )
    revoke_admin.add_argument("id", type=int, help="admin key id, as shown by list-admin-keys")

    args = parser.parse_args(argv)
    if args.command == "set-limits" and args.rpm is None and args.tokens_per_day is None:
        set_limits.error("give at least one limit: --rpm and/or --tokens-per-day")
    if args.command == "clear-cache" and args.alias is not None and args.tenant is None:
        clear_cache.error("--alias needs --tenant: an alias is cleared for one tenant")
    if args.command == "create-key":
        return asyncio.run(_create_key(args.tenant, args.rpm, args.tokens_per_day))
    if args.command == "list-keys":
        return asyncio.run(_list_keys(args.tenant))
    if args.command == "revoke-key":
        return asyncio.run(_revoke_key(args.id))
    if args.command == "set-limits":
        return asyncio.run(_set_limits(args.tenant, args.rpm, args.tokens_per_day))
    if args.command == "clear-cache":
        return asyncio.run(_clear_cache(args.tenant, args.alias))
    if args.command == "create-admin-key":
        return asyncio.run(_create_admin_key(args.name))
    if args.command == "list-admin-keys":
        return asyncio.run(_list_admin_keys())
    if args.command == "revoke-admin-key":
        return asyncio.run(_revoke_admin_key(args.id))
    return 1


def _add_limit_arguments(command: argparse.ArgumentParser) -> None:
    """Add the tenant limit options. A limit left out keeps its current value."""
    command.add_argument("--rpm", type=_positive_int, help="requests per minute of the tenant")
    command.add_argument(
        "--tokens-per-day",
        type=_positive_int,
        help="daily token budget of the tenant (prompt and completion), reset at 00:00 UTC",
    )


async def _create_key(tenant: str, rpm: int | None, tokens_per_day: int | None) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        new_key = await create_api_key(
            engine, tenant, rpm=rpm, tokens_per_day=tokens_per_day, actor=CLI
        )
    finally:
        await engine.dispose()
    print(f"API key for tenant '{tenant}' (shown only once, store it now):")
    print(new_key.key)
    return 0


async def _list_keys(tenant: str | None) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        keys = await list_api_keys(engine, tenant)
    finally:
        await engine.dispose()
    print(_keys_table(keys))
    return 0


async def _revoke_key(api_key_id: int) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        revocation = await revoke_api_key(engine, api_key_id, actor=CLI)
    finally:
        await engine.dispose()
    match revocation:
        case Revocation.REVOKED:
            print(f"API key {api_key_id} revoked.")
            return 0
        case Revocation.NOT_FOUND:
            print(f"Error: no API key with id {api_key_id}.", file=sys.stderr)
        case Revocation.ALREADY_REVOKED:
            print(f"Error: API key {api_key_id} is already revoked.", file=sys.stderr)
    return 1


async def _set_limits(tenant: str, rpm: int | None, tokens_per_day: int | None) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        limits = await set_tenant_limits(
            engine, tenant, rpm=rpm, tokens_per_day=tokens_per_day, actor=CLI
        )
    finally:
        await engine.dispose()
    if limits is None:
        print(f"Error: unknown tenant '{tenant}'.", file=sys.stderr)
        return 1
    changes = []
    if rpm is not None:
        changes.append(f"{rpm} requests per minute")
    if tokens_per_day is not None:
        changes.append(f"{tokens_per_day} tokens per day")
    print(f"Limits of tenant '{tenant}' updated: {', '.join(changes)}.")
    return 0


async def _clear_cache(tenant: str | None, alias: str | None) -> int:
    """Remove the cached answers of `tenant` (every tenant if None), or of one of its aliases."""
    settings = Settings()
    engine = create_async_engine(settings.database_url)
    try:
        tenant_id = None
        if tenant is not None:
            tenant_id = await find_tenant_id(engine, tenant)
            if tenant_id is None:
                print(f"Error: unknown tenant '{tenant}'.", file=sys.stderr)
                return 1
        redis = Redis.from_url(settings.redis_url)
        try:
            # Clearing needs no alias settings: those only matter to store answers.
            removed = await ResponseCache(redis, cached_aliases={}).clear(tenant_id, alias)
        finally:
            await redis.aclose()
        await record_cache_clear(engine, CLI, tenant, alias, removed)
    finally:
        await engine.dispose()
    print(f"Removed {removed} cached {'answer' if removed == 1 else 'answers'}.")
    return 0


async def _create_admin_key(name: str) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        new_key = await create_admin_key(engine, name, actor=CLI)
    finally:
        await engine.dispose()
    print(f"Admin key for '{name}' (shown only once, store it now):")
    print(new_key.key)
    return 0


async def _list_admin_keys() -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        keys = await list_admin_keys(engine)
    finally:
        await engine.dispose()
    print(_admin_keys_table(keys))
    return 0


async def _revoke_admin_key(admin_key_id: int) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        revocation = await revoke_admin_key(engine, admin_key_id, actor=CLI)
    finally:
        await engine.dispose()
    match revocation:
        case Revocation.REVOKED:
            print(f"Admin key {admin_key_id} revoked.")
            return 0
        case Revocation.NOT_FOUND:
            print(f"Error: no admin key with id {admin_key_id}.", file=sys.stderr)
        case Revocation.ALREADY_REVOKED:
            print(f"Error: admin key {admin_key_id} is already revoked.", file=sys.stderr)
    return 1


def _positive_int(value: str) -> int:
    """Parse a limit given on the command line: a whole number above zero."""
    if not value.isdigit() or int(value) == 0:
        raise argparse.ArgumentTypeError(f"must be a positive whole number, got {value!r}")
    return int(value)


KEY_COLUMNS = ("ID", "TENANT", "PREFIX", "CREATED (UTC)", "LAST USED (UTC)", "STATUS")
ADMIN_KEY_COLUMNS = ("ID", "NAME", "PREFIX", "CREATED (UTC)", "LAST USED (UTC)", "STATUS")


def _keys_table(keys: Sequence[ApiKeyInfo]) -> str:
    """Format tenant keys as a table."""
    return _table(
        KEY_COLUMNS,
        [(str(key.id), key.tenant_name, key.prefix, *_key_dates(key)) for key in keys],
    )


def _admin_keys_table(keys: Sequence[AdminKeyInfo]) -> str:
    """Format admin keys as a table."""
    return _table(
        ADMIN_KEY_COLUMNS,
        [(str(key.id), key.name, key.prefix, *_key_dates(key)) for key in keys],
    )


def _key_dates(key: ApiKeyInfo | AdminKeyInfo) -> tuple[str, str, str]:
    """Creation, last use and status of a key, as table cells."""
    return (
        _utc_minute(key.created_at),
        _utc_minute(key.last_used_at) if key.last_used_at else "never",
        "revoked" if key.revoked_at else "active",
    )


def _table(columns: Sequence[str], cells: Sequence[Sequence[str]]) -> str:
    """Format rows as a table with aligned columns, separated by two spaces."""
    rows = [columns, *cells]
    widths = [max(len(row[column]) for row in rows) for column in range(len(columns))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def _utc_minute(moment: dt.datetime) -> str:
    """Format a moment as `YYYY-MM-DD HH:MM` in UTC."""
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    sys.exit(main())
