"""The PostgreSQL test fixture (TEST-031) empties every table it touches, so it must
only ever reach a throwaway database on this machine: CI's service container or a
local one. Checked without a database."""

import pytest

from tests.conftest import local_postgres_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://smartdoc:smartdoc@localhost:5432/smartdoc",
        "postgresql+asyncpg://tester:pw@127.0.0.1:55432/scratch",
    ],
)
def test_a_postgresql_on_this_machine_is_taken(url):
    assert local_postgres_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+asyncpg://user:pw@db.example.supabase.co:5432/postgres",  # a hosted database
        "postgresql+asyncpg://user:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres",
        "postgresql+asyncpg://user:pw@10.0.0.5:5432/smartdoc",  # another machine on the network
        "postgresql+asyncpg://user:pw@/smartdoc",  # no host: a socket, not necessarily ours
        "postgresql://user:pw@localhost:5432/smartdoc",  # not the app's driver
        "sqlite+aiosqlite:///tmp/test.db",
    ],
)
def test_anything_else_is_refused(url):
    with pytest.raises(ValueError):
        local_postgres_url(url)
