import hashlib
import json
import os
from io import BytesIO
from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from fastapi import UploadFile
from minio import Minio
from redis import Redis
from sqlalchemy import text

from src.auth import Identity
from src.database import Database


DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SUPPORTED_CONTENT_TYPES = {
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")


class UploadRejected(ValueError):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


class UploadUnavailable(RuntimeError):
    pass


class MinioObjectStore:
    def __init__(self):
        self.bucket_name = os.getenv("MINIO_BUCKET", "knowledge-documents")
        self.client = Minio(
            os.getenv("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            secure=os.getenv("MINIO_SECURE", "0") == "1",
        )

    def put(self, object_key, stream, size_bytes, content_type):
        if not self.client.bucket_exists(self.bucket_name):
            self.client.make_bucket(self.bucket_name)
        self.client.put_object(
            self.bucket_name,
            object_key,
            stream,
            size_bytes,
            content_type=content_type,
        )

    def delete(self, object_key):
        self.client.remove_object(self.bucket_name, object_key)

    def download(self, object_key, destination):
        self.client.fget_object(
            self.bucket_name,
            object_key,
            str(destination),
        )

    def put_bytes(self, object_key, content, content_type):
        if not self.client.bucket_exists(self.bucket_name):
            self.client.make_bucket(self.bucket_name)
        self.client.put_object(
            self.bucket_name,
            object_key,
            BytesIO(content),
            len(content),
            content_type=content_type,
        )


class RedisIngestionQueue:
    def __init__(self):
        self.client = Redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
        )
        self.queue_name = os.getenv(
            "INGESTION_QUEUE_NAME",
            "trusted-rag:ingestion",
        )

    def enqueue(self, job):
        self.client.rpush(
            self.queue_name,
            json.dumps(job, ensure_ascii=False, separators=(",", ":")),
        )

    def dequeue(self, timeout: int = 5):
        result = self.client.blpop(self.queue_name, timeout=timeout)
        if result is None:
            return None
        _queue_name, payload = result
        return json.loads(payload)


@lru_cache(maxsize=1)
def get_object_store() -> MinioObjectStore:
    return MinioObjectStore()


@lru_cache(maxsize=1)
def get_ingestion_queue() -> RedisIngestionQueue:
    return RedisIngestionQueue()


def _max_upload_bytes() -> int:
    try:
        return int(os.getenv("KNOWLEDGE_UPLOAD_MAX_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
    except ValueError as exc:
        raise UploadUnavailable("上传大小限制配置无效") from exc


async def _inspect_upload(file: UploadFile) -> dict:
    filename = Path(file.filename or "").name
    extension = Path(filename).suffix.lower()
    if not filename or extension not in SUPPORTED_CONTENT_TYPES:
        raise UploadRejected(422, "UPLOAD_UNSUPPORTED_FORMAT", "仅支持 DOC、DOCX、PDF、XLS 和 XLSX 文件")

    maximum = _max_upload_bytes()
    size_bytes = 0
    checksum = hashlib.sha256()
    header = bytearray()
    while chunk := await file.read(1024 * 1024):
        size_bytes += len(chunk)
        if size_bytes > maximum:
            raise UploadRejected(413, "UPLOAD_TOO_LARGE", "文件超过允许的大小限制")
        checksum.update(chunk)
        if len(header) < 4096:
            header.extend(chunk[:4096 - len(header)])

    if size_bytes == 0:
        raise UploadRejected(422, "UPLOAD_EMPTY_FILE", "不能上传空文件")

    await file.seek(0)
    valid = False
    if extension == ".pdf":
        valid = b"%PDF-" in header[:1024]
    elif extension in {".doc", ".xls"}:
        valid = bytes(header[:8]) == OLE_SIGNATURE
    else:
        try:
            with ZipFile(file.file) as archive:
                names = set(archive.namelist())
            required = "word/document.xml" if extension == ".docx" else "xl/workbook.xml"
            valid = "[Content_Types].xml" in names and required in names
        except BadZipFile:
            valid = False
        finally:
            await file.seek(0)

    if not valid:
        raise UploadRejected(422, "UPLOAD_INVALID_CONTENT", "文件内容与扩展名不匹配或文件已损坏")

    return {
        "filename": filename,
        "extension": extension,
        "size_bytes": size_bytes,
        "checksum_sha256": checksum.hexdigest(),
        "content_type": SUPPORTED_CONTENT_TYPES[extension],
    }


class DocumentUploadService:
    def __init__(self, database, object_store, ingestion_queue):
        self.database = database
        self.object_store = object_store
        self.ingestion_queue = ingestion_queue

    async def accept(self, file: UploadFile, identity: Identity) -> dict:
        metadata = await _inspect_upload(file)
        document_id = uuid4()
        version_id = uuid4()
        task_id = uuid4()
        object_key = (
            f"documents/{document_id}/versions/{version_id}/original"
            f"{metadata['extension']}"
        )

        try:
            self.object_store.put(
                object_key,
                file.file,
                metadata["size_bytes"],
                metadata["content_type"],
            )
        except Exception as exc:
            raise UploadUnavailable("原始文件暂时无法保存，请稍后重试") from exc

        try:
            with self.database.session() as session, session.begin():
                session.execute(text("""
                    INSERT INTO knowledge_documents (id)
                    VALUES (:document_id)
                """), {"document_id": document_id})
                session.execute(text("""
                    INSERT INTO document_versions (
                        id, document_id, version_number, original_filename,
                        size_bytes, uploaded_by_subject, uploaded_by_name,
                        object_bucket, object_key, checksum_sha256, content_type
                    ) VALUES (
                        :version_id, :document_id, 1, :filename,
                        :size_bytes, :uploader_subject, :uploader_name,
                        :object_bucket, :object_key, :checksum_sha256, :content_type
                    )
                """), {
                    "version_id": version_id,
                    "document_id": document_id,
                    "filename": metadata["filename"],
                    "size_bytes": metadata["size_bytes"],
                    "uploader_subject": identity.subject,
                    "uploader_name": identity.display_name,
                    "object_bucket": self.object_store.bucket_name,
                    "object_key": object_key,
                    "checksum_sha256": metadata["checksum_sha256"],
                    "content_type": metadata["content_type"],
                })
                session.execute(text("""
                    INSERT INTO ingestion_tasks (
                        id, document_version_id, state
                    ) VALUES (
                        :task_id, :version_id, 'queued'
                    )
                """), {"task_id": task_id, "version_id": version_id})
        except Exception:
            self.object_store.delete(object_key)
            raise

        job = {
            "document_id": str(document_id),
            "version_id": str(version_id),
            "task_id": str(task_id),
        }
        try:
            self.ingestion_queue.enqueue(job)
        except Exception as exc:
            with self.database.session() as session, session.begin():
                session.execute(text("""
                    UPDATE ingestion_tasks
                    SET state = 'failed',
                        result_message = '任务排队失败',
                        updated_at = now(),
                        completed_at = now()
                    WHERE id = :task_id
                """), {"task_id": task_id})
            self.object_store.delete(object_key)
            raise UploadUnavailable("入库任务暂时无法排队，请稍后重试") from exc

        with self.database.session() as session, session.begin():
            session.execute(text("""
                INSERT INTO audit_events (
                    id, actor_subject, action, target_type,
                    target_id, request_id, result
                ) VALUES (
                    :id, :actor_subject, 'knowledge_document.upload_accepted',
                    'knowledge_document', :target_id, :request_id, 'accepted'
                )
            """), {
                "id": uuid4(),
                "actor_subject": identity.subject,
                "target_id": document_id,
                "request_id": str(uuid4()),
            })
        return {**job, "status": "in_progress"}
