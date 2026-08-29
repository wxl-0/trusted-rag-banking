from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.auth import Identity, get_current_identity
from src.database import Database, get_database
from src.document_uploads import get_object_store
from src.index_visibility import CurrentVersionVisibility


def _identity(role: str) -> Identity:
    return Identity(
        subject=f"{role}-subject",
        username=role,
        display_name="测试用户",
        email=None,
        roles=frozenset({role}),
    )


@pytest.fixture
def knowledge_client(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_current_identity] = lambda: _identity("member")
    try:
        with TestClient(app) as client:
            yield client, database
    finally:
        app.dependency_overrides.pop(get_current_identity, None)
        app.dependency_overrides.pop(get_database, None)
        database.dispose()


def test_member_cannot_call_knowledge_document_read_apis(knowledge_client):
    client, _database = knowledge_client

    for path in (
        "/api/knowledge-documents/summary",
        "/api/knowledge-documents",
        f"/api/knowledge-documents/{uuid4()}",
    ):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json()["detail"] == {
            "code": "KNOWLEDGE_MAINTAINER_REQUIRED",
            "message": "仅知识库维护者可以管理企业共享知识库",
        }

    response = client.delete(f"/api/knowledge-documents/{uuid4()}")
    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "KNOWLEDGE_MAINTAINER_REQUIRED",
        "message": "仅知识库维护者可以管理企业共享知识库",
    }


def _seed_document(
    database: Database,
    *,
    filename: str,
    state: str,
    updated_at: datetime,
    size_bytes: int = 1024,
    result_code: str | None = None,
    object_key: str | None = None,
    content_type: str | None = None,
) -> str:
    document_id = uuid4()
    version_id = uuid4()
    task_id = uuid4()
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO knowledge_documents (id, created_at, updated_at)
            VALUES (:id, :updated_at, :updated_at)
        """), {"id": document_id, "updated_at": updated_at})
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name, object_bucket,
                object_key, content_type, created_at, updated_at
            ) VALUES (
                :id, :document_id, 1, :filename, :size_bytes,
                'maintainer-subject', '知识库维护者', :object_bucket,
                :object_key, :content_type, :updated_at, :updated_at
            )
        """), {
            "id": version_id,
            "document_id": document_id,
            "filename": filename,
            "size_bytes": size_bytes,
            "object_bucket": "knowledge-documents" if object_key else None,
            "object_key": object_key,
            "content_type": content_type,
            "updated_at": updated_at,
        })
        session.execute(text("""
            INSERT INTO ingestion_tasks (
                id, document_version_id, idempotency_key,
                state, result_code, result_message,
                created_at, updated_at, completed_at
            ) VALUES (
                :id, :version_id, :idempotency_key,
                :state, :result_code, :result_message,
                :updated_at, :updated_at, :completed_at
            )
        """), {
            "id": task_id,
            "version_id": version_id,
            "idempotency_key": str(task_id),
            "state": state,
            "result_code": result_code,
            "result_message": (
                "入库完成"
                if state == "succeeded"
                else "文档解析失败"
                if state == "failed"
                else None
            ),
            "updated_at": updated_at,
            "completed_at": updated_at if state in {"succeeded", "failed"} else None,
        })
        if state == "succeeded":
            session.execute(text("""
                UPDATE knowledge_documents
                SET current_version_id = :version_id
                WHERE id = :document_id
            """), {"version_id": version_id, "document_id": document_id})
    return str(document_id)


class DownloadObjectStore:
    def __init__(self):
        self.objects = {}

    def open_download(self, object_key):
        try:
            return BytesIO(self.objects[object_key])
        except KeyError as error:
            raise FileNotFoundError(object_key) from error


@pytest.fixture
def download_client(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    object_store = DownloadObjectStore()
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    app.dependency_overrides[get_object_store] = lambda: object_store
    try:
        with TestClient(app) as client:
            yield client, database, object_store
    finally:
        app.dependency_overrides.clear()
        database.dispose()


def test_maintainer_reads_knowledge_document_summary(knowledge_client):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    _seed_document(
        database,
        filename="资本管理办法.pdf",
        state="succeeded",
        updated_at=datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc),
    )
    _seed_document(
        database,
        filename="风险分类指引.docx",
        state="parsing",
        updated_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
    )
    _seed_document(
        database,
        filename="统计制度.xlsx",
        state="failed",
        updated_at=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )

    response = client.get("/api/knowledge-documents/summary")

    assert response.status_code == 200
    assert response.json() == {
        "succeeded": 1,
        "in_progress": 1,
        "failed": 1,
        "updated_at": "2026-08-28T10:00:00Z",
    }


