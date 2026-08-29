import json
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.database import Database
from src.index_activation import VersionPublisher
from src.index_visibility import CurrentVersionVisibility
from src.ingestion_worker import IngestionWorker, SingleDocumentParser
from src.indexer.bm25_index import BM25GenerationManager, BM25Index, PublishedBM25Index
from src.retriever.hybrid_retriever import HybridRetriever


class RecordingObjectStore:
    bucket_name = "knowledge-documents"

    def __init__(self, original: bytes = b"source document"):
        self.original = original
        self.artifacts = {}

    def download(self, object_key, destination):
        Path(destination).write_bytes(self.original)

    def put_bytes(self, object_key, content, content_type):
        self.artifacts[object_key] = {
            "content": content,
            "content_type": content_type,
        }

    def delete(self, object_key):
        self.artifacts.pop(object_key, None)


class CleanupRetryObjectStore(RecordingObjectStore):
    def __init__(self):
        super().__init__()
        self.cleanup_attempts = 0

    def delete(self, object_key):
        if "/chunks/" in object_key:
            self.cleanup_attempts += 1
            if self.cleanup_attempts == 1:
                raise RuntimeError("minio secret=do-not-leak")
        super().delete(object_key)


class RecordingParser:
    def __init__(self, database):
        self.database = database
        self.states = []

    def parse(self, local_path, version):
        with self.database.session() as session:
            self.states.append(session.execute(text("""
                SELECT state FROM ingestion_tasks WHERE id = :task_id
            """), {"task_id": version["task_id"]}).scalar_one())
        return "regulations", [{
            "doc_id": str(version["id"]),
            "chunk_id": "chunk-1",
            "chunk_type": "clause",
            "text": "资本充足率不得低于百分之十点五。",
            "source_title": "商业银行资本管理办法",
            "issuer": "",
            "doc_no": "",
            "publish_date": "",
            "section_path": ["资本监管要求"],
            "source_url": "",
            "local_path": version["original_filename"],
        }]


class BlockingParser(RecordingParser):
    def __init__(self, database):
        super().__init__(database)
        self.started = threading.Event()
        self.release = threading.Event()
        self.call_count = 0

    def parse(self, local_path, version):
        self.call_count += 1
        self.started.set()
        assert self.release.wait(timeout=3)
        return super().parse(local_path, version)


class FailingParser:
    def parse(self, local_path, version):
        raise RuntimeError("parser host password=do-not-leak")


class RecordingVectorIndex:
    def __init__(self, database, fail=False):
        self.database = database
        self.fail = fail
        self.calls = []
        self.deleted_versions = []

    def index_version(self, collection, chunks):
        with self.database.session() as session:
            state = session.execute(text("""
                SELECT state FROM ingestion_tasks
                WHERE document_version_id = :version_id
            """), {"version_id": chunks[0]["document_version_id"]}).scalar_one()
        self.calls.append((collection, chunks, state))
        if self.fail:
            raise RuntimeError("qdrant api-key=do-not-leak")
        return ["point-1"]

    def validate_version(self, collection, version_id, expected_count):
        return not self.fail and expected_count == 1

    def delete_version(self, version_id):
        self.deleted_versions.append(str(version_id))


class RecordingBM25Generations:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.cleaned_versions = []

    def build_candidate(self, document_id, version_id, chunks):
        self.calls.append((document_id, version_id, chunks))
        if self.fail:
            raise RuntimeError("filesystem secret=do-not-leak")
        return {
            "id": uuid4(),
            "artifact_path": f"data/bm25_generations/{uuid4()}.pkl",
            "checksum_sha256": "b" * 64,
            "chunk_count": len(chunks),
        }

    def validate_candidate(self, generation, version_id, expected_count):
        return not self.fail and expected_count == 1

    def cleanup_candidate(self, version_id):
        self.cleaned_versions.append(str(version_id))


