from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Literal, Optional, List


class ChatMessage(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str
    filters: Optional[dict] = None
    history: Optional[List[ChatMessage]] = None
    conversation_id: Optional[UUID] = None
    request_id: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_request_id_for_conversation(self):
        if self.conversation_id is not None and not self.request_id:
            raise ValueError("request_id is required with conversation_id")
        return self


class EvidenceItem(BaseModel):
    source_title: str
    section: str = ""
    text: str
    source_url: str = ""


class AskResponse(BaseModel):
    answer: str
    evidence: List[EvidenceItem]
    refuse_reason: Optional[str] = None
    latency_ms: int


class IngestRequest(BaseModel):
    manifest_path: str = "data/manifest.json"


class IdentityResponse(BaseModel):
    subject: str
    username: str
    display_name: str
    email: Optional[str] = None
    business_role: str
    roles: List[str]


class KnowledgeDocumentSummaryResponse(BaseModel):
    succeeded: int
    in_progress: int
    failed: int
    updated_at: Optional[datetime] = None


class KnowledgeDocumentListItemResponse(BaseModel):
    id: UUID
    sequence: int
    filename: str
    size_bytes: int
    status: Literal["succeeded", "in_progress", "failed"]
    updated_at: datetime


class KnowledgeDocumentListResponse(BaseModel):
    items: List[KnowledgeDocumentListItemResponse]
    next_cursor: Optional[str] = None


class KnowledgeDocumentUploaderResponse(BaseModel):
    subject: str
    display_name: str


class KnowledgeDocumentVersionResponse(BaseModel):
    id: UUID
    number: int


class IngestionTaskResponse(BaseModel):
    id: UUID
    state: Literal["queued", "parsing", "indexing", "succeeded", "failed"]
    status: Literal["succeeded", "in_progress", "failed"]
    result_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class KnowledgeDocumentDetailResponse(BaseModel):
    id: UUID
    original_filename: str
    size_bytes: int
    uploaded_by: KnowledgeDocumentUploaderResponse
    uploaded_at: datetime
    updated_at: datetime
    current_version: Optional[KnowledgeDocumentVersionResponse] = None
    latest_task: Optional[IngestionTaskResponse] = None


class ConversationResponse(BaseModel):
    id: UUID
    owner_subject: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List["ConversationMessageResponse"]


class ConversationMessageResponse(BaseModel):
    id: UUID
    request_id: str
    role: str
    content: str
    evidence: List[EvidenceItem]
    refuse_reason: Optional[str] = None
    latency_ms: Optional[int] = None
    created_at: datetime
    completed_at: datetime


class ConversationSummaryResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    items: List[ConversationSummaryResponse]
    next_cursor: Optional[str] = None


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title cannot be blank")
        return title
