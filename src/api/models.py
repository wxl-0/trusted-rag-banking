from pydantic import BaseModel
from typing import Optional, List


class AskRequest(BaseModel):
    question: str
    filters: Optional[dict] = None


class EvidenceItem(BaseModel):
    source_title: str
    section: str = ""
    text: str
    source_url: str = ""


class AskResponse(BaseModel):
    answer: str
    confidence: str
    evidence: List[EvidenceItem]
    refuse_reason: Optional[str] = None
    latency_ms: int


class IngestRequest(BaseModel):
    manifest_path: str = "data/manifest.json"
