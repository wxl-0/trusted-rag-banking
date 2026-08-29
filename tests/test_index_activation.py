from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from src.database import Database
from src.index_activation import (
    ActivationConflict,
    RedisActivationLock,
    VersionPublisher,
)
from src.index_visibility import CurrentVersionVisibility
from src.retriever.hybrid_retriever import HybridRetriever


class RecordingLock:
    def __init__(self):
        self.keys = []

    @contextmanager
    def hold(self, document_id):
        self.keys.append(str(document_id))
        yield


class NoopLock:
    @contextmanager
    def hold(self, document_id):
        yield


class FakeRedisLock:
    def __init__(self):
        self.acquired = False
        self.released = False

    def acquire(self, blocking=True):
        self.acquired = blocking
        return True

    def release(self):
        self.released = True


class FakeRedisClient:
    def __init__(self):
        self.calls = []
        self.lock_value = FakeRedisLock()

    def lock(self, name, timeout, blocking_timeout):
        self.calls.append((name, timeout, blocking_timeout))
        return self.lock_value


class CandidateQdrant:
    def __init__(self, chunks):
        self.chunks = chunks

    def search(self, query, collection_name, filters=None, top_k=20):
        return self.chunks[:top_k]


class EmptyBM25:
    def search(self, query, top_k=20, filters=None):
        return []


class PassThroughReranker:
    def rerank(self, query, chunks, top_k=5):
        return chunks[:top_k]


@pytest.fixture
def activation_database(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    try:
        yield database
    finally:
        database.dispose()


def _insert_version(
    database: Database,
    document_id,
    version_number: int,
    task_state: str,
):
    version_id = uuid4()
    task_id = uuid4()
    generation_id = uuid4()
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name
            ) VALUES (
                :version_id, :document_id, :version_number, :filename, 100,
                'maintainer', '知识库维护者'
            )
        """), {
            "version_id": version_id,
            "document_id": document_id,
            "version_number": version_number,
            "filename": f"监管制度-v{version_number}.docx",
        })
        session.execute(text("""
            INSERT INTO ingestion_tasks (id, document_version_id, state)
            VALUES (:task_id, :version_id, :task_state)
        """), {
            "task_id": task_id,
            "version_id": version_id,
            "task_state": task_state,
        })
        session.execute(text("""
            INSERT INTO bm25_generations (
                id, document_version_id, artifact_path,
                checksum_sha256, chunk_count, published_at
            ) VALUES (
                :generation_id, :version_id, :artifact_path,
                :checksum, 10,
                CASE WHEN :task_state = 'succeeded' THEN now() ELSE NULL END
            )
        """), {
            "generation_id": generation_id,
            "version_id": version_id,
            "artifact_path": f"data/bm25_generations/{generation_id}.pkl",
            "checksum": "a" * 64,
            "task_state": task_state,
        })
    return version_id, task_id, generation_id


def _seed_current_document(database: Database):
    document_id = uuid4()
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO knowledge_documents (id) VALUES (:document_id)
        """), {"document_id": document_id})
    version_id, task_id, generation_id = _insert_version(
        database,
        document_id,
        1,
        "succeeded",
    )
    with database.session() as session, session.begin():
        session.execute(text("""
            UPDATE knowledge_documents
            SET current_version_id = :version_id
            WHERE id = :document_id
        """), {"version_id": version_id, "document_id": document_id})
        session.execute(text("""
            UPDATE knowledge_index_state
            SET active_bm25_generation_id = :generation_id
            WHERE id = 1
        """), {"generation_id": generation_id})
    return document_id, version_id, generation_id


def _state(database: Database, document_id):
    with database.session() as session:
        return session.execute(text("""
            SELECT document.current_version_id,
                   state.active_bm25_generation_id
            FROM knowledge_documents AS document
            CROSS JOIN knowledge_index_state AS state
            WHERE document.id = :document_id AND state.id = 1
        """), {"document_id": document_id}).mappings().one()


def test_redis_coordination_lock_is_short_and_document_scoped():
    document_id = uuid4()
    client = FakeRedisClient()

    with RedisActivationLock(client).hold(document_id):
        assert client.lock_value.acquired is True

    assert client.calls == [(
        f"trusted-rag:activation:{document_id}",
        30,
        5,
    )]
    assert client.lock_value.released is True


@pytest.mark.parametrize("task_state", ["queued", "parsing", "indexing"])
def test_candidate_is_hidden_while_old_version_remains_visible(
    activation_database,
    task_state,
):
    document_id, old_version_id, _old_generation_id = _seed_current_document(
        activation_database
    )
    candidate_version_id, _task_id, _generation_id = _insert_version(
        activation_database,
        document_id,
        2,
        task_state,
    )
    visibility = CurrentVersionVisibility(activation_database)
    old_chunk = {
        "chunk_id": "old",
        "knowledge_document_id": str(document_id),
        "document_version_id": str(old_version_id),
    }
    candidate_chunk = {
        "chunk_id": "candidate",
        "knowledge_document_id": str(document_id),
        "document_version_id": str(candidate_version_id),
    }
    spoofed_chunk = {
        "chunk_id": "spoofed",
        "knowledge_document_id": str(uuid4()),
        "document_version_id": str(old_version_id),
    }

    assert visibility.filter([
        candidate_chunk,
        spoofed_chunk,
        old_chunk,
    ]) == [old_chunk]


