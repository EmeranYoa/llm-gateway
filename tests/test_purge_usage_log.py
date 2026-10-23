"""Tests for `purge-usage-log`: an operator deletes old usage rows with the admin CLI."""

import datetime as dt
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.storage.tenants import create_api_key
from app.storage.usage import UsageLogRow, purge_usage_rows
from tests.conftest import FetchUsageRows, run_admin, run_admin_command

FetchActions = Callable[[], Awaitable[list[dict[str, Any]]]]

NOW = dt.datetime.now(dt.UTC)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
async def purge_actions(engine: AsyncEngine) -> FetchActions:
    """Remove earlier purge actions, then return a function that reads the new ones in order."""
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM admin_actions WHERE action = 'purge-usage-log'"))

    async def _fetch() -> list[dict[str, Any]]:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT * FROM admin_actions WHERE action = 'purge-usage-log' ORDER BY id")
            )
            return [dict(row) for row in result.mappings()]

    return _fetch


async def add_usage_rows(engine: AsyncEngine, *created_at: dt.datetime) -> None:
    """Insert one usage row per moment, each with its own request id."""
    async with engine.begin() as connection:
        await connection.execute(
            insert(UsageLogRow).values(
                [
                    {
                        "request_id": uuid4().hex,
                        "created_at": moment,
                        "alias": "chat-fast",
                        "attempt_index": 0,
                        "outcome": "success",
                        "prompt_chars": 10,
                    }
                    for moment in created_at
                ]
            )
        )


async def count_rows(engine: AsyncEngine, table: str) -> int:
    async with engine.connect() as connection:
        return int(await connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0)


def days_ago(days: float) -> dt.datetime:
    return NOW - dt.timedelta(days=days)


# --- Storage function ---


async def test_purge_deletes_only_rows_older_than_the_cutoff(
    engine: AsyncEngine, usage_rows: FetchUsageRows
) -> None:
    cutoff = days_ago(30)
    one_microsecond = dt.timedelta(microseconds=1)
    await add_usage_rows(engine, days_ago(400), cutoff - one_microsecond, cutoff, days_ago(1))

    deleted = await purge_usage_rows(engine, cutoff)

    assert deleted == 2
    # A row created exactly at the cutoff is not older than it: it stays.
    assert [row["created_at"] for row in await usage_rows()] == [cutoff, days_ago(1)]


async def test_purge_deletes_in_batches_each_in_its_own_transaction(
    engine: AsyncEngine, usage_rows: FetchUsageRows
) -> None:
    await add_usage_rows(engine, *[days_ago(100 + index) for index in range(5)], days_ago(1))
    deletes: list[str] = []
    commits: list[None] = []

    def on_execute(*args: Any) -> None:
        statement = args[2]
        if statement.lstrip().upper().startswith("DELETE"):
            deletes.append(statement)

    def on_commit(_: Any) -> None:
        commits.append(None)

    event.listen(engine.sync_engine, "before_cursor_execute", on_execute)
    event.listen(engine.sync_engine, "commit", on_commit)
    deleted = await purge_usage_rows(engine, days_ago(30), batch_size=2)

    assert deleted == 5
    # Batches of 2, 2 and 1 rows: a batch smaller than the limit is the last one.
    assert len(deletes) == 3
    assert len(commits) == 3
    assert [row["created_at"] for row in await usage_rows()] == [days_ago(1)]


async def test_purge_with_nothing_old_deletes_nothing(
    engine: AsyncEngine, usage_rows: FetchUsageRows
) -> None:
    await add_usage_rows(engine, days_ago(1))

    assert await purge_usage_rows(engine, days_ago(30)) == 0
    assert len(await usage_rows()) == 1


