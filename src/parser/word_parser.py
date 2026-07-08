from docx import Document
from typing import List
from src.parser.base import Chunk


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
        doc = Document(self.local_path)
        chunks = []
        current_path = []
        buffer_text = []
        buffer_path = []

        def flush_buffer():
            if buffer_text:
                text = " ".join(buffer_text).strip()
                if text:
                    chunk_id = f"{self.doc_id}#{'#'.join(buffer_path) if buffer_path else 'body'}"
                    chunks.append(Chunk(
                        doc_id=self.doc_id,
                        chunk_id=chunk_id,
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

        for para in doc.paragraphs:
            style_name = para.style.name
            text = para.text.strip()
            if not text:
                continue
            if style_name.startswith("Heading"):
                flush_buffer()
                try:
                    level = int(style_name.split()[-1])
                except ValueError:
                    level = 1
                current_path = current_path[:level - 1] + [text]
                buffer_path.clear()
                buffer_path.extend(current_path)
            else:
                buffer_text.append(text)

        flush_buffer()
        return chunks
from src.parser.word_enhanced_parser import WordEnhancedParser as WordParser