class EmptyQdrant:
    def search(self, query, collection_name, filters=None, top_k=20):
        return []


class PassThroughReranker:
    def rerank(self, query, chunks, top_k=5):
        return chunks[:top_k]


class NoopActivationLock:
    @contextmanager
    def hold(self, document_id):
        yield


def _publisher(database):
    return VersionPublisher(database, NoopActivationLock())


def _seed_queued_upload(database: Database):
    document_id = uuid4()
    version_id = uuid4()
    task_id = uuid4()
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO knowledge_documents (id) VALUES (:document_id)
        """), {"document_id": document_id})
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name, object_bucket,
                object_key, checksum_sha256, content_type
            ) VALUES (
                :version_id, :document_id, 1, '商业银行资本管理办法.docx', 15,
                'maintainer', '知识库维护者', 'knowledge-documents',
                :object_key, :checksum, :content_type
            )
        """), {
            "version_id": version_id,
            "document_id": document_id,
            "object_key": f"documents/{document_id}/versions/{version_id}/original.docx",
            "checksum": "a" * 64,
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        })
        session.execute(text("""
            INSERT INTO ingestion_tasks (
                id, document_version_id, idempotency_key, state
            ) VALUES (
                :task_id, :version_id, :idempotency_key, 'queued'
            )
        """), {
            "task_id": task_id,
            "version_id": version_id,
            "idempotency_key": str(task_id),
        })
    return {
        "document_id": str(document_id),
        "version_id": str(version_id),
        "task_id": str(task_id),
        "idempotency_key": str(task_id),
    }


def _seed_unrecoverable_legacy_job(database: Database):
    document_id = uuid4()
    version_id = uuid4()
    task_id = uuid4()
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO knowledge_documents (id) VALUES (:document_id)
        """), {"document_id": document_id})
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name
            ) VALUES (
                :version_id, :document_id, 1, '历史制度.docx', 10,
                'maintainer', '知识库维护者'
            )
        """), {"version_id": version_id, "document_id": document_id})
        session.execute(text("""
            INSERT INTO ingestion_tasks (
                id, document_version_id, idempotency_key, state
            ) VALUES (
                :task_id, :version_id, :idempotency_key, 'queued'
            )
        """), {
            "task_id": task_id,
            "version_id": version_id,
            "idempotency_key": str(task_id),
        })
    return {
        "document_id": str(document_id),
        "version_id": str(version_id),
        "task_id": str(task_id),
        "idempotency_key": str(task_id),
    }