def test_maintainer_pages_documents_by_latest_update(knowledge_client):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    newest_id = _seed_document(
        database,
        filename="最新监管办法.pdf",
        state="succeeded",
        size_bytes=2048,
        updated_at=datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc),
    )
    middle_id = _seed_document(
        database,
        filename="中间统计制度.xlsx",
        state="parsing",
        size_bytes=3072,
        updated_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
    )
    oldest_id = _seed_document(
        database,
        filename="早期风险指引.docx",
        state="failed",
        size_bytes=4096,
        updated_at=datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc),
    )

    first = client.get("/api/knowledge-documents", params={"limit": 2})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [
        newest_id,
        middle_id,
    ]
    assert [item["sequence"] for item in first.json()["items"]] == [1, 2]
    assert first.json()["items"][0] == {
        "id": newest_id,
        "sequence": 1,
        "filename": "最新监管办法.pdf",
        "size_bytes": 2048,
        "status": "succeeded",
        "updated_at": "2026-08-28T10:00:00Z",
    }
    assert first.json()["next_cursor"]

    second = client.get("/api/knowledge-documents", params={
        "limit": 2,
        "cursor": first.json()["next_cursor"],
    })
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["items"]] == [oldest_id]
    assert [item["sequence"] for item in second.json()["items"]] == [3]
    assert second.json()["next_cursor"] is None


def test_maintainer_can_open_a_numbered_document_page(knowledge_client):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    for hour in range(5):
        _seed_document(
            database,
            filename=f"监管制度-{hour}.pdf",
            state="succeeded",
            updated_at=datetime(2026, 8, 28, hour, 0, tzinfo=timezone.utc),
        )

    response = client.get(
        "/api/knowledge-documents",
        params={"page": 2, "limit": 2},
    )

    assert response.status_code == 200
    assert [item["filename"] for item in response.json()["items"]] == [
        "监管制度-2.pdf",
        "监管制度-1.pdf",
    ]
    assert [item["sequence"] for item in response.json()["items"]] == [3, 4]
    assert response.json()["total"] == 5
    assert response.json()["page"] == 2
    assert response.json()["page_size"] == 2


def test_maintainer_filters_documents_by_filename_and_status(knowledge_client):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    matching_id = _seed_document(
        database,
        filename="商业银行资本管理办法.docx",
        state="parsing",
        updated_at=datetime(2026, 8, 28, 9, 0, tzinfo=timezone.utc),
    )
    _seed_document(
        database,
        filename="商业银行资本管理办法旧版.pdf",
        state="succeeded",
        updated_at=datetime(2026, 8, 28, 8, 0, tzinfo=timezone.utc),
    )
    _seed_document(
        database,
        filename="监管统计制度.xlsx",
        state="parsing",
        updated_at=datetime(2026, 8, 28, 7, 0, tzinfo=timezone.utc),
    )

    response = client.get("/api/knowledge-documents", params={
        "search": "资本管理",
        "status": "in_progress",
    })

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [matching_id]


def test_maintainer_receives_safe_error_for_invalid_document_cursor(knowledge_client):
    client, _database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )

    response = client.get("/api/knowledge-documents", params={"cursor": "not-base64"})

    assert response.status_code == 400
    assert response.json()["detail"] == "cursor 无效"


