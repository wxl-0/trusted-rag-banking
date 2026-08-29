import os
from functools import lru_cache

from fastapi import Depends
from qdrant_client import QdrantClient

from src.database import Database, get_database
from src.document_uploads import (
    MinioObjectStore,
    RedisIngestionQueue,
    get_ingestion_queue,
    get_object_store,
)


class QdrantProbe:
    def __init__(self):
        self.client = QdrantClient(
            host=os.getenv("QDRANT_HOST", "localhost"),
            port=int(os.getenv("QDRANT_PORT", "6333")),
            timeout=5,
            trust_env=False,
        )

    def ping(self) -> None:
        self.client.get_collections()


@lru_cache(maxsize=1)
def get_qdrant_probe() -> QdrantProbe:
    return QdrantProbe()


class ReadinessChecker:
    def __init__(self, database, queue, object_store, qdrant):
        self.database = database
        self.queue = queue
        self.object_store = object_store
        self.qdrant = qdrant

    def check(self) -> dict[str, str]:
        checks = {
            "postgresql": self._status(self.database.ping),
            "redis": self._status(self.queue.ping),
            "minio": self._status(self.object_store.ping),
            "qdrant": self._status(self.qdrant.ping),
            "worker": self._worker_status(),
        }
        return checks

    @staticmethod
    def _status(probe) -> str:
        try:
            probe()
        except Exception:
            return "unavailable"
        return "available"

    def _worker_status(self) -> str:
        try:
            return "available" if self.queue.worker_alive() else "unavailable"
        except Exception:
            return "unavailable"


def get_readiness_checker(
    database: Database = Depends(get_database),
    queue: RedisIngestionQueue = Depends(get_ingestion_queue),
    object_store: MinioObjectStore = Depends(get_object_store),
    qdrant: QdrantProbe = Depends(get_qdrant_probe),
) -> ReadinessChecker:
    return ReadinessChecker(database, queue, object_store, qdrant)