def _seed_queued_update(database: Database):
    document_id = uuid4()
    old_version_id = uuid4()
    old_task_id = uuid4()
    old_generation_id = uuid4()
    candidate_version_id = uuid4()
    candidate_task_id = uuid4()
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO knowledge_documents (id) VALUES (:document_id)
        """), {"document_id": document_id})
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name
            ) VALUES (
                :version_id, :document_id, 1, '监管制度-v1.docx', 10,
                'maintainer', '知识库维护者'
            )
        """), {"version_id": old_version_id, "document_id": document_id})
        session.execute(text("""
            INSERT INTO ingestion_tasks (
                id, document_version_id, idempotency_key,
                state, completed_at
            ) VALUES (
                :task_id, :version_id, :idempotency_key,
                'succeeded', now()
            )
        """), {
            "task_id": old_task_id,
            "version_id": old_version_id,
            "idempotency_key": str(old_task_id),
        })
        session.execute(text("""
            INSERT INTO bm25_generations (
                id, document_version_id, artifact_path,
                checksum_sha256, chunk_count, published_at
            ) VALUES (
                :generation_id, :version_id, :artifact_path,
                :checksum, 10, now()
            )
        """), {
            "generation_id": old_generation_id,
            "version_id": old_version_id,
            "artifact_path": f"data/bm25_generations/{old_generation_id}.pkl",
            "checksum": "c" * 64,
        })
        session.execute(text("""
            UPDATE knowledge_documents
            SET current_version_id = :version_id
            WHERE id = :document_id
        """), {"version_id": old_version_id, "document_id": document_id})
        session.execute(text("""
            UPDATE knowledge_index_state
            SET active_bm25_generation_id = :generation_id
            WHERE id = 1
        """), {"generation_id": old_generation_id})
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name, object_bucket,
                object_key, checksum_sha256, content_type
            ) VALUES (
                :version_id, :document_id, 2, '监管制度-v2.docx', 15,
                'maintainer', '知识库维护者', 'knowledge-documents',
                :object_key, :checksum, :content_type
            )
        """), {
            "version_id": candidate_version_id,
            "document_id": document_id,
            "object_key": (
                f"documents/{document_id}/versions/"
                f"{candidate_version_id}/original.docx"
            ),
            "checksum": "d" * 64,
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        })
        session.execute(text("""
            INSERT INTO ingestion_tasks (
                id, document_version_id, idempotency_key, state
            ) VALUES (
                :task_id, :version_id, :idempotency_key, 'queued'
            )
        """), {
            "task_id": candidate_task_id,
            "version_id": candidate_version_id,
            "idempotency_key": str(candidate_task_id),
        })
    return (
        {
            "document_id": str(document_id),
            "version_id": str(candidate_version_id),
            "task_id": str(candidate_task_id),
            "idempotency_key": str(candidate_task_id),
        },
        old_version_id,
        old_generation_id,
    )


@pytest.fixture
def ingestion_database(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    try:
        yield database
    finally:
        database.dispose()


def test_worker_persists_artifacts_and_publishes_only_after_validation(
    ingestion_database,
):
    job = _seed_queued_upload(ingestion_database)
    object_store = RecordingObjectStore()
    parser = RecordingParser(ingestion_database)
    vector_index = RecordingVectorIndex(ingestion_database)
    bm25 = RecordingBM25Generations()
    worker = IngestionWorker(
        ingestion_database,
        object_store,
        parser,
        vector_index,
        bm25,
        _publisher(ingestion_database),
    )

    worker.process(job)

    assert parser.states == ["parsing"]
    assert vector_index.calls[0][2] == "indexing"
    collection, indexed_chunks, _state = vector_index.calls[0]
    assert collection == "regulations"
    assert indexed_chunks[0]["knowledge_document_id"] == job["document_id"]
    assert indexed_chunks[0]["document_version_id"] == job["version_id"]
    assert len(object_store.artifacts) == 1
    artifact_key, artifact = next(iter(object_store.artifacts.items()))
    assert artifact_key == (
        f"documents/{job['document_id']}/versions/{job['version_id']}"
        "/chunks/regulations.jsonl"
    )
    assert json.loads(artifact["content"].decode().strip())["chunk_id"] == "chunk-1"

    with ingestion_database.session() as session:
        row = session.execute(text("""
            SELECT task.state, task.result_message, task.started_at,
                   task.completed_at, document.current_version_id,
                   state.active_bm25_generation_id,
                   generation.published_at,
                   artifact.collection_name, artifact.chunk_count
            FROM ingestion_tasks AS task
            JOIN document_versions AS version
              ON version.id = task.document_version_id
            JOIN knowledge_documents AS document
              ON document.id = version.document_id
            JOIN document_version_artifacts AS artifact
              ON artifact.document_version_id = version.id
            JOIN knowledge_index_state AS state ON state.id = 1
            JOIN bm25_generations AS generation
              ON generation.id = state.active_bm25_generation_id
            WHERE task.id = :task_id
        """), {"task_id": UUID(job["task_id"])}).mappings().one()

    assert row["state"] == "succeeded"
    assert row["result_message"] == "入库完成，共 1 个知识块"
    assert row["started_at"] is not None
    assert row["completed_at"] is not None
    assert str(row["current_version_id"]) == job["version_id"]
    assert row["active_bm25_generation_id"] is not None
    assert row["published_at"] is not None
    assert row["collection_name"] == "regulations"
    assert row["chunk_count"] == 1


def test_stale_indexing_task_is_safely_redone_to_one_terminal_result(
    ingestion_database,
):
    job = _seed_queued_upload(ingestion_database)
    with ingestion_database.session() as session, session.begin():
        session.execute(text("""
            UPDATE ingestion_tasks
            SET state = 'indexing',
                started_at = now() - interval '20 minutes',
                updated_at = now() - interval '20 minutes'
            WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])})

    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database),
        RecordingBM25Generations(),
        _publisher(ingestion_database),
    )

    worker.process(job)

    with ingestion_database.session() as session:
        task = session.execute(text("""
            SELECT state, count(*) OVER () AS task_count
            FROM ingestion_tasks
            WHERE document_version_id = :version_id
        """), {"version_id": UUID(job["version_id"])}).mappings().one()
        artifact_count = session.execute(text("""
            SELECT count(*) FROM document_version_artifacts
            WHERE document_version_id = :version_id
        """), {"version_id": UUID(job["version_id"])}).scalar_one()
        generation_count = session.execute(text("""
            SELECT count(*) FROM bm25_generations
            WHERE document_version_id = :version_id
        """), {"version_id": UUID(job["version_id"])}).scalar_one()

    assert task == {"state": "succeeded", "task_count": 1}
    assert artifact_count == 1
    assert generation_count == 1