def test_maintainer_reads_document_detail_and_latest_task(knowledge_client):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    document_id = _seed_document(
        database,
        filename="商业银行资本管理办法.pdf",
        state="succeeded",
        size_bytes=1_888_000,
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )

    response = client.get(f"/api/knowledge-documents/{document_id}")

    assert response.status_code == 200
    detail = response.json()
    assert detail["id"] == document_id
    assert detail["original_filename"] == "商业银行资本管理办法.pdf"
    assert detail["size_bytes"] == 1_888_000
    assert detail["uploaded_by"] == {
        "subject": "maintainer-subject",
        "display_name": "知识库维护者",
    }
    assert detail["uploaded_at"] == "2026-08-28T10:20:00Z"
    assert detail["current_version"]["number"] == 1
    assert detail["latest_task"]["state"] == "succeeded"
    assert detail["latest_task"]["status"] == "succeeded"
    assert detail["latest_task"]["result_code"] is None
    assert detail["latest_task"]["result_message"] == "入库完成"
    assert detail["latest_task"]["completed_at"] == "2026-08-28T10:20:00Z"

    missing = client.get(f"/api/knowledge-documents/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "KNOWLEDGE_DOCUMENT_NOT_FOUND"


def test_document_detail_exposes_only_stable_ingestion_failure(knowledge_client):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    document_id = _seed_document(
        database,
        filename="损坏制度.docx",
        state="failed",
        result_code="INGESTION_PARSE_FAILED",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )

    response = client.get(f"/api/knowledge-documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["latest_task"]["result_code"] == (
        "INGESTION_PARSE_FAILED"
    )
    assert response.json()["latest_task"]["result_message"] == "文档解析失败"
    assert "password" not in response.text


@pytest.mark.parametrize("state", ["succeeded", "parsing", "failed"])
def test_maintainer_downloads_latest_original_in_any_ingestion_state(
    download_client,
    state,
):
    client, database, object_store = download_client
    content = f"original-{state}".encode()
    object_key = f"documents/{uuid4()}/original.pdf"
    object_store.objects[object_key] = content
    document_id = _seed_document(
        database,
        filename="商业银行资本管理办法.pdf",
        state=state,
        size_bytes=len(content),
        object_key=object_key,
        content_type="application/pdf",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )

    response = client.get(f"/api/knowledge-documents/{document_id}/download")

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["content-disposition"] == (
        "attachment; filename*=UTF-8''"
        "%E5%95%86%E4%B8%9A%E9%93%B6%E8%A1%8C%E8%B5%84%E6%9C%AC"
        "%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf"
    )


def test_document_download_requires_maintainer_and_active_document(download_client):
    client, database, object_store = download_client
    content = b"original"
    object_key = f"documents/{uuid4()}/original.pdf"
    object_store.objects[object_key] = content
    document_id = _seed_document(
        database,
        filename="监管办法.pdf",
        state="succeeded",
        size_bytes=len(content),
        object_key=object_key,
        content_type="application/pdf",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )

    app.dependency_overrides[get_current_identity] = lambda: _identity("member")
    forbidden = client.get(f"/api/knowledge-documents/{document_id}/download")
    assert forbidden.status_code == 403

    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    assert client.delete(f"/api/knowledge-documents/{document_id}").status_code == 204
    missing = client.get(f"/api/knowledge-documents/{document_id}/download")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "KNOWLEDGE_DOCUMENT_NOT_FOUND"


def test_document_download_returns_404_when_original_is_missing(download_client):
    client, database, _object_store = download_client
    without_object_key = _seed_document(
        database,
        filename="历史监管办法.pdf",
        state="failed",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )
    missing_object = _seed_document(
        database,
        filename="丢失原件的监管办法.pdf",
        state="failed",
        object_key=f"documents/{uuid4()}/original.pdf",
        content_type="application/pdf",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )

    for document_id in (without_object_key, missing_object):
        response = client.get(
            f"/api/knowledge-documents/{document_id}/download"
        )
        assert response.status_code == 404
        assert response.json()["detail"] == {
            "code": "KNOWLEDGE_DOCUMENT_ORIGINAL_NOT_FOUND",
            "message": "知识文档原件不存在",
        }
        assert "documents/" not in response.text


def test_document_download_uses_latest_uploaded_version(download_client):
    client, database, object_store = download_client
    old_key = f"documents/{uuid4()}/original.pdf"
    new_key = f"documents/{uuid4()}/original.docx"
    object_store.objects[old_key] = b"old-version"
    object_store.objects[new_key] = b"latest-version"
    document_id = _seed_document(
        database,
        filename="旧版监管办法.pdf",
        state="succeeded",
        size_bytes=len(object_store.objects[old_key]),
        object_key=old_key,
        content_type="application/pdf",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )
    with database.session() as session, session.begin():
        session.execute(text("""
            INSERT INTO document_versions (
                id, document_id, version_number, original_filename, size_bytes,
                uploaded_by_subject, uploaded_by_name, object_bucket,
                object_key, content_type
            ) VALUES (
                :id, :document_id, 2, :filename, :size_bytes,
                'maintainer-subject', '知识库维护者',
                'knowledge-documents', :object_key, :content_type
            )
        """), {
            "id": uuid4(),
            "document_id": document_id,
            "filename": "新版监管办法.docx",
            "size_bytes": len(object_store.objects[new_key]),
            "object_key": new_key,
            "content_type": (
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document"
            ),
        })

    response = client.get(f"/api/knowledge-documents/{document_id}/download")

    assert response.status_code == 200
    assert response.content == b"latest-version"
    assert response.headers["content-disposition"].endswith(
        "%E6%96%B0%E7%89%88%E7%9B%91%E7%AE%A1%E5%8A%9E%E6%B3%95.docx"
    )


def test_document_download_hides_unexpected_storage_failure(download_client):
    client, database, _object_store = download_client
    document_id = _seed_document(
        database,
        filename="监管办法.pdf",
        state="failed",
        object_key=f"documents/{uuid4()}/original.pdf",
        content_type="application/pdf",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )

    class BrokenObjectStore:
        def open_download(self, _object_key):
            raise RuntimeError("private-minio-host/internal-object-key")

    app.dependency_overrides[get_object_store] = lambda: BrokenObjectStore()
    response = client.get(f"/api/knowledge-documents/{document_id}/download")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "KNOWLEDGE_DOCUMENT_DOWNLOAD_UNAVAILABLE",
        "message": "知识文档暂时无法下载，请稍后重试",
    }
    assert "minio" not in response.text.lower()
    assert "object-key" not in response.text


