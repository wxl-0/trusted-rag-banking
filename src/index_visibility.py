from sqlalchemy import text

from src.database import Database, DatabaseNotConfigured


class CurrentVersionVisibility:
    """Allow legacy chunks and only published versions of online documents."""

    def __init__(self, database: Database):
        self.database = database

    def filter(self, chunks: list[dict]) -> list[dict]:
        versioned = {
            str(chunk["document_version_id"])
            for chunk in chunks
            if chunk.get("document_version_id")
        }
        if not versioned:
            return chunks
        try:
            with self.database.session() as session:
                active = {
                    str(value)
                    for value in session.execute(text("""
                        SELECT current_version_id
                        FROM knowledge_documents
                        WHERE deleted_at IS NULL
                          AND current_version_id IS NOT NULL
                    """)).scalars()
                }
        except DatabaseNotConfigured:
            active = set()
        return [
            chunk for chunk in chunks
            if not chunk.get("document_version_id")
            or str(chunk["document_version_id"]) in active
        ]
