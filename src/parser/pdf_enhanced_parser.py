import re
from typing import List

import fitz

from src.parser.base import Chunk


class PdfEnhancedParser:
    HEADING_THRESHOLD = 14

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
        document = fitz.open(self.local_path)
        chunks: List[Chunk] = []
        current_path: list[str] = []
        buffer_lines: list[str] = []
        buffer_page = 1

        def flush_buffer() -> None:
            if not buffer_lines:
                return
            text = self._clean_text(" ".join(buffer_lines))
            if text:
                chunks.append(Chunk(
                    doc_id=self.doc_id,
                    chunk_id=f"{self.doc_id}#P{buffer_page}#{len(chunks) + 1}",
                    text=text,
                    chunk_type="clause",
                    source_title=self.source_title,
                    issuer=self.issuer,
                    doc_no=self.doc_no,
                    publish_date=self.publish_date,
                    section_path=list(current_path),
                    source_url=self.source_url,
                    local_path=self.local_path,
                    page_no=buffer_page,
                ))
            buffer_lines.clear()

        try:
            for page_index, page in enumerate(document, start=1):
                for text, font_size in self._page_lines(page):
                    if self._is_noise(text):
                        continue
                    if self._is_heading(text, font_size):
                        flush_buffer()
                        current_path = [text]
                        buffer_page = page_index
                    else:
                        if not buffer_lines:
                            buffer_page = page_index
                        buffer_lines.append(text)
            flush_buffer()
        finally:
            document.close()

        return chunks

    def _page_lines(self, page) -> list[tuple[str, float]]:
        lines: list[tuple[str, float]] = []
        blocks = page.get_text("dict")["blocks"]
        for block in blocks:
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                texts = []
                sizes = []
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        texts.append(text)
                        sizes.append(float(span.get("size", 0)))
                line_text = self._clean_text(" ".join(texts))
                if line_text:
                    lines.append((line_text, max(sizes) if sizes else 0))
        return lines

    def _is_heading(self, text: str, font_size: float) -> bool:
        if re.match(
            r"^(第[一二三四五六七八九十百0-9]+[章节]|[一二三四五六七八九十]+、|（[一二三四五六七八九十0-9]+）|Chapter\s+\d+)",
            text,
        ):
            return True
        if font_size >= 16 and len(text) <= 40 and not text.endswith(("。", "；", "，", ",")):
            return True
        return False

    def _is_noise(self, text: str) -> bool:
        if re.fullmatch(r"\d+", text):
            return True
        if len(text) <= 1:
            return True
        return False

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()