def test_vector_leftovers_cannot_bypass_postgresql_visibility(
    activation_database,
):
    document_id, old_version_id, _old_generation_id = _seed_current_document(
        activation_database
    )
    candidate_version_id, _task_id, _generation_id = _insert_version(
        activation_database,
        document_id,
        2,
        "indexing",
    )
    old_chunk = {
        "chunk_id": "old",
        "chunk_type": "clause",
        "text": "旧版本仍然有效",
        "knowledge_document_id": str(document_id),
        "document_version_id": str(old_version_id),
    }
    candidate_chunk = {
        "chunk_id": "candidate",
        "chunk_type": "clause",
        "text": "候选版本尚未发布",
        "knowledge_document_id": str(document_id),
        "document_version_id": str(candidate_version_id),
    }
    retriever = HybridRetriever(
        qdrant=CandidateQdrant([candidate_chunk, old_chunk]),
        bm25=EmptyBM25(),
        router=object(),
        reranker=PassThroughReranker(),
        visibility=CurrentVersionVisibility(activation_database),
    )

    results = retriever.retrieve(
        "当前制度",
        query_type="regulation",
        top_k=1,
    )

    assert results == [old_chunk]


def test_successful_activation_switches_version_and_generation_together(
    activation_database,
):
    document_id, old_version_id, old_generation_id = _seed_current_document(
        activation_database
    )
    version_id, task_id, generation_id = _insert_version(
        activation_database,
        document_id,
        2,
        "indexing",
    )
    lock = RecordingLock()
    publisher = VersionPublisher(activation_database, lock)

    publisher.publish(
        document_id=document_id,
        version_id=version_id,
        task_id=task_id,
        generation_id=generation_id,
        chunk_count=12,
        expected_current_version_id=old_version_id,
        expected_generation_id=old_generation_id,
    )

    state = _state(activation_database, document_id)
    assert state == {
        "current_version_id": version_id,
        "active_bm25_generation_id": generation_id,
    }
    assert lock.keys == [str(document_id)]
    with activation_database.session() as session:
        task = session.execute(text("""
            SELECT state, result_message FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": task_id}).mappings().one()
        published_at = session.execute(text("""
            SELECT published_at FROM bm25_generations WHERE id = :generation_id
        """), {"generation_id": generation_id}).scalar_one()
    assert task == {
        "state": "succeeded",
        "result_message": "入库完成，共 12 个知识块",
    }
    assert published_at is not None


def test_stale_candidate_fails_without_changing_current_state(
    activation_database,
):
    document_id, old_version_id, old_generation_id = _seed_current_document(
        activation_database
    )
    version_id, task_id, generation_id = _insert_version(
        activation_database,
        document_id,
        2,
        "indexing",
    )
    publisher = VersionPublisher(activation_database, NoopLock())

    with pytest.raises(ActivationConflict):
        publisher.publish(
            document_id=document_id,
            version_id=version_id,
            task_id=task_id,
            generation_id=generation_id,
            chunk_count=12,
            expected_current_version_id=uuid4(),
            expected_generation_id=old_generation_id,
        )

    assert _state(activation_database, document_id) == {
        "current_version_id": old_version_id,
        "active_bm25_generation_id": old_generation_id,
    }
    with activation_database.session() as session:
        task = session.execute(text("""
            SELECT state, result_message FROM ingestion_tasks WHERE id = :task_id
        """), {"task_id": task_id}).mappings().one()
        published_at = session.execute(text("""
            SELECT published_at FROM bm25_generations WHERE id = :generation_id
        """), {"generation_id": generation_id}).scalar_one()
    assert task == {"state": "failed", "result_message": "版本发布冲突"}
    assert published_at is None


def test_concurrent_activation_has_one_database_winner(activation_database):
    document_id, old_version_id, old_generation_id = _seed_current_document(
        activation_database
    )
    candidates = [
        _insert_version(
            activation_database,
            document_id,
            version_number,
            "indexing",
        )
        for version_number in (2, 3)
    ]
    publisher = VersionPublisher(activation_database, NoopLock())

    def activate(candidate):
        version_id, task_id, generation_id = candidate
        try:
            publisher.publish(
                document_id=document_id,
                version_id=version_id,
                task_id=task_id,
                generation_id=generation_id,
                chunk_count=10,
                expected_current_version_id=old_version_id,
                expected_generation_id=old_generation_id,
            )
            return "succeeded", version_id, generation_id
        except ActivationConflict:
            return "failed", version_id, generation_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(activate, candidates))

    assert sorted(result[0] for result in results) == ["failed", "succeeded"]
    winner = next(result for result in results if result[0] == "succeeded")
    assert _state(activation_database, document_id) == {
        "current_version_id": winner[1],
        "active_bm25_generation_id": winner[2],
    }
    with activation_database.session() as session:
        states = session.execute(text("""
            SELECT state, count(*)
            FROM ingestion_tasks
            WHERE id = ANY(:task_ids)
            GROUP BY state
        """), {"task_ids": [candidate[1] for candidate in candidates]}).all()
    assert dict(states) == {"failed": 1, "succeeded": 1}
