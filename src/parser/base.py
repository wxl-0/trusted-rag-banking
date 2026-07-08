from dataclasses import dataclass, fields
from typing import Optional, List
import json


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    chunk_type: str          # "clause" | "table_row"
    source_title: str
    issuer: str
    doc_no: str
    publish_date: str        # "YYYY-MM-DD"
    section_path: List[str]
    source_url: str
    local_path: str
    # 表格专用字段（可选）
    table_name: Optional[str] = None
    indicator: Optional[str] = None
    period: Optional[str] = None
    unit: Optional[str] = None
    row_index: Optional[int] = None
    cell_ref: Optional[str] = None
    row_label: Optional[str] = None
    column_header: Optional[str] = None
    raw_value: Optional[str] = None
    page_no: Optional[int] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        allowed = {field.name for field in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in allowed})
