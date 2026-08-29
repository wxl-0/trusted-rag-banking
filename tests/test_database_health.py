import os
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-api-key")

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.readiness import ReadinessChecker, get_readiness_checker


class _ReadyComponent:
    def ping(self):
        return None


class _UnavailableComponent:
    def ping(self):
        raise RuntimeError("postgresql://user:secret@database/internal")


class _ReadyQueue(_ReadyComponent):
    def worker_alive(self):
        return True


class _UnavailableQueue(_UnavailableComponent):
    def worker_alive(self):
        return False


def _get(path: str, checker):
    app.dependency_overrides[get_readiness_checker] = lambda: checker
    try:
        with TestClient(app) as client:
            return client.get(path)
    finally:
        app.dependency_overrides.pop(get_readiness_checker, None)


def test_liveness_does_not_require_postgresql():
    response = _get("/api/health", None)

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_all_required_services_available():
    ready = _ReadyComponent()
    response = _get(
        "/api/ready",
        ReadinessChecker(ready, _ReadyQueue(), ready, ready),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "postgresql": "available",
            "redis": "available",
            "minio": "available",
            "qdrant": "available",
            "worker": "available",
        },
    }


def test_readiness_reports_each_failure_without_internal_details():
    unavailable = _UnavailableComponent()
    response = _get(
        "/api/ready",
        ReadinessChecker(
            unavailable,
            _UnavailableQueue(),
            unavailable,
            unavailable,
        ),
    )

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "postgresql": "unavailable",
            "redis": "unavailable",
            "minio": "unavailable",
            "qdrant": "unavailable",
            "worker": "unavailable",
        },
    }
    assert "secret" not in response.text
