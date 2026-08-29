from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_backend_container_does_not_require_private_bootstrap_data():
    dockerfile = (ROOT / "Dockerfile.backend").read_text(encoding="utf-8")
    entrypoint = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")

    assert "COPY data/manifest.json" not in dockerfile
    assert "COPY data/chunks" not in dockerfile
    assert "scripts/build_index.py" not in entrypoint
    assert "alembic upgrade head" in entrypoint
    assert "src.api.main:app" in entrypoint


def test_docker_build_context_excludes_private_runtime_artifacts():
    dockerignore = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".env",
        "models",
        "outputs",
        "data/manifest.json",
        "data/chunks",
        "data/eval",
        "data/qdrant_snapshots",
        "src/frontend/dist",
        "*.pkl",
        "*.snapshot",
    } <= dockerignore


def test_compose_orders_the_full_stack_by_readiness():
    compose = yaml.safe_load(
        (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]

    for name in (
        "postgres",
        "keycloak",
        "redis",
        "minio",
        "qdrant",
        "backend",
        "ingestion-worker",
        "frontend",
    ):
        assert "healthcheck" in services[name], name

    for dependency in ("postgres", "redis", "minio", "qdrant"):
        assert services["backend"]["depends_on"][dependency]["condition"] == (
            "service_healthy"
        )
        assert services["ingestion-worker"]["depends_on"][dependency][
            "condition"
        ] == "service_healthy"

    assert services["frontend"]["depends_on"]["backend"]["condition"] == (
        "service_healthy"
    )
    assert services["frontend"]["depends_on"]["keycloak"]["condition"] == (
        "service_healthy"
    )
    assert set(compose["volumes"]) == {
        "postgres_data",
        "redis_data",
        "minio_data",
        "qdrant_data",
    }
