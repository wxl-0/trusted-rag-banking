import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


TEST_DATABASE_ENV = "TRUSTED_RAG_TEST_DATABASE_URL"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _reset_public_schema(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()


@pytest.fixture
def migrated_postgres_url(monkeypatch) -> str:
    database_url = os.getenv(TEST_DATABASE_ENV)
    if not database_url:
        pytest.skip(f"{TEST_DATABASE_ENV} is not configured")

    database_name = make_url(database_url).database or ""
    if not database_name.endswith("_test"):
        pytest.fail(f"{TEST_DATABASE_ENV} must target a database ending in _test")

    _reset_public_schema(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")

    try:
        yield database_url
    finally:
        _reset_public_schema(database_url)
