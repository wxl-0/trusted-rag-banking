import hashlib
import json
import logging
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from sqlalchemy import text

from scripts import ingest
from src.database import Database
from src.index_activation import (
    ActivationConflict,
    RedisActivationLock,
    VersionPublisher,
)
from src.indexer.bm25_index import BM25GenerationManager
from src.indexer.qdrant_index import DocumentVectorIndex


logger = logging.getLogger(__name__)


class SingleDocumentParser:
    """Run the established parser router for one immutable uploaded version."""

    def parse(self, local_path: Path, version: dict) -> tuple[str, list[dict]]:
        entry = {
            "doc_id": str(version["id"]),
            "title": Path(version["original_filename"]).stem,
            "issuer": "",
            "doc_no": "",
            "publish_date": "",
            "source_url": "",
            "local_path": str(local_path),
            "parse_profile": "regulation",
        }
        collection, chunks = ingest.parse_manifest_entry(entry)
        return collection, [chunk.to_dict() for chunk in chunks]


class IngestionLeaseLost(RuntimeError):
    pass


class IngestionWorker:
    def __init__(
        self,
        database,
        object_store,
        parser=None,
        vector_index=None,
        bm25_generations=None,
        publisher=None,
    ):
        self.database = database
        self.object_store = object_store
        self.parser = parser or SingleDocumentParser()
        self.vector_index = vector_index or DocumentVectorIndex()
        self.bm25_generations = bm25_generations or BM25GenerationManager(database)
        self.publisher = publisher or VersionPublisher(
            database,
            RedisActivationLock(),
        )

    def recoverable_jobs(self) -> list[dict]:
        with self.database.session() as session:
            rows = session.execute(text("""
                SELECT version.document_id,
                       version.id AS version_id,
                       task.id AS task_id,
                       task.idempotency_key
                FROM ingestion_tasks AS task
                JOIN document_versions AS version
                  ON version.id = task.document_version_id
                WHERE task.state = 'queued'
                   OR (
                       task.state IN ('parsing', 'indexing')
                       AND COALESCE(task.lease_expires_at, task.updated_at)
                           <= now()
                   )
                ORDER BY task.created_at, task.id
            """)).mappings().all()
        return [
            {
                "document_id": str(row["document_id"]),
                "version_id": str(row["version_id"]),
                "task_id": str(row["task_id"]),
                "idempotency_key": row["idempotency_key"],
            }
            for row in rows
        ]

    def process(self, job: dict) -> None:
        version = self._claim_job(job)
        if version is None:
            return "ignored"

        if version["needs_cleanup"]:
            try:
                self._cleanup_candidate(version)
            except Exception:
                logger.exception(
                    "candidate cleanup failed for task %s",
                    version["task_id"],
                )
                self._queue_cleanup_retry(version)
                return "retry"

        stage = "parsing"
        try:
            with TemporaryDirectory(prefix="trusted-rag-ingestion-") as temp_dir:
                local_path = Path(temp_dir) / Path(
                    version["original_filename"]
                ).name
                self.object_store.download(version["object_key"], local_path)
                collection, chunks = self.parser.parse(local_path, version)
            if collection not in {"regulations", "tables"} or not chunks:
                raise ValueError("document produced no searchable chunks")

            enriched = self._enrich_chunks(chunks, version)
            artifact = self._save_artifact(collection, enriched, version)
            self._record_artifact(artifact, version["id"])

            stage = "indexing"
            self._set_state(
                version["task_id"],
                version["lease_token"],
                "indexing",
            )
            self.vector_index.index_version(collection, enriched)
            if not self.vector_index.validate_version(
                collection,
                version["id"],
                len(enriched),
            ):
                raise RuntimeError("vector candidate validation failed")

            generation = self.bm25_generations.build_candidate(
                version["document_id"],
                version["id"],
                enriched,
            )
            if not self.bm25_generations.validate_candidate(
                generation,
                version["id"],
                len(enriched),
            ):
                raise RuntimeError("BM25 candidate validation failed")
            self._record_generation(generation, version["id"])
            self.publisher.publish(
                document_id=version["document_id"],
                version_id=version["id"],
                task_id=version["task_id"],
                generation_id=generation["id"],
                chunk_count=len(enriched),
                expected_current_version_id=version["current_version_id"],
                expected_generation_id=version["active_bm25_generation_id"],
                lease_token=version["lease_token"],
            )
            return "succeeded"
        except (ActivationConflict, IngestionLeaseLost):
            return "ignored"
        except Exception:
            logger.exception(
                "ingestion task %s failed during %s",
                version["task_id"],
                stage,
            )
            message = "文档解析失败" if stage == "parsing" else "索引构建失败"
            code = (
                "INGESTION_PARSE_FAILED"
                if stage == "parsing"
                else "INGESTION_INDEX_FAILED"
            )
            try:
                self._cleanup_candidate(version)
            except Exception:
                logger.exception(
                    "candidate cleanup failed for task %s",
                    version["task_id"],
                )
                self._queue_cleanup_retry(version)
                return "retry"
            self._fail(version["task_id"], version["lease_token"], code, message)
            return "failed"

    def _claim_job(self, job: dict) -> dict | None:
        try:
            document_id = UUID(str(job["document_id"]))
            version_id = UUID(str(job["version_id"]))
            task_id = UUID(str(job["task_id"]))
            idempotency_key = str(job["idempotency_key"])
        except (KeyError, TypeError, ValueError):
            return None
        lease_token = uuid4()
        lease_seconds = int(os.getenv("INGESTION_TASK_LEASE_SECONDS", "900"))
        with self.database.session() as session, session.begin():
            row = session.execute(text("""
                SELECT version.id, version.document_id,
                       version.original_filename, version.object_bucket,
                       version.object_key, version.content_type, task.id AS task_id,
                       task.state AS previous_state, task.attempt_count,
                       document.current_version_id,
                       index_state.active_bm25_generation_id
                FROM document_versions AS version
                JOIN ingestion_tasks AS task
                  ON task.document_version_id = version.id
                JOIN knowledge_documents AS document
                  ON document.id = version.document_id
                JOIN knowledge_index_state AS index_state ON index_state.id = 1
                WHERE version.id = :version_id
                  AND version.document_id = :document_id
                  AND task.id = :task_id
                  AND task.idempotency_key = :idempotency_key
                  AND (
                      task.state = 'queued'
                      OR (
                          task.state IN ('parsing', 'indexing')
                          AND COALESCE(task.lease_expires_at, task.updated_at)
                              <= now()
                      )
                  )
                FOR UPDATE OF task SKIP LOCKED
            """), {
                "document_id": document_id,
                "version_id": version_id,
                "task_id": task_id,
                "idempotency_key": idempotency_key,
            }).mappings().one_or_none()
            if row is None:
                return None
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'parsing',
                    attempt_count = attempt_count + 1,
                    lease_token = :lease_token,
                    lease_expires_at = now()
                        + (:lease_seconds * interval '1 second'),
                    result_code = NULL,
                    result_message = NULL,
                    updated_at = now(),
                    started_at = COALESCE(started_at, now()),
                    completed_at = NULL
                WHERE id = :task_id
            """), {
                "task_id": task_id,
                "lease_token": lease_token,
                "lease_seconds": lease_seconds,
            })
        return {
            **dict(row),
            "lease_token": lease_token,
            "needs_cleanup": (
                row["previous_state"] != "queued"
                or row["attempt_count"] > 0
            ),
        }

    def _set_state(self, task_id: UUID, lease_token: UUID, state: str) -> None:
        lease_seconds = int(os.getenv("INGESTION_TASK_LEASE_SECONDS", "900"))
        with self.database.session() as session, session.begin():
            result = session.execute(text("""
                UPDATE ingestion_tasks
                SET state = :state,
                    updated_at = now(),
                    lease_expires_at = now()
                        + (:lease_seconds * interval '1 second')
                WHERE id = :task_id
                  AND lease_token = :lease_token
                  AND state IN ('parsing', 'indexing')
            """), {
                "task_id": task_id,
                "lease_token": lease_token,
                "lease_seconds": lease_seconds,
                "state": state,
            })
            if result.rowcount != 1:
                raise IngestionLeaseLost("ingestion task lease lost")

    def _enrich_chunks(self, chunks: list[dict], version: dict) -> list[dict]:
        document_id = str(version["document_id"])
        version_id = str(version["id"])
        enriched = []
        seen = set()
        for chunk in chunks:
            item = dict(chunk)
            item["knowledge_document_id"] = document_id
            item["document_version_id"] = version_id
            item["local_path"] = version["original_filename"]
            chunk_id = item.get("chunk_id")
            if not chunk_id or chunk_id in seen:
                raise ValueError("document contains duplicate or missing chunk ids")
            seen.add(chunk_id)
            enriched.append(item)
        return enriched

    def _save_artifact(
        self,
        collection: str,
        chunks: list[dict],
        version: dict,
    ) -> dict:
        content = "".join(
            json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n"
            for chunk in chunks
        ).encode()
        object_key = (
            f"documents/{version['document_id']}/versions/{version['id']}"
            f"/chunks/{collection}.jsonl"
        )
        self.object_store.put_bytes(
            object_key,
            content,
            "application/x-ndjson",
        )
        return {
            "id": uuid4(),
            "collection_name": collection,
            "object_bucket": self.object_store.bucket_name,
            "object_key": object_key,
            "checksum_sha256": hashlib.sha256(content).hexdigest(),
            "chunk_count": len(chunks),
        }

    def _record_artifact(self, artifact: dict, version_id: UUID) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                INSERT INTO document_version_artifacts (
                    id, document_version_id, collection_name, object_bucket,
                    object_key, checksum_sha256, chunk_count
                ) VALUES (
                    :id, :version_id, :collection_name, :object_bucket,
                    :object_key, :checksum_sha256, :chunk_count
                )
            """), {**artifact, "version_id": version_id})

    def _record_generation(self, generation: dict, version_id: UUID) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                INSERT INTO bm25_generations (
                    id, document_version_id, artifact_path,
                    checksum_sha256, chunk_count
                ) VALUES (
                    :id, :version_id, :artifact_path,
                    :checksum_sha256, :chunk_count
                )
            """), {**generation, "version_id": version_id})

    def _cleanup_candidate(self, version: dict) -> None:
        base_key = (
            f"documents/{version['document_id']}/versions/{version['id']}"
            "/chunks"
        )
        for collection in ("regulations", "tables"):
            self.object_store.delete(f"{base_key}/{collection}.jsonl")
        self.vector_index.delete_version(version["id"])
        self.bm25_generations.cleanup_candidate(version["id"])
        with self.database.session() as session, session.begin():
            session.execute(text("""
                DELETE FROM document_version_artifacts
                WHERE document_version_id = :version_id
            """), {"version_id": version["id"]})
            session.execute(text("""
                DELETE FROM bm25_generations AS generation
                WHERE generation.document_version_id = :version_id
                  AND generation.published_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM knowledge_index_state AS state
                      WHERE state.active_bm25_generation_id = generation.id
                  )
            """), {"version_id": version["id"]})

    def _queue_cleanup_retry(self, version: dict) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'queued',
                    result_code = 'INGESTION_CLEANUP_PENDING',
                    result_message = '暂存数据清理中，等待安全重试',
                    updated_at = now(),
                    completed_at = NULL,
                    lease_token = NULL,
                    lease_expires_at = NULL
                WHERE id = :task_id
                  AND lease_token = :lease_token
                  AND state IN ('parsing', 'indexing')
            """), {
                "task_id": version["task_id"],
                "lease_token": version["lease_token"],
            })

    def _fail(
        self,
        task_id: UUID,
        lease_token: UUID,
        code: str,
        message: str,
    ) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'failed',
                    result_code = :code,
                    result_message = :message,
                    updated_at = now(),
                    completed_at = now(),
                    lease_token = NULL,
                    lease_expires_at = NULL
                WHERE id = :task_id
                  AND lease_token = :lease_token
                  AND state <> 'succeeded'
            """), {
                "task_id": task_id,
                "lease_token": lease_token,
                "code": code,
                "message": message,
            })