def test_duplicate_delivery_has_one_worker_and_one_terminal_result(
    ingestion_database,
):
    job = _seed_queued_upload(ingestion_database)
    parser = BlockingParser(ingestion_database)
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        parser,
        RecordingVectorIndex(ingestion_database),
        RecordingBM25Generations(),
        _publisher(ingestion_database),
    )
    first_result = []
    thread = threading.Thread(
        target=lambda: first_result.append(worker.process(job)),
    )
    thread.start()
    assert parser.started.wait(timeout=3)

    duplicate_result = worker.process(job)
    parser.release.set()
    thread.join(timeout=3)

    assert duplicate_result == "ignored"
    assert first_result == ["succeeded"]
    assert worker.process(job) == "ignored"
    assert parser.call_count == 1
    with ingestion_database.session() as session:
        counts = session.execute(text("""
            SELECT
                (SELECT count(*) FROM ingestion_tasks
                 WHERE document_version_id = :version_id) AS tasks,
                (SELECT count(*) FROM document_version_artifacts
                 WHERE document_version_id = :version_id) AS artifacts,
                (SELECT count(*) FROM bm25_generations
                 WHERE document_version_id = :version_id) AS generations
        """), {"version_id": UUID(job["version_id"])}).mappings().one()
        state = session.execute(text("""
            SELECT state FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).scalar_one()

    assert counts == {"tasks": 1, "artifacts": 1, "generations": 1}
    assert state == "succeeded"


def test_candidate_cleanup_retries_without_disabling_the_active_version(
    ingestion_database,
):
    job, old_version_id, old_generation_id = _seed_queued_update(
        ingestion_database
    )
    candidate_generation_id = uuid4()
    artifact_key = (
        f"documents/{job['document_id']}/versions/{job['version_id']}"
        "/chunks/regulations.jsonl"
    )
    with ingestion_database.session() as session, session.begin():
        session.execute(text("""
            UPDATE ingestion_tasks
            SET state = 'indexing',
                started_at = now() - interval '20 minutes',
                updated_at = now() - interval '20 minutes'
            WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])})
        session.execute(text("""
            INSERT INTO document_version_artifacts (
                id, document_version_id, collection_name, object_bucket,
                object_key, checksum_sha256, chunk_count
            ) VALUES (
                :id, :version_id, 'regulations', 'knowledge-documents',
                :object_key, :checksum, 1
            )
        """), {
            "id": uuid4(),
            "version_id": UUID(job["version_id"]),
            "object_key": artifact_key,
            "checksum": "e" * 64,
        })
        session.execute(text("""
            INSERT INTO bm25_generations (
                id, document_version_id, artifact_path,
                checksum_sha256, chunk_count
            ) VALUES (
                :id, :version_id, :artifact_path, :checksum, 1
            )
        """), {
            "id": candidate_generation_id,
            "version_id": UUID(job["version_id"]),
            "artifact_path": f"data/bm25_generations/{candidate_generation_id}.pkl",
            "checksum": "f" * 64,
        })

    object_store = CleanupRetryObjectStore()
    object_store.artifacts[artifact_key] = {
        "content": b"stale",
        "content_type": "application/x-ndjson",
    }
    vector_index = RecordingVectorIndex(ingestion_database)
    bm25 = RecordingBM25Generations()
    worker = IngestionWorker(
        ingestion_database,
        object_store,
        RecordingParser(ingestion_database),
        vector_index,
        bm25,
        _publisher(ingestion_database),
    )

    assert worker.process(job) == "retry"
    with ingestion_database.session() as session:
        pending = session.execute(text("""
            SELECT state, result_code, result_message
            FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).mappings().one()
        current_version_id = session.execute(text("""
            SELECT current_version_id FROM knowledge_documents
            WHERE id = :document_id
        """), {"document_id": UUID(job["document_id"])}).scalar_one()
        active_generation_id = session.execute(text("""
            SELECT active_bm25_generation_id FROM knowledge_index_state
            WHERE id = 1
        """)).scalar_one()

    assert pending == {
        "state": "queued",
        "result_code": "INGESTION_CLEANUP_PENDING",
        "result_message": "暂存数据清理中，等待安全重试",
    }
    assert current_version_id == old_version_id
    assert active_generation_id == old_generation_id

    assert worker.process(job) == "succeeded"
    with ingestion_database.session() as session:
        final_state = session.execute(text("""
            SELECT state FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).scalar_one()
        artifact_count = session.execute(text("""
            SELECT count(*) FROM document_version_artifacts
            WHERE document_version_id = :version_id
        """), {"version_id": UUID(job["version_id"])}).scalar_one()
        generation_count = session.execute(text("""
            SELECT count(*) FROM bm25_generations
            WHERE document_version_id = :version_id
        """), {"version_id": UUID(job["version_id"])}).scalar_one()

    assert final_state == "succeeded"
    assert artifact_count == 1
    assert generation_count == 1
    assert vector_index.deleted_versions == [job["version_id"]]
    assert bm25.cleaned_versions == [job["version_id"]]


def test_worker_restart_recovers_queued_and_expired_jobs(ingestion_database):
    queued_job = _seed_queued_upload(ingestion_database)
    expired_job = _seed_queued_upload(ingestion_database)
    with ingestion_database.session() as session, session.begin():
        session.execute(text("""
            UPDATE ingestion_tasks
            SET state = 'parsing',
                updated_at = now() - interval '20 minutes',
                lease_expires_at = now() - interval '5 minutes'
            WHERE id = :task_id
        """), {"task_id": UUID(expired_job["task_id"])})

    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database),
        RecordingBM25Generations(),
        _publisher(ingestion_database),
    )

    assert sorted(
        worker.recoverable_jobs(),
        key=lambda job: job["task_id"],
    ) == sorted([queued_job, expired_job], key=lambda job: job["task_id"])


