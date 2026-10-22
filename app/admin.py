"""Admin command line: manage tenants and their gateway API keys.

Usage:
    python -m app.admin create-key --tenant acme [--rpm 60] [--tokens-per-day 200000]
    python -m app.admin list-keys [--tenant acme]
    python -m app.admin revoke-key 12
    python -m app.admin set-limits --tenant acme [--rpm 120] [--tokens-per-day 500000]

A full key is printed only once, by create-key. Other commands show a short prefix.
It uses the same `DATABASE_URL` as the gateway.
"""

import argparse
import asyncio
import datetime as dt
import sys
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.storage.tenants import (
    ApiKeyInfo,
    Revocation,
    create_api_key,
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

    args = parser.parse_args(argv)
    if args.command == "set-limits" and args.rpm is None and args.tokens_per_day is None:
        set_limits.error("give at least one limit: --rpm and/or --tokens-per-day")
    if args.command == "create-key":
        return asyncio.run(_create_key(args.tenant, args.rpm, args.tokens_per_day))
    if args.command == "list-keys":
        return asyncio.run(_list_keys(args.tenant))
    if args.command == "revoke-key":
        return asyncio.run(_revoke_key(args.id))
    if args.command == "set-limits":
        return asyncio.run(_set_limits(args.tenant, args.rpm, args.tokens_per_day))
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
        new_key = await create_api_key(engine, tenant, rpm=rpm, tokens_per_day=tokens_per_day)
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
        revocation = await revoke_api_key(engine, api_key_id)
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
        found = await set_tenant_limits(engine, tenant, rpm=rpm, tokens_per_day=tokens_per_day)
    finally:
        await engine.dispose()
    if not found:
        print(f"Error: unknown tenant '{tenant}'.", file=sys.stderr)
        return 1
    changes = []
    if rpm is not None:
        changes.append(f"{rpm} requests per minute")
    if tokens_per_day is not None:
        changes.append(f"{tokens_per_day} tokens per day")
    print(f"Limits of tenant '{tenant}' updated: {', '.join(changes)}.")
    return 0


def _positive_int(value: str) -> int:
    """Parse a limit given on the command line: a whole number above zero."""
    if not value.isdigit() or int(value) == 0:
        raise argparse.ArgumentTypeError(f"must be a positive whole number, got {value!r}")
    return int(value)


KEY_COLUMNS = ("ID", "TENANT", "PREFIX", "CREATED (UTC)", "LAST USED (UTC)", "STATUS")


def _keys_table(keys: Sequence[ApiKeyInfo]) -> str:
    """Format keys as a table with aligned columns, separated by two spaces."""
    rows = [KEY_COLUMNS] + [
        (
            str(key.id),
            key.tenant_name,
            key.prefix,
            _utc_minute(key.created_at),
            _utc_minute(key.last_used_at) if key.last_used_at else "never",
            "revoked" if key.revoked_at else "active",
        )
        for key in keys
    ]
    widths = [max(len(row[column]) for row in rows) for column in range(len(KEY_COLUMNS))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def _utc_minute(moment: dt.datetime) -> str:
    """Format a moment as `YYYY-MM-DD HH:MM` in UTC."""
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%d %H:%M")


if __name__ == "__main__":
    sys.exit(main())
