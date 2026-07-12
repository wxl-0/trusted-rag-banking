import tempfile
from pathlib import Path
from typing import Iterable, List

from docx import Document
from docx.document import Document as DocumentType
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.parser.base import Chunk


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONVERTED_DOCX_DIR = PROJECT_ROOT / "data" / "converted" / "docx"


class WordParser:
    def __init__(self, doc_id: str, source_title: str, issuer: str,
                 doc_no: str, publish_date: str, source_url: str, local_path: str):
        self.doc_id = doc_id
        self.source_title = source_title
        self.issuer = issuer
        self.doc_no = doc_no
        self.publish_date = publish_date
        self.source_url = source_url
        self.local_path = local_path

    def parse(self) -> List[Chunk]:
        path = Path(self.local_path)
        parse_path = self._ensure_docx(path)
        document = Document(str(parse_path))

        chunks: List[Chunk] = []
        current_path: list[str] = []
        buffer_text: list[str] = []
        buffer_path: list[str] = []
        table_index = 0

        def flush_buffer() -> None:
            if not buffer_text:
                return
            text = " ".join(buffer_text).strip()
            if text:
                chunks.append(Chunk(
                    doc_id=self.doc_id,
                    chunk_id=f"{self.doc_id}#{'#'.join(buffer_path) if buffer_path else 'body'}",
                    text=text,
                    chunk_type="clause",
                    source_title=self.source_title,
                    issuer=self.issuer,
                    doc_no=self.doc_no,
                    publish_date=self.publish_date,
                    section_path=list(buffer_path),
                    source_url=self.source_url,
                    local_path=self.local_path,
                ))
            buffer_text.clear()

        for block in self._iter_blocks(document):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                style_name = block.style.name if block.style is not None else ""
                heading_level = self._heading_level(style_name, text)
                if heading_level is not None:
                    flush_buffer()
                    current_path = current_path[:heading_level - 1] + [text]
                    buffer_path.clear()
                    buffer_path.extend(current_path)
                else:
                    buffer_text.append(text)
            elif isinstance(block, Table):
                flush_buffer()
                table_index += 1
                chunks.extend(self._table_chunks(block, table_index, current_path))

        flush_buffer()
        return chunks

    def _ensure_docx(self, path: Path) -> Path:
        if path.suffix.lower() != ".doc":
            return path
        cached = CONVERTED_DOCX_DIR / f"{self.doc_id}_{path.stem}.docx"
        if cached.exists() and cached.stat().st_size > 0:
            return cached
        converted = self._convert_doc_to_docx(path)
        if converted is None or not converted.exists():
            raise RuntimeError(
                "Unable to convert .doc file to .docx. "
                "Run: python scripts/convert_doc_to_docx.py --limit 1 --timeout-seconds 60"
            )
        return converted

    def _convert_doc_to_docx(self, path: Path) -> Path | None:
        try:
            import win32com.client
        except ImportError:
            return None

        output = Path(tempfile.gettempdir()) / f"{path.stem}.converted.docx"
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            document = word.Documents.Open(
                str(path.resolve()),
                ConfirmConversions=False,
                ReadOnly=True,
                AddToRecentFiles=False,
                Visible=False,
            )
            document.SaveAs2(str(output.resolve()), FileFormat=16)
            document.Close(False)
            return output
        finally:
            word.Quit()

    def _iter_blocks(self, document: DocumentType) -> Iterable[Paragraph | Table]:
        body = document.element.body
        for child in body.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, document)
            elif isinstance(child, CT_Tbl):
                yield Table(child, document)

    def _heading_level(self, style_name: str, text: str) -> int | None:
        if style_name.startswith("Heading"):
            try:
                return int(style_name.split()[-1])
            except ValueError:
                return 1
        if text.startswith("第") and any(token in text[:8] for token in ("章", "节")):
            return 1 if "章" in text[:8] else 2
        return None

    def _table_chunks(self, table: Table, table_index: int, section_path: list[str]) -> list[Chunk]:
        if len(table.rows) < 2:
            return []
        header_cells = table.rows[0].cells
        headers = self._unique_texts([c.text.strip() for c in header_cells])
        column_header = " | ".join(headers)
        chunks: list[Chunk] = []
        for row_index, row in enumerate(table.rows[1:], start=2):
            cells = row.cells
            row_texts = [c.text.strip() for c in cells]
            if self._is_table_title_or_blank(row_texts):
                continue
            unique_values = self._unique_texts(row_texts)
            if not unique_values:
                continue
            row_label = unique_values[0]
            values = []
            seen_tc = set()
            for col_index, cell in enumerate(cells):
                tc_id = id(cell._tc)
                if tc_id in seen_tc:
                    continue
                seen_tc.add(tc_id)
                value = cell.text.strip()
                if not value:
                    continue
                header = headers[col_index] if col_index < len(headers) and headers[col_index] else f"Column {col_index + 1}"
                entry = f"{header}: {value}"
                if entry not in values:
                    values.append(entry)
            text = (
                f"文件《{self.source_title}》表格 {table_index} 第 {row_index} 行；"
                f"{'；'.join(values)}。"
            )
            chunks.append(Chunk(
                doc_id=self.doc_id,
                chunk_id=f"{self.doc_id}#table{table_index}#R{row_index}",
                text=text,
                chunk_type="table_row",
                source_title=self.source_title,
                issuer=self.issuer,
                doc_no=self.doc_no,
                publish_date=self.publish_date,
                section_path=list(section_path),
                source_url=self.source_url,
                local_path=self.local_path,
                table_name=f"table{table_index}",
                indicator=row_label,
                row_index=row_index,
                row_label=row_label,
                column_header=column_header,
            ))
        return chunks

    def _unique_texts(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = " ".join(str(value).split())
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _is_table_title_or_blank(self, row: list[str]) -> bool:
        unique = self._unique_texts(row)
        if not unique:
            return True
        if len(unique) == 1:
            text = unique[0]
            return text.startswith("附件") or "统计表" in text or "报告表" in text
        return False
