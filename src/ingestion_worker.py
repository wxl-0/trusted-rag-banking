import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from sqlalchemy import text

from scripts import ingest
from src.database import Database
from src.indexer.bm25_index import BM25GenerationManager
from src.indexer.qdrant_index import DocumentVectorIndex


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


class IngestionWorker:
    def __init__(
        self,
        database,
        object_store,
        parser=None,
        vector_index=None,
        bm25_generations=None,
    ):
        self.database = database
        self.object_store = object_store
        self.parser = parser or SingleDocumentParser()
        self.vector_index = vector_index or DocumentVectorIndex()
        self.bm25_generations = bm25_generations or BM25GenerationManager(database)

    def process(self, job: dict) -> None:
        version = self._load_job(job)
        if version is None:
            return

        stage = "parsing"
        try:
            self._set_state(version["task_id"], "parsing")
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
            self._set_state(version["task_id"], "indexing")
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
            self._publish(version, generation, len(enriched))
        except Exception:
            message = "文档解析失败" if stage == "parsing" else "索引构建失败"
            self._fail(version["task_id"], message)

    def _load_job(self, job: dict) -> dict | None:
        try:
            document_id = UUID(str(job["document_id"]))
            version_id = UUID(str(job["version_id"]))
            task_id = UUID(str(job["task_id"]))
        except (KeyError, TypeError, ValueError):
            return None
        with self.database.session() as session:
            row = session.execute(text("""
                SELECT version.id, version.document_id,
                       version.original_filename, version.object_bucket,
                       version.object_key, version.content_type, task.id AS task_id,
                       task.state
                FROM document_versions AS version
                JOIN ingestion_tasks AS task
                  ON task.document_version_id = version.id
                WHERE version.id = :version_id
                  AND version.document_id = :document_id
                  AND task.id = :task_id
            """), {
                "document_id": document_id,
                "version_id": version_id,
                "task_id": task_id,
            }).mappings().one_or_none()
        if row is None or row["state"] != "queued":
            return None
        return dict(row)

    def _set_state(self, task_id: UUID, state: str) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = :state,
                    updated_at = now(),
                    started_at = COALESCE(started_at, now())
                WHERE id = :task_id
            """), {"task_id": task_id, "state": state})

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

    def _publish(self, version: dict, generation: dict, chunk_count: int) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                UPDATE knowledge_documents
                SET current_version_id = :version_id,
                    updated_at = now()
                WHERE id = :document_id
            """), {
                "version_id": version["id"],
                "document_id": version["document_id"],
            })
            session.execute(text("""
                UPDATE bm25_generations
                SET published_at = now()
                WHERE id = :generation_id
            """), {"generation_id": generation["id"]})
            session.execute(text("""
                UPDATE knowledge_index_state
                SET active_bm25_generation_id = :generation_id,
                    updated_at = now()
                WHERE id = 1
            """), {"generation_id": generation["id"]})
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'succeeded',
                    result_message = :message,
                    updated_at = now(),
                    completed_at = now()
                WHERE id = :task_id
            """), {
                "task_id": version["task_id"],
                "message": f"入库完成，共 {chunk_count} 个知识块",
            })

    def _fail(self, task_id: UUID, message: str) -> None:
        with self.database.session() as session, session.begin():
            session.execute(text("""
                UPDATE ingestion_tasks
                SET state = 'failed',
                    result_message = :message,
                    updated_at = now(),
                    completed_at = now()
                WHERE id = :task_id
                  AND state <> 'succeeded'
            """), {"task_id": task_id, "message": message})
