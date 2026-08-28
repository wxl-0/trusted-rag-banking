import os
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-api-key")

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.database import get_database


class _ReadyDatabase:
    def ping(self):
        return None


class _UnavailableDatabase:
    def ping(self):
        raise RuntimeError("postgresql://user:secret@database/internal")


def _get(path: str, database):
    app.dependency_overrides[get_database] = lambda: database
    try:
        with TestClient(app) as client:
            return client.get(path)
    finally:
        app.dependency_overrides.pop(get_database, None)


def test_liveness_does_not_require_postgresql():
    response = _get("/api/health", _UnavailableDatabase())

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_postgresql_available():
    response = _get("/api/ready", _ReadyDatabase())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"postgresql": "available"},
    }


def test_readiness_fails_safely_when_postgresql_is_unavailable():
    response = _get("/api/ready", _UnavailableDatabase())

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"postgresql": "unavailable"},
    }
    assert "secret" not in response.text
