import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

os.environ.setdefault("OPENAI_API_KEY", "test-api-key")

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.database import Database
from src.readiness import ReadinessChecker, get_readiness_checker


class _ReadyComponent:
    def ping(self):
        return None

    def worker_alive(self):
        return True


def test_alembic_upgrades_an_empty_postgresql_database(migrated_postgres_url):
    engine = create_engine(migrated_postgres_url)
    try:
        inspector = inspect(engine)
        assert set(inspector.get_table_names()) == {
            "alembic_version",
            "audit_events",
            "bm25_generations",
            "conversation_messages",
            "conversations",
            "document_version_artifacts",
            "document_versions",
            "ingestion_tasks",
            "knowledge_index_state",
            "knowledge_documents",
        }
        assert {
            "idempotency_key",
            "attempt_count",
            "lease_token",
            "lease_expires_at",
            "result_code",
        }.issubset({
            column["name"]
            for column in inspector.get_columns("ingestion_tasks")
        })
    finally:
        engine.dispose()


def test_readiness_uses_the_migrated_postgresql_database(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    ready = _ReadyComponent()
    app.dependency_overrides[get_readiness_checker] = lambda: ReadinessChecker(
        database,
        ready,
        ready,
        ready,
    )
    try:
        with TestClient(app) as client:
            response = client.get("/api/ready")
    finally:
        app.dependency_overrides.pop(get_readiness_checker, None)
        database.dispose()

    assert response.status_code == 200
    assert response.json()["checks"] == {
        "postgresql": "available",
        "redis": "available",
        "minio": "available",
        "qdrant": "available",
        "worker": "available",
    }