def test_maintainer_withdraws_document_idempotently_and_audits_each_request(
    knowledge_client,
):
    client, database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    document_id = _seed_document(
        database,
        filename="商业银行资本管理办法.pdf",
        state="succeeded",
        updated_at=datetime(2026, 8, 28, 10, 20, tzinfo=timezone.utc),
    )
    with database.session() as session:
        version_id = session.execute(text("""
            SELECT current_version_id
            FROM knowledge_documents
            WHERE id = :document_id
        """), {"document_id": document_id}).scalar_one()
    chunk = {
        "chunk_id": "online-document-chunk",
        "knowledge_document_id": document_id,
        "document_version_id": str(version_id),
        "text": "应当在撤回后立即不可见",
    }
    assert CurrentVersionVisibility(database).filter([chunk]) == [chunk]

    first = client.delete(
        f"/api/knowledge-documents/{document_id}",
        headers={"X-Request-ID": "withdraw-request-1"},
    )
    repeated = client.delete(
        f"/api/knowledge-documents/{document_id}",
        headers={"X-Request-ID": "withdraw-request-2"},
    )

    assert first.status_code == 204
    assert repeated.status_code == 204
    assert client.get("/api/knowledge-documents").json()["total"] == 0
    assert client.get(f"/api/knowledge-documents/{document_id}").status_code == 404
    assert CurrentVersionVisibility(database).filter([chunk]) == []

    with database.session() as session:
        document = session.execute(text("""
            SELECT current_version_id, deleted_at
            FROM knowledge_documents
            WHERE id = :document_id
        """), {"document_id": document_id}).mappings().one()
        audits = session.execute(text("""
            SELECT actor_subject, action, target_type, target_id,
                   request_id, result, created_at
            FROM audit_events
            WHERE target_id = :document_id
            ORDER BY created_at, request_id
        """), {"document_id": document_id}).mappings().all()
        version_count = session.execute(text("""
            SELECT count(*) FROM document_versions WHERE document_id = :document_id
        """), {"document_id": document_id}).scalar_one()

    assert document["current_version_id"] is None
    assert document["deleted_at"] is not None
    assert version_count == 1
    assert [{key: row[key] for key in (
        "actor_subject", "action", "target_type", "request_id", "result"
    )} for row in audits] == [
        {
            "actor_subject": "knowledge_maintainer-subject",
            "action": "knowledge_document.withdraw",
            "target_type": "knowledge_document",
            "request_id": "withdraw-request-1",
            "result": "succeeded",
        },
        {
            "actor_subject": "knowledge_maintainer-subject",
            "action": "knowledge_document.withdraw",
            "target_type": "knowledge_document",
            "request_id": "withdraw-request-2",
            "result": "already_withdrawn",
        },
    ]
    assert all(str(row["target_id"]) == document_id for row in audits)
    assert all(row["created_at"] is not None for row in audits)


def test_maintainer_receives_not_found_when_withdrawing_unknown_document(
    knowledge_client,
):
    client, _database = knowledge_client
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )

    response = client.delete(f"/api/knowledge-documents/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "KNOWLEDGE_DOCUMENT_NOT_FOUND",
        "message": "知识文档不存在",
    }
