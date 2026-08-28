import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

os.environ.setdefault("OPENAI_API_KEY", "test-api-key")

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.database import Database, get_database


def test_alembic_upgrades_an_empty_postgresql_database(migrated_postgres_url):
    engine = create_engine(migrated_postgres_url)
    try:
        assert inspect(engine).get_table_names() == ["alembic_version"]
    finally:
        engine.dispose()


def test_readiness_uses_the_migrated_postgresql_database(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    app.dependency_overrides[get_database] = lambda: database
    try:
        with TestClient(app) as client:
            response = client.get("/api/ready")
    finally:
        app.dependency_overrides.pop(get_database, None)
        database.dispose()

    assert response.status_code == 200
    assert response.json()["checks"] == {"postgresql": "available"}
