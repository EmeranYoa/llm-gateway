"""Admin command line: manage tenants and their gateway API keys.

Usage:
    python -m app.admin create-key --tenant acme

It uses the same `DATABASE_URL` as the gateway.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.storage.tenants import create_api_key


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

    args = parser.parse_args(argv)
    if args.command == "create-key":
        return asyncio.run(_create_key(args.tenant))
    return 1


async def _create_key(tenant: str) -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        new_key = await create_api_key(engine, tenant)
    finally:
        await engine.dispose()
    print(f"API key for tenant '{tenant}' (shown only once, store it now):")
    print(new_key.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
