from sqlalchemy import text
from uuid import UUID

from src.database import Database


_DOCUMENT_ROWS = """
    WITH latest_version AS (
        SELECT DISTINCT ON (version.document_id)
            version.id,
            version.document_id,
            version.original_filename,
            version.size_bytes,
            version.updated_at
        FROM document_versions AS version
        ORDER BY version.document_id, version.version_number DESC, version.id DESC
    ),
    latest_task AS (
        SELECT DISTINCT ON (task.document_version_id)
            task.document_version_id,
            task.state,
            task.updated_at
        FROM ingestion_tasks AS task
        ORDER BY task.document_version_id, task.created_at DESC, task.id DESC
    ),
    document_rows AS (
        SELECT
            document.id,
            version.original_filename AS filename,
            version.size_bytes,
            CASE
                WHEN task.state = 'succeeded' THEN 'succeeded'
                WHEN task.state = 'failed' THEN 'failed'
                ELSE 'in_progress'
            END AS status,
            GREATEST(
                document.updated_at,
                version.updated_at,
                COALESCE(task.updated_at, version.updated_at)
            ) AS updated_at
        FROM knowledge_documents AS document
        JOIN latest_version AS version ON version.document_id = document.id
        LEFT JOIN latest_task AS task ON task.document_version_id = version.id
        WHERE document.deleted_at IS NULL
    )
"""


class KnowledgeDocumentStore:
    def __init__(self, database: Database):
        self.database = database

    def summary(self) -> dict:
        with self.database.session() as session:
            row = session.execute(text("""
                WITH latest_task AS (
                    SELECT DISTINCT ON (version.document_id)
                        version.document_id,
                        task.state,
                        task.updated_at
                    FROM document_versions AS version
                    JOIN ingestion_tasks AS task
                      ON task.document_version_id = version.id
                    ORDER BY version.document_id,
                             version.version_number DESC,
                             task.created_at DESC,
                             task.id DESC
                )
                SELECT
                    COUNT(*) FILTER (
                        WHERE latest_task.state = 'succeeded'
                    ) AS succeeded,
                    COUNT(*) FILTER (
                        WHERE latest_task.state = 'failed'
                    ) AS failed,
                    COUNT(*) FILTER (
                        WHERE latest_task.state IS NULL
                           OR latest_task.state IN ('queued', 'parsing', 'indexing')
                    ) AS in_progress,
                    MAX(GREATEST(
                        document.updated_at,
                        COALESCE(latest_task.updated_at, document.updated_at)
                    )) AS updated_at
                FROM knowledge_documents AS document
                LEFT JOIN latest_task ON latest_task.document_id = document.id
                WHERE document.deleted_at IS NULL
            """)).mappings().one()
        return dict(row)

    def list(
        self,
        *,
        search: str | None,
        status: str | None,
        before: tuple | None,
        limit: int,
    ) -> list[dict]:
        conditions = []
        params: dict = {"limit": limit}
        if search:
            conditions.append("filename ILIKE :search")
            params["search"] = f"%{search}%"
        if status:
            conditions.append("status = :status")
            params["status"] = status
        if before:
            conditions.append(
                "(updated_at < :before_updated_at "
                "OR (updated_at = :before_updated_at AND id < :before_id))"
            )
            params["before_updated_at"], params["before_id"] = before
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with self.database.session() as session:
            rows = session.execute(text(f"""
                {_DOCUMENT_ROWS}
                SELECT id, filename, size_bytes, status, updated_at
                FROM document_rows
                {where}
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
            """), params).mappings().all()
        return [dict(row) for row in rows]

    def get(self, document_id: UUID) -> dict | None:
        with self.database.session() as session:
            row = session.execute(text("""
                SELECT
                    document.id,
                    latest_version.original_filename,
                    latest_version.size_bytes,
                    latest_version.uploaded_by_subject,
                    latest_version.uploaded_by_name,
                    latest_version.created_at AS uploaded_at,
                    GREATEST(
                        document.updated_at,
                        latest_version.updated_at,
                        COALESCE(latest_task.updated_at, latest_version.updated_at)
                    ) AS updated_at,
                    current_version.id AS current_version_id,
                    current_version.version_number AS current_version_number,
                    latest_task.id AS latest_task_id,
                    latest_task.state AS latest_task_state,
                    CASE
                        WHEN latest_task.state = 'succeeded' THEN 'succeeded'
                        WHEN latest_task.state = 'failed' THEN 'failed'
                        ELSE 'in_progress'
                    END AS latest_task_status,
                    latest_task.result_message,
                    latest_task.created_at AS task_created_at,
                    latest_task.updated_at AS task_updated_at,
                    latest_task.started_at,
                    latest_task.completed_at
                FROM knowledge_documents AS document
                JOIN LATERAL (
                    SELECT version.*
                    FROM document_versions AS version
                    WHERE version.document_id = document.id
                    ORDER BY version.version_number DESC, version.id DESC
                    LIMIT 1
                ) AS latest_version ON TRUE
                LEFT JOIN document_versions AS current_version
                  ON current_version.id = document.current_version_id
                LEFT JOIN LATERAL (
                    SELECT task.*
                    FROM ingestion_tasks AS task
                    WHERE task.document_version_id = latest_version.id
                    ORDER BY task.created_at DESC, task.id DESC
                    LIMIT 1
                ) AS latest_task ON TRUE
                WHERE document.id = :document_id
                  AND document.deleted_at IS NULL
            """), {"document_id": document_id}).mappings().one_or_none()
        if row is None:
            return None
        return {
            "id": row["id"],
            "original_filename": row["original_filename"],
            "size_bytes": row["size_bytes"],
            "uploaded_by": {
                "subject": row["uploaded_by_subject"],
                "display_name": row["uploaded_by_name"],
            },
            "uploaded_at": row["uploaded_at"],
            "updated_at": row["updated_at"],
            "current_version": (
                {
                    "id": row["current_version_id"],
                    "number": row["current_version_number"],
                }
                if row["current_version_id"] else None
            ),
            "latest_task": (
                {
                    "id": row["latest_task_id"],
                    "state": row["latest_task_state"],
                    "status": row["latest_task_status"],
                    "result_message": row["result_message"],
                    "created_at": row["task_created_at"],
                    "updated_at": row["task_updated_at"],
                    "started_at": row["started_at"],
                    "completed_at": row["completed_at"],
                }
                if row["latest_task_id"] else None
            ),
        }