def test_worker_restart_fails_legacy_job_without_source_object(
    ingestion_database,
):
    job = _seed_unrecoverable_legacy_job(ingestion_database)
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database),
        RecordingBM25Generations(),
        _publisher(ingestion_database),
    )

    assert worker.recoverable_jobs() == []

    with ingestion_database.session() as session:
        task = session.execute(text("""
            SELECT state, result_code, result_message, completed_at,
                   lease_token, lease_expires_at
            FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).mappings().one()

    assert task["state"] == "failed"
    assert task["result_code"] == "INGESTION_SOURCE_MISSING"
    assert task["result_message"] == "原始文件不可用，无法恢复入库"
    assert task["completed_at"] is not None
    assert task["lease_token"] is None
    assert task["lease_expires_at"] is None


def test_worker_restart_reclassifies_legacy_missing_source_failure(
    ingestion_database,
):
    job = _seed_unrecoverable_legacy_job(ingestion_database)
    with ingestion_database.session() as session, session.begin():
        session.execute(text("""
            UPDATE ingestion_tasks
            SET state = 'failed',
                result_code = 'INGESTION_PARSE_FAILED',
                result_message = '文档解析失败',
                completed_at = now()
            WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])})
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database),
        RecordingBM25Generations(),
        _publisher(ingestion_database),
    )

    assert worker.recoverable_jobs() == []

    with ingestion_database.session() as session:
        task = session.execute(text("""
            SELECT result_code, result_message
            FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).mappings().one()

    assert task == {
        "result_code": "INGESTION_SOURCE_MISSING",
        "result_message": "原始文件不可用，无法恢复入库",
    }


def test_worker_restart_keeps_job_recoverable_when_only_optional_metadata_missing(
    ingestion_database,
):
    job = _seed_queued_upload(ingestion_database)
    with ingestion_database.session() as session, session.begin():
        session.execute(text("""
            UPDATE document_versions
            SET object_bucket = NULL,
                checksum_sha256 = NULL,
                content_type = NULL
            WHERE id = :version_id
        """), {"version_id": UUID(job["version_id"])})
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database),
        RecordingBM25Generations(),
        _publisher(ingestion_database),
    )

    assert worker.recoverable_jobs() == [job]


@pytest.mark.parametrize(
    ("parser", "vector_fail", "bm25_fail", "expected_message"),
    [
        (FailingParser(), False, False, "文档解析失败"),
        (None, True, False, "索引构建失败"),
        (None, False, True, "索引构建失败"),
    ],
)
def test_worker_failure_is_safe_and_never_publishes(
    ingestion_database,
    parser,
    vector_fail,
    bm25_fail,
    expected_message,
):
    job = _seed_queued_upload(ingestion_database)
    parser = parser or RecordingParser(ingestion_database)
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        parser,
        RecordingVectorIndex(ingestion_database, fail=vector_fail),
        RecordingBM25Generations(fail=bm25_fail),
        _publisher(ingestion_database),
    )

    worker.process(job)

    with ingestion_database.session() as session:
        task = session.execute(text("""
            SELECT state, result_code, result_message, completed_at
            FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).mappings().one()
        current_version_id = session.execute(text("""
            SELECT current_version_id FROM knowledge_documents
            WHERE id = :document_id
        """), {"document_id": UUID(job["document_id"])}).scalar_one()
        active_generation = session.execute(text("""
            SELECT active_bm25_generation_id
            FROM knowledge_index_state WHERE id = 1
        """)).scalar_one()

    assert task["state"] == "failed"
    assert task["result_code"] == (
        "INGESTION_PARSE_FAILED"
        if expected_message == "文档解析失败"
        else "INGESTION_INDEX_FAILED"
    )
    assert task["result_message"] == expected_message
    assert task["completed_at"] is not None
    assert "secret" not in task["result_message"]
    assert current_version_id is None
    assert active_generation is None


@pytest.mark.parametrize(("vector_fail", "bm25_fail"), [
    (True, False),
    (False, True),
])
def test_index_failure_keeps_old_version_and_generation_active(
    ingestion_database,
    vector_fail,
    bm25_fail,
):
    job, old_version_id, old_generation_id = _seed_queued_update(
        ingestion_database
    )
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database, fail=vector_fail),
        RecordingBM25Generations(fail=bm25_fail),
        _publisher(ingestion_database),
    )

    worker.process(job)

    with ingestion_database.session() as session:
        current_version_id = session.execute(text("""
            SELECT current_version_id FROM knowledge_documents
            WHERE id = :document_id
        """), {"document_id": UUID(job["document_id"])}).scalar_one()
        active_generation_id = session.execute(text("""
            SELECT active_bm25_generation_id
            FROM knowledge_index_state WHERE id = 1
        """)).scalar_one()
        task = session.execute(text("""
            SELECT state, result_message FROM ingestion_tasks
            WHERE id = :task_id
        """), {"task_id": UUID(job["task_id"])}).mappings().one()
    assert current_version_id == old_version_id
    assert active_generation_id == old_generation_id
    assert task == {"state": "failed", "result_message": "索引构建失败"}


