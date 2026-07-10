"""
PDF 表格提取解析器。
使用 pdfplumber 从 PDF 中提取表格，输出 table_row 类型 Chunk。
适用于统计报告类 PDF（parse_profile=pdf_table）。
"""
from pathlib import Path
from typing import List

import pdfplumber

from src.parser.base import Chunk


class PdfTableParser:
    def __init__(self, doc_id: str, source_title: str, issuer: str,
                 publish_date: str, source_url: str, local_path: str):
        self.doc_id = doc_id
        self.source_title = source_title
        self.issuer = issuer
        self.publish_date = publish_date
        self.source_url = source_url
        self.local_path = local_path

    def parse(self) -> List[Chunk]:
        chunks: List[Chunk] = []
        with pdfplumber.open(self.local_path) as pdf:
            for page_idx, page in enumerate(pdf.pages, 1):
                tables = page.extract_tables()
                if not tables:
                    continue
                for table_idx, table in enumerate(tables, 1):
                    chunks.extend(self._parse_table(table, page_idx, table_idx))
        return chunks

    def _parse_table(self, table: list, page_idx: int, table_idx: int) -> List[Chunk]:
        if not table or len(table) < 2:
            return []

        header = [self._clean(cell) for cell in table[0]]
        chunks: List[Chunk] = []

        for row_idx, row in enumerate(table[1:], 1):
            row_label = self._clean(row[0]) if row else ""
            if not row_label:
                continue

            for col_idx in range(1, len(row)):
                value = self._clean(row[col_idx]) if col_idx < len(row) else ""
                if not value:
                    continue
                col_header = header[col_idx] if col_idx < len(header) else ""
                if not col_header:
                    continue

                cell_ref = f"P{page_idx}T{table_idx}R{row_idx}C{col_idx + 1}"
                text = self._build_text(page_idx, row_label, col_header, value)
                chunks.append(Chunk(
                    doc_id=self.doc_id,
                    chunk_id=f"{self.doc_id}#{cell_ref}",
                    text=text,
                    chunk_type="table_row",
                    source_title=self.source_title,
                    issuer=self.issuer,
                    doc_no="",
                    publish_date=self.publish_date,
                    section_path=[],
                    source_url=self.source_url,
                    local_path=self.local_path,
                    table_name=f"Page{page_idx}_Table{table_idx}",
                    row_label=row_label,
                    column_header=col_header,
                    raw_value=value,
                ))
        return chunks

    def _build_text(self, page_idx: int, row_label: str, col_header: str, value: str) -> str:
        parts = [
            f"文件《{self.source_title}》",
            f"页码 P{page_idx}",
            f"行指标「{row_label}」",
            f"列口径「{col_header}」",
            f"原始值为 {value}",
        ]
        return "；".join(parts) + "。"

    def _clean(self, cell) -> str:
        if cell is None:
            return ""
        return str(cell).strip().replace("\n", " ")
