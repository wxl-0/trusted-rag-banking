import fitz  # pymupdf
from typing import List
from src.parser.base import Chunk


class PdfParser:
    HEADING_THRESHOLD = 14  # 字体大小超过此值视为标题

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
        doc = fitz.open(self.local_path)
        chunks = []
        current_path = []
        buffer_lines = []

        def flush_buffer():
            if buffer_lines:
                text = " ".join(buffer_lines).strip()
                if text:
                    chunk_id = f"{self.doc_id}#{'#'.join(current_path) if current_path else 'body'}"
                    chunks.append(Chunk(
                        doc_id=self.doc_id,
                        chunk_id=chunk_id,
                        text=text,
                        chunk_type="clause",
                        source_title=self.source_title,
                        issuer=self.issuer,
                        doc_no=self.doc_no,
                        publish_date=self.publish_date,
                        section_path=list(current_path),
                        source_url=self.source_url,
                        local_path=self.local_path,
                    ))
                buffer_lines.clear()

        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        if span["size"] >= self.HEADING_THRESHOLD:
                            flush_buffer()
                            current_path = [text]
                        else:
                            buffer_lines.append(text)

        flush_buffer()
        doc.close()
        return chunks
