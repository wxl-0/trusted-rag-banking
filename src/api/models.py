from pydantic import BaseModel
from typing import Optional, List


class ChatMessage(BaseModel):
    role: str
    content: str


class AskRequest(BaseModel):
    question: str
    filters: Optional[dict] = None
    history: Optional[List[ChatMessage]] = None


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
