import re
import openpyxl
from typing import List
from src.parser.base import Chunk


class ExcelParser:
    def __init__(self, doc_id: str, source_title: str, issuer: str,
                 publish_date: str, source_url: str, local_path: str):
        self.doc_id = doc_id
        self.source_title = source_title
        self.issuer = issuer
        self.publish_date = publish_date
        self.source_url = source_url
        self.local_path = local_path

    def parse(self) -> List[Chunk]:
        wb = openpyxl.load_workbook(self.local_path, data_only=True)
        chunks = []
        for sheet in wb.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if len(rows) < 2:
                continue
            headers = [str(h).strip() if h is not None else "" for h in rows[0]]
            period = self._detect_period(headers)
            for row_idx, row in enumerate(rows[1:], start=1):
                if not any(cell for cell in row):
                    continue
                indicator = str(row[0]).strip() if row[0] else ""
                value = row[1] if len(row) > 1 else None
                unit = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                text = self._build_text(indicator, value, unit, period)
                chunk_id = f"{self.doc_id}#{sheet.title}#R{row_idx}"
                chunks.append(Chunk(
                    doc_id=self.doc_id,
                    chunk_id=chunk_id,
                    text=text,
                    chunk_type="table_row",
                    source_title=self.source_title,
                    issuer=self.issuer,
                    doc_no="",
                    publish_date=self.publish_date,
                    section_path=[],
                    source_url=self.source_url,
                    local_path=self.local_path,
                    table_name=sheet.title,
                    indicator=indicator,
                    period=period,
                    unit=unit,
                    row_index=row_idx,
                ))
        return chunks

    def _detect_period(self, headers: list) -> str:
        for h in headers:
            m = re.search(r"(20\d{2})(Q[1-4]|年[0-9]{1,2}月)", h)
            if m:
                return m.group(0)
            m = re.search(r"20\d{2}Q[1-4]", h)
            if m:
                return m.group(0)
        return ""

    def _build_text(self, indicator: str, value, unit: str, period: str) -> str:
        if value is None:
            return f"{indicator}：数据缺失"
        period_str = f"{period}，" if period else ""
        return f"{period_str}{indicator}为{value}{unit}"
from src.parser.excel_cell_parser import ExcelCellParser as ExcelParser
