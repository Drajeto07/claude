import pytest

from app.config import Settings

_POOLER = "postgres.abc:secret@aws-1-eu-central-1.pooler.supabase.com:5432/postgres"


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
def test_remote_postgres_url_gets_asyncpg_driver_and_required_tls(scheme):
    settings = Settings(database_url=f"{scheme}://{_POOLER}")
    assert settings.database_url == f"postgresql+asyncpg://{_POOLER}?ssl=require"


def test_explicit_ssl_setting_is_left_alone():
    settings = Settings(database_url="postgresql://u:p@db.example.com/app?ssl=disable")
    assert settings.database_url == "postgresql+asyncpg://u:p@db.example.com/app?ssl=disable"


def test_local_postgres_does_not_require_tls():
    settings = Settings(database_url="postgresql://u:p@localhost:5432/app")
    assert settings.database_url == "postgresql+asyncpg://u:p@localhost:5432/app"


def test_url_encoded_password_survives_normalization():
    settings = Settings(database_url="postgresql://u:p%40ss%2Fword@db.example.com/app")
    assert settings.database_url.startswith("postgresql+asyncpg://u:p%40ss%2Fword@db.example.com/app")


def test_non_postgres_url_is_untouched():
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    assert settings.database_url == "sqlite+aiosqlite:///:memory:"