async def test_purge_leaves_other_tables_untouched(
    engine: AsyncEngine, usage_rows: FetchUsageRows
) -> None:
    new_key = await create_api_key(engine, f"tenant-{uuid4().hex[:8]}")
    async with engine.begin() as connection:
        await connection.execute(
            insert(UsageLogRow).values(
                request_id=uuid4().hex,
                created_at=days_ago(100),
                tenant_id=new_key.owner.tenant_id,
                api_key_id=new_key.owner.api_key_id,
                alias="chat-fast",
                attempt_index=0,
                outcome="success",
                prompt_chars=10,
            )
        )
    tables = ("tenants", "api_keys", "admin_keys", "admin_actions")
    before = {table: await count_rows(engine, table) for table in tables}

    assert await purge_usage_rows(engine, days_ago(30)) == 1

    assert await usage_rows() == []
    assert {table: await count_rows(engine, table) for table in tables} == before


# --- Admin CLI ---


async def test_cli_deletes_old_rows_and_prints_how_many(
    database_url: str, engine: AsyncEngine, usage_rows: FetchUsageRows
) -> None:
    await add_usage_rows(engine, days_ago(200), days_ago(91), days_ago(89), days_ago(1))

    output = await run_admin(database_url, "purge-usage-log", "--older-than-days", "90")

    assert output.strip() == "Deleted 2 usage rows older than 90 days."
    assert [row["created_at"] for row in await usage_rows()] == [days_ago(89), days_ago(1)]


async def test_cli_uses_singular_words_for_one(
    database_url: str, engine: AsyncEngine, usage_rows: FetchUsageRows
) -> None:
    await add_usage_rows(engine, days_ago(3))

    output = await run_admin(database_url, "purge-usage-log", "--older-than-days", "1")

    assert output.strip() == "Deleted 1 usage row older than 1 day."
    assert await usage_rows() == []


async def test_cli_records_the_purge_as_an_admin_action(
    database_url: str,
    engine: AsyncEngine,
    usage_rows: FetchUsageRows,
    purge_actions: FetchActions,
) -> None:
    await add_usage_rows(engine, days_ago(40), days_ago(35), days_ago(5))
    started = dt.datetime.now(dt.UTC)

    await run_admin(database_url, "purge-usage-log", "--older-than-days", "30")

    finished = dt.datetime.now(dt.UTC)
    [action] = await purge_actions()
    assert action["actor"] == "cli"
    assert action["admin_key_id"] is None
    assert action["target"] is None
    assert set(action["details"]) == {"older_than_days", "deleted", "cutoff"}
    assert action["details"]["older_than_days"] == 30
    assert action["details"]["deleted"] == 2
    cutoff = dt.datetime.fromisoformat(action["details"]["cutoff"])
    assert cutoff.utcoffset() == dt.timedelta(0)
    thirty_days = dt.timedelta(days=30)
    assert started - thirty_days <= cutoff <= finished - thirty_days
    # The action is recorded after the deletion.
    assert action["created_at"] >= cutoff + thirty_days


async def test_cli_records_a_purge_that_found_nothing(
    database_url: str,
    engine: AsyncEngine,
    usage_rows: FetchUsageRows,
    purge_actions: FetchActions,
) -> None:
    output = await run_admin(database_url, "purge-usage-log", "--older-than-days", "7")

    assert output.strip() == "Deleted 0 usage rows older than 7 days."
    [action] = await purge_actions()
    assert action["details"]["deleted"] == 0


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--older-than-days"],
        ["--older-than-days", "0"],
        ["--older-than-days", "-5"],
        ["--older-than-days", "1.5"],
        ["--older-than-days", "ninety"],
    ],
)
async def test_cli_refuses_a_missing_or_invalid_number_of_days(
    database_url: str,
    engine: AsyncEngine,
    usage_rows: FetchUsageRows,
    purge_actions: FetchActions,
    arguments: list[str],
) -> None:
    await add_usage_rows(engine, days_ago(400))

    run = await run_admin_command(database_url, "purge-usage-log", *arguments)

    assert run.exit_code == 2
    assert "--older-than-days" in run.stderr
    assert len(await usage_rows()) == 1
    assert await purge_actions() == []