def test_published_generation_makes_document_retrievable_with_evidence(
    ingestion_database,
    tmp_path,
):
    job = _seed_queued_upload(ingestion_database)
    legacy_path = tmp_path / "legacy.pkl"
    BM25Index(str(legacy_path)).build_from_chunks([
        {
            "chunk_id": f"legacy-{index}",
            "chunk_type": "clause",
            "text": text_value,
            "source_title": f"历史制度 {index}",
        }
        for index, text_value in enumerate(("流动性要求", "操作风险", "信息披露"), 1)
    ])
    generations = BM25GenerationManager(
        ingestion_database,
        generation_dir=str(tmp_path / "generations"),
        legacy_path=str(legacy_path),
        chunk_paths=(),
    )
    worker = IngestionWorker(
        ingestion_database,
        RecordingObjectStore(),
        RecordingParser(ingestion_database),
        RecordingVectorIndex(ingestion_database),
        generations,
        _publisher(ingestion_database),
    )

    worker.process(job)

    retriever = HybridRetriever(
        qdrant=EmptyQdrant(),
        bm25=PublishedBM25Index(
            ingestion_database,
            legacy_path=str(legacy_path),
        ),
        reranker=PassThroughReranker(),
        visibility=CurrentVersionVisibility(ingestion_database),
    )
    results = retriever.retrieve(
        "资本充足率最低要求",
        query_type="regulation",
        top_k=3,
    )

    assert results[0]["source_title"] == "商业银行资本管理办法"
    assert results[0]["text"] == "资本充足率不得低于百分之十点五。"
    assert results[0]["document_version_id"] == job["version_id"]


