from io import BytesIO
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.auth import Identity, get_current_identity
from src.database import Database, get_database
from src.document_uploads import get_ingestion_queue, get_object_store


def _docx_bytes() -> bytes:
    content = BytesIO()
    with ZipFile(content, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>',
        )
    return content.getvalue()


def _xlsx_bytes() -> bytes:
    content = BytesIO()
    with ZipFile(content, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        )
    return content.getvalue()


class RecordingObjectStore:
    bucket_name = "knowledge-documents"

    def __init__(self):
        self.objects = []

    def put(self, object_key, stream, size_bytes, content_type):
        self.objects.append({
            "object_key": object_key,
            "content": stream.read(),
            "size_bytes": size_bytes,
            "content_type": content_type,
        })

    def delete(self, object_key):
        self.objects = [item for item in self.objects if item["object_key"] != object_key]


class RecordingIngestionQueue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, job):
        self.jobs.append(job)


class UnavailableObjectStore(RecordingObjectStore):
    def put(self, object_key, stream, size_bytes, content_type):
        raise ConnectionError("storage password=do-not-leak")


class UnavailableIngestionQueue(RecordingIngestionQueue):
    def enqueue(self, job):
        raise ConnectionError("redis://secret@internal-host")


@pytest.fixture
def upload_client(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    object_store = RecordingObjectStore()
    queue = RecordingIngestionQueue()
    identity = Identity(
        subject="maintainer-subject",
        username="maintainer",
        display_name="知识库维护者",
        email=None,
        roles=frozenset({"knowledge_maintainer"}),
    )
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_current_identity] = lambda: identity
    app.dependency_overrides[get_object_store] = lambda: object_store
    app.dependency_overrides[get_ingestion_queue] = lambda: queue
    try:
        with TestClient(app) as client:
            yield client, database, object_store, queue
    finally:
        app.dependency_overrides.clear()
        database.dispose()


