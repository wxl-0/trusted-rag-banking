import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from src.database import Database


@dataclass(frozen=True)
class Conversation:
    id: UUID
    owner_subject: str
    title: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ConversationMessage:
    id: UUID
    conversation_id: UUID
    request_id: str
    role: str
    content: str
    evidence: list[dict]
    refuse_reason: str | None
    latency_ms: int | None
    created_at: datetime
    completed_at: datetime


class ConversationStore:
    def __init__(self, database: Database):
        self.database = database

    def create(self, owner_subject: str) -> Conversation:
        conversation_id = uuid4()
        now = datetime.now(timezone.utc)
        with self.database.session() as session, session.begin():
            row = session.execute(
                text(
                    """
                    INSERT INTO conversations (id, owner_subject, created_at, updated_at)
                    VALUES (:id, :owner_subject, :created_at, :updated_at)
                    RETURNING id, owner_subject, title, created_at, updated_at
                    """
                ),
                {
                    "id": conversation_id,
                    "owner_subject": owner_subject,
                    "created_at": now,
                    "updated_at": now,
                },
            ).mappings().one()
        return Conversation(**row)

    def get_owned(self, conversation_id: UUID, owner_subject: str) -> Conversation | None:
        with self.database.session() as session:
            row = session.execute(
                text(
                    """
                    SELECT id, owner_subject, title, created_at, updated_at
                    FROM conversations
                    WHERE id = :id AND owner_subject = :owner_subject
                      AND deleted_at IS NULL
                    """
                ),
                {"id": conversation_id, "owner_subject": owner_subject},
            ).mappings().one_or_none()
        return Conversation(**row) if row else None

    def list_owned(
        self,
        owner_subject: str,
        *,
        search: str | None,
        before: tuple[datetime, UUID] | None,
        limit: int,
    ) -> list[Conversation]:
        conditions = [
            "owner_subject = :owner_subject",
            "deleted_at IS NULL",
            "title IS NOT NULL",
        ]
        params: dict = {"owner_subject": owner_subject, "limit": limit}
        if search:
            conditions.append("title ILIKE :search")
            params["search"] = f"%{search}%"
        if before:
            conditions.append("(updated_at, id) < (:before_updated_at, :before_id)")
            params["before_updated_at"], params["before_id"] = before

        with self.database.session() as session:
            rows = session.execute(
                text(
                    f"""
                    SELECT id, owner_subject, title, created_at, updated_at
                    FROM conversations
                    WHERE {' AND '.join(conditions)}
                    ORDER BY updated_at DESC, id DESC
                    LIMIT :limit
                    """
                ),
                params,
            ).mappings().all()
        return [Conversation(**row) for row in rows]

    def rename_owned(
        self,
        conversation_id: UUID,
        owner_subject: str,
        title: str,
    ) -> Conversation | None:
        now = datetime.now(timezone.utc)
        with self.database.session() as session, session.begin():
            row = session.execute(
                text(
                    """
                    UPDATE conversations
                    SET title = :title, updated_at = :updated_at
                    WHERE id = :id AND owner_subject = :owner_subject
                      AND deleted_at IS NULL
                    RETURNING id, owner_subject, title, created_at, updated_at
                    """
                ),
                {
                    "id": conversation_id,
                    "owner_subject": owner_subject,
                    "title": title,
                    "updated_at": now,
                },
            ).mappings().one_or_none()
        return Conversation(**row) if row else None

    def delete_owned(self, conversation_id: UUID, owner_subject: str) -> bool:
        now = datetime.now(timezone.utc)
        with self.database.session() as session, session.begin():
            deleted_id = session.execute(
                text(
                    """
                    UPDATE conversations
                    SET deleted_at = :deleted_at, updated_at = :updated_at
                    WHERE id = :id AND owner_subject = :owner_subject
                      AND deleted_at IS NULL
                    RETURNING id
                    """
                ),
                {
                    "id": conversation_id,
                    "owner_subject": owner_subject,
                    "deleted_at": now,
                    "updated_at": now,
                },
            ).scalar_one_or_none()
        return deleted_id is not None

    def list_messages(self, conversation_id: UUID) -> list[ConversationMessage]:
        with self.database.session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT id, conversation_id, request_id, role, content, evidence,
                           refuse_reason, latency_ms, created_at, completed_at
                    FROM conversation_messages
                    WHERE conversation_id = :conversation_id
                    ORDER BY created_at, id
                    """
                ),
                {"conversation_id": conversation_id},
            ).mappings().all()
        return [ConversationMessage(**row) for row in rows]

    def history_for_turn(
        self,
        conversation_id: UUID,
        request_id: str,
    ) -> list[dict[str, str]]:
        with self.database.session() as session:
            rows = session.execute(
                text(
                    """
                    SELECT message.role, message.content
                    FROM conversation_messages AS message
                    WHERE message.conversation_id = :conversation_id
                      AND message.request_id <> :request_id
                      AND EXISTS (
                          SELECT 1
                          FROM conversation_messages AS completed_answer
                          WHERE completed_answer.conversation_id = message.conversation_id
                            AND completed_answer.request_id = message.request_id
                            AND completed_answer.role = 'assistant'
                      )
                    ORDER BY message.created_at, message.id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                },
            ).mappings().all()
        return [
            {"role": row["role"], "content": row["content"]}
            for row in rows
        ]

    def completed_answer(
        self,
        conversation_id: UUID,
        request_id: str,
    ) -> ConversationMessage | None:
        with self.database.session() as session:
            row = session.execute(
                text(
                    """
                    SELECT id, conversation_id, request_id, role, content, evidence,
                           refuse_reason, latency_ms, created_at, completed_at
                    FROM conversation_messages
                    WHERE conversation_id = :conversation_id
                      AND request_id = :request_id
                      AND role = 'assistant'
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                },
            ).mappings().one_or_none()
        return ConversationMessage(**row) if row else None

    def start_turn(
        self,
        conversation_id: UUID,
        request_id: str,
        question: str,
    ) -> str:
        message_id = uuid4()
        now = datetime.now(timezone.utc)
        with self.database.session() as session, session.begin():
            inserted_question = session.execute(
                text(
                    """
                    INSERT INTO conversation_messages (
                        id, conversation_id, request_id, role, content,
                        evidence, created_at, completed_at
                    )
                    VALUES (
                        :id, :conversation_id, :request_id, 'user', :content,
                        CAST(:evidence AS jsonb), :created_at, :completed_at
                    )
                    ON CONFLICT (conversation_id, request_id, role) DO NOTHING
                    RETURNING content
                    """
                ),
                {
                    "id": message_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "content": question,
                    "evidence": "[]",
                    "created_at": now,
                    "completed_at": now,
                },
            ).scalar_one_or_none()
            if inserted_question is not None:
                session.execute(
                    text(
                        """
                        UPDATE conversations
                        SET updated_at = :updated_at
                        WHERE id = :conversation_id
                        """
                    ),
                    {"conversation_id": conversation_id, "updated_at": now},
                )
                return inserted_question

            return session.execute(
                text(
                    """
                    SELECT content
                    FROM conversation_messages
                    WHERE conversation_id = :conversation_id
                      AND request_id = :request_id
                      AND role = 'user'
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                },
            ).scalar_one()

    def complete_turn(
        self,
        conversation_id: UUID,
        request_id: str,
        answer: dict,
    ) -> ConversationMessage:
        message_id = uuid4()
        now = datetime.now(timezone.utc)
        with self.database.session() as session, session.begin():
            session.execute(
                text(
                    """
                    INSERT INTO conversation_messages (
                        id, conversation_id, request_id, role, content,
                        evidence, refuse_reason, latency_ms, created_at, completed_at
                    )
                    VALUES (
                        :id, :conversation_id, :request_id, 'assistant', :content,
                        CAST(:evidence AS jsonb), :refuse_reason, :latency_ms,
                        :created_at, :completed_at
                    )
                    ON CONFLICT (conversation_id, request_id, role) DO NOTHING
                    """
                ),
                {
                    "id": message_id,
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "content": answer["answer"],
                    "evidence": json.dumps(answer["evidence"], ensure_ascii=False),
                    "refuse_reason": answer.get("refuse_reason"),
                    "latency_ms": answer["latency_ms"],
                    "created_at": now,
                    "completed_at": now,
                },
            )
            session.execute(
                text(
                    """
                    UPDATE conversations
                    SET updated_at = :updated_at,
                        title = COALESCE(
                            title,
                            (
                                SELECT content
                                FROM conversation_messages
                                WHERE conversation_id = :conversation_id
                                  AND request_id = :request_id
                                  AND role = 'user'
                            )
                        )
                    WHERE id = :conversation_id
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                    "updated_at": now,
                },
            )
            row = session.execute(
                text(
                    """
                    SELECT id, conversation_id, request_id, role, content, evidence,
                           refuse_reason, latency_ms, created_at, completed_at
                    FROM conversation_messages
                    WHERE conversation_id = :conversation_id
                      AND request_id = :request_id
                      AND role = 'assistant'
                    """
                ),
                {
                    "conversation_id": conversation_id,
                    "request_id": request_id,
                },
            ).mappings().one()
        return ConversationMessage(**row)