def test_current_version_visibility_hides_candidate_until_publication(
    ingestion_database,
):
    job = _seed_queued_upload(ingestion_database)
    chunk = {
        "chunk_id": "candidate",
        "knowledge_document_id": job["document_id"],
        "document_version_id": job["version_id"],
    }
    visibility = CurrentVersionVisibility(ingestion_database)

    assert visibility.filter([chunk]) == []

    with ingestion_database.session() as session, session.begin():
        session.execute(text("""
            UPDATE knowledge_documents
            SET current_version_id = :version_id
            WHERE id = :document_id
        """), {
            "version_id": UUID(job["version_id"]),
            "document_id": UUID(job["document_id"]),
        })

    assert visibility.filter([chunk]) == [chunk]
    legacy = {"chunk_id": "legacy"}
    assert visibility.filter([legacy]) == [legacy]


def test_single_document_parser_reuses_existing_entry_router(tmp_path, monkeypatch):
    local_path = tmp_path / "资本管理办法.pdf"
    local_path.write_bytes(b"%PDF-1.7")
    captured = {}

    def fake_parse(entry):
        captured.update(entry)
        return "regulations", []

    monkeypatch.setattr("scripts.ingest.parse_manifest_entry", fake_parse)

    result = SingleDocumentParser().parse(local_path, {
        "id": uuid4(),
        "original_filename": local_path.name,
    })

    assert result == ("regulations", [])
    assert captured["local_path"] == str(local_path)
    assert captured["title"] == "资本管理办法"
    assert captured["parse_profile"] == "regulation"
