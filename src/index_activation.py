import os
from contextlib import contextmanager

from redis import Redis
from redis.exceptions import LockNotOwnedError
from sqlalchemy import text


class ActivationConflict(RuntimeError):
    pass


class RedisActivationLock:
    def __init__(self, client=None):
        self.client = client or Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )

    @contextmanager
    def hold(self, document_id):
        lock = self.client.lock(
            f"trusted-rag:activation:{document_id}",
            timeout=30,
            blocking_timeout=5,
        )
        if not lock.acquire(blocking=True):
            raise ActivationConflict("activation lock unavailable")
        try:
            yield
        finally:
            try:
                lock.release()
            except LockNotOwnedError:
                pass


class VersionPublisher:
    def __init__(self, database, coordination_lock):
        self.database = database
        self.coordination_lock = coordination_lock

    def publish(
        self,
        *,
        document_id,
        version_id,
        task_id,
        generation_id,
        chunk_count: int,
        expected_current_version_id,
        expected_generation_id,
        lease_token=None,
    ) -> None:
        try:
            with self.coordination_lock.hold(document_id):
                self._publish_locked(
                    document_id=document_id,
                    version_id=version_id,
                    task_id=task_id,
                    generation_id=generation_id,
                    chunk_count=chunk_count,
                    expected_current_version_id=expected_current_version_id,
                    expected_generation_id=expected_generation_id,
                    lease_token=lease_token,
                )
        except ActivationConflict:
            self._mark_conflict(task_id)
            raise

    def _publish_locked(
        self,
        *,
        document_id,
        version_id,
        task_id,
        generation_id,
        chunk_count,
        expected_current_version_id,
        expected_generation_id,
        lease_token,
    ) -> None:
        with self.database.session() as session, session.begin():
            current_version_id = session.execute(text("""
                SELECT current_version_id
                FROM knowledge_documents
                WHERE id = :document_id
                  AND deleted_at IS NULL
                FOR UPDATE
            """), {"document_id": document_id}).scalar_one_or_none()
            active_generation_id = session.execute(text("""
                SELECT active_bm25_generation_id
                FROM knowledge_index_state
                WHERE id = 1
                FOR UPDATE
            """)).scalar_one()
            candidate = session.execute(text("""
                SELECT version.document_id,
                       task.document_version_id AS task_version_id,
                       task.state, task.lease_token,
                       generation.document_version_id AS generation_version_id
                FROM document_versions AS version
                JOIN ingestion_tasks AS task ON task.id = :task_id
                JOIN bm25_generations AS generation
                  ON generation.id = :generation_id
                WHERE version.id = :version_id
            """), {
                "version_id": version_id,
                "task_id": task_id,
                "generation_id": generation_id,
            }).mappings().one_or_none()
            if (
                candidate is None
                or candidate["document_id"] != document_id
                or candidate["task_version_id"] != version_id
                or candidate["generation_version_id"] != version_id
                or candidate["state"] != "indexing"
                or (
                    lease_token is not None
                    and candidate["lease_token"] != lease_token
                )
                or current_version_id != expected_current_version_id
                or active_generation_id != expected_generation_id
            ):
                raise ActivationConflict("database activation state changed")

            session.execute(text("""
                UPDATE knowledge_documents
                SET current_version_id = :version_id,
                    updated_at = now()
                WHERE id = :document_id
            """), {
                "version_id": version_id,
                "document_id": document_id,
            })
            session.execute(text("""
                UPDATE bm25_generations
                SET published_at = now()
                WHERE id = :generation_id
            """), {"generation_id": generation_id})
            session.execute(text("""
                UPDATE knowledge_index_state
                SET active_bm25_generation_id = :generation_id,
                    updated_at = now()
                WHERE id = 1
            """), {"generation_id": generation_id})
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'succeeded',
                    result_code = NULL,
                    result_message = :message,
                    updated_at = now(),
                    completed_at = now(),
                    lease_token = NULL,
                    lease_expires_at = NULL
                WHERE id = :task_id
            """), {
                "task_id": task_id,
                "message": f"入库完成，共 {chunk_count} 个知识块",
            })

    def _mark_conflict(self, task_id) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'failed',
                    result_code = 'INGESTION_ACTIVATION_CONFLICT',
                    result_message = '版本发布冲突',
                    updated_at = now(),
                    completed_at = now()
                WHERE id = :task_id
                  AND state <> 'succeeded'
            """), {"task_id": task_id})