def test_maintainer_uploads_one_document_and_receives_queued_task(upload_client):
    client, database, object_store, queue = upload_client
    content = _docx_bytes()

    response = client.post(
        "/api/knowledge-documents",
        files={
            "file": (
                "商业银行资本管理办法.docx",
                content,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "in_progress"
    assert set(payload) == {"document_id", "version_id", "task_id", "status"}
    assert len(object_store.objects) == 1
    assert object_store.objects[0]["content"] == content
    assert object_store.objects[0]["object_key"].endswith(".docx")
    assert queue.jobs == [{
        "document_id": payload["document_id"],
        "version_id": payload["version_id"],
        "task_id": payload["task_id"],
    }]

    with database.session() as session:
        version = session.execute(text("""
            SELECT original_filename, size_bytes, object_bucket, object_key,
                   checksum_sha256, uploaded_by_subject
            FROM document_versions
        """)).mappings().one()
        task = session.execute(text("""
            SELECT state FROM ingestion_tasks
        """)).mappings().one()
        audit = session.execute(text("""
            SELECT actor_subject, action, target_type, target_id, result
            FROM audit_events
        """)).mappings().one()

    assert version["original_filename"] == "商业银行资本管理办法.docx"
    assert version["size_bytes"] == len(content)
    assert version["object_bucket"] == "knowledge-documents"
    assert version["object_key"] == object_store.objects[0]["object_key"]
    assert len(version["checksum_sha256"]) == 64
    assert version["uploaded_by_subject"] == "maintainer-subject"
    assert task["state"] == "queued"
    assert {
        key: audit[key]
        for key in ("actor_subject", "action", "target_type", "result")
    } == {
        "actor_subject": "maintainer-subject",
        "action": "knowledge_document.upload_accepted",
        "target_type": "knowledge_document",
        "result": "accepted",
    }
    assert str(audit["target_id"]) == payload["document_id"]


def test_upload_rejects_more_than_one_file_before_creating_work(upload_client):
    client, database, object_store, queue = upload_client
    content = _docx_bytes()

    response = client.post(
        "/api/knowledge-documents",
        files=[
            ("file", ("第一份.docx", content, "application/octet-stream")),
            ("file", ("第二份.docx", content, "application/octet-stream")),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "UPLOAD_FILE_COUNT",
        "message": "每次只能上传一个知识文档",
    }
    assert object_store.objects == []
    assert queue.jobs == []
    with database.session() as session:
        assert session.execute(text("SELECT count(*) FROM knowledge_documents")).scalar_one() == 0


@pytest.mark.parametrize(("filename", "content"), [
    ("制度.doc", bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy-word"),
    ("制度.pdf", b"%PDF-1.7\n%%EOF"),
    ("数据.xls", bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy-excel"),
    ("数据.xlsx", _xlsx_bytes()),
])
def test_each_other_supported_format_is_accepted(upload_client, filename, content):
    client, _, object_store, queue = upload_client

    response = client.post(
        "/api/knowledge-documents",
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == 202
    assert object_store.objects[0]["content"] == content
    assert len(queue.jobs) == 1


@pytest.mark.parametrize(("filename", "content", "code", "message"), [
    (
        "说明.txt",
        b"plain text",
        "UPLOAD_UNSUPPORTED_FORMAT",
        "仅支持 DOC、DOCX、PDF、XLS 和 XLSX 文件",
    ),
    (
        "空文件.pdf",
        b"",
        "UPLOAD_EMPTY_FILE",
        "不能上传空文件",
    ),
    (
        "伪装文件.docx",
        b"this is not an office document",
        "UPLOAD_INVALID_CONTENT",
        "文件内容与扩展名不匹配或文件已损坏",
    ),
])
def test_invalid_upload_is_rejected_before_creating_work(
    upload_client,
    filename,
    content,
    code,
    message,
):
    client, database, object_store, queue = upload_client

    response = client.post(
        "/api/knowledge-documents",
        files={"file": (filename, content, "application/octet-stream")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {"code": code, "message": message}
    assert object_store.objects == []
    assert queue.jobs == []
    with database.session() as session:
        assert session.execute(text("SELECT count(*) FROM knowledge_documents")).scalar_one() == 0


def test_upload_limit_is_configurable_and_checked_before_creating_work(
    upload_client,
    monkeypatch,
):
    client, database, object_store, queue = upload_client
    monkeypatch.setenv("KNOWLEDGE_UPLOAD_MAX_BYTES", "10")

    response = client.post(
        "/api/knowledge-documents",
        files={"file": ("过大文件.pdf", b"%PDF-1.7xxxxxx", "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["detail"] == {
        "code": "UPLOAD_TOO_LARGE",
        "message": "文件超过允许的大小限制",
    }
    assert object_store.objects == []
    assert queue.jobs == []
    with database.session() as session:
        assert session.execute(text("SELECT count(*) FROM knowledge_documents")).scalar_one() == 0


def test_member_cannot_upload_knowledge_document(upload_client):
    client, database, object_store, queue = upload_client
    app.dependency_overrides[get_current_identity] = lambda: Identity(
        subject="member-subject",
        username="member",
        display_name="企业成员",
        email=None,
        roles=frozenset({"member"}),
    )

    response = client.post(
        "/api/knowledge-documents",
        files={"file": ("制度.docx", _docx_bytes(), "application/octet-stream")},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "KNOWLEDGE_MAINTAINER_REQUIRED"
    assert object_store.objects == []
    assert queue.jobs == []
    with database.session() as session:
        assert session.execute(text("SELECT count(*) FROM knowledge_documents")).scalar_one() == 0


def test_storage_failure_returns_safe_error_without_database_work(upload_client):
    client, database, _, queue = upload_client
    app.dependency_overrides[get_object_store] = UnavailableObjectStore

    response = client.post(
        "/api/knowledge-documents",
        files={"file": ("制度.docx", _docx_bytes(), "application/octet-stream")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "UPLOAD_UNAVAILABLE",
        "message": "原始文件暂时无法保存，请稍后重试",
    }
    assert queue.jobs == []
    assert "password" not in response.text
    with database.session() as session:
        assert session.execute(text("SELECT count(*) FROM knowledge_documents")).scalar_one() == 0


def test_queue_failure_marks_task_failed_and_removes_private_object(upload_client):
    client, database, object_store, _ = upload_client
    app.dependency_overrides[get_ingestion_queue] = UnavailableIngestionQueue

    response = client.post(
        "/api/knowledge-documents",
        files={"file": ("制度.docx", _docx_bytes(), "application/octet-stream")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "UPLOAD_UNAVAILABLE",
        "message": "入库任务暂时无法排队，请稍后重试",
    }
    assert object_store.objects == []
    assert "internal-host" not in response.text
    with database.session() as session:
        task = session.execute(text("""
            SELECT state, result_message FROM ingestion_tasks
        """)).mappings().one()
        assert task == {"state": "failed", "result_message": "任务排队失败"}
        assert session.execute(text("SELECT count(*) FROM audit_events")).scalar_one() == 0
