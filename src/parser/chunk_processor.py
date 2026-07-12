"""
Chunk 后处理管道。
在 parser.parse() 和 save_chunks() 之间运行，对 clause 类型 chunk 做：
子条款切分 → 超长切分+overlap → 上下文增强 → 最小长度过滤。
table_row 类型 chunk 直接跳过。

通过 profile 参数控制不同文件类型的处理策略：
- regulation: 监管文件，做子条款切分，600字上限
- report: 年报/报告，不做子条款切分，800字上限，支持英文标点
"""
import re
from typing import List

from src.parser.base import Chunk

OVERLAP_CHARS = 80
MIN_CHUNK_CHARS = 10
NOISE_PREFIXES = ("本页无正文", "目录", "附件清单", "注：本表", "注:本表", "填表说明", "编制说明")

PROFILE_CONFIG = {
    "regulation": {
        "sub_clause_split": True,
        "max_chars": 600,
        "sentence_split_chars": "。；",
    },
    "report": {
        "sub_clause_split": False,
        "max_chars": 800,
        "sentence_split_chars": "。；.;",
    },
}

SUB_CLAUSE_PATTERNS = [
    re.compile(r'(?=（[一二三四五六七八九十百]+）)'),
    re.compile(r'(?=\([一二三四五六七八九十百]+\))'),
    re.compile(r'(?<=[\n。；])(?=\d+[\.、])'),
]


def process_chunks(chunks: List[Chunk], profile: str = "regulation") -> List[Chunk]:
    config = PROFILE_CONFIG.get(profile, PROFILE_CONFIG["regulation"])

    clause_chunks = [c for c in chunks if c.chunk_type == "clause"]
    table_chunks = [c for c in chunks if c.chunk_type == "table_row"]

    if config["sub_clause_split"]:
        clause_chunks = split_sub_clauses(clause_chunks)

    clause_chunks = split_by_max_length(
        clause_chunks, config["max_chars"], config["sentence_split_chars"]
    )
    clause_chunks = enrich_context(clause_chunks)
    clause_chunks = filter_min_length(clause_chunks)

    return clause_chunks + table_chunks


def split_sub_clauses(chunks: List[Chunk]) -> List[Chunk]:
    result: List[Chunk] = []
    for chunk in chunks:
        parts = _detect_sub_clause_boundaries(chunk.text)
        if len(parts) <= 1:
            result.append(chunk)
        else:
            parent_id = chunk.chunk_id
            for idx, part_text in enumerate(parts, start=1):
                text = part_text.strip()
                if not text:
                    continue
                child = Chunk(
                    doc_id=chunk.doc_id,
                    chunk_id=f"{parent_id}#K{idx}",
                    text=text,
                    chunk_type=chunk.chunk_type,
                    source_title=chunk.source_title,
                    issuer=chunk.issuer,
                    doc_no=chunk.doc_no,
                    publish_date=chunk.publish_date,
                    section_path=chunk.section_path,
                    source_url=chunk.source_url,
                    local_path=chunk.local_path,
                    page_no=chunk.page_no,
                    parent_chunk_id=parent_id,
                )
                result.append(child)
    return result


def enrich_context(chunks: List[Chunk]) -> List[Chunk]:
    for chunk in chunks:
        if not chunk.section_path:
            chunk.section_path = ["正文"]
        section = " > ".join(chunk.section_path)
        prefix_parts = [f"《{chunk.source_title}》"]
        if section:
            prefix_parts.append(section)
        prefix = "".join(prefix_parts) + "：\n"
        chunk.text = prefix + chunk.text
    return chunks


def split_by_max_length(chunks: List[Chunk], max_chars: int = 600, split_chars: str = "。；") -> List[Chunk]:
    result: List[Chunk] = []
    for chunk in chunks:
        if len(chunk.text) <= max_chars:
            result.append(chunk)
            continue

        segments = _split_at_sentence_boundaries(chunk.text, max_chars, OVERLAP_CHARS, split_chars)
        if len(segments) <= 1:
            result.append(chunk)
            continue

        effective_parent = chunk.parent_chunk_id or chunk.chunk_id

        for idx, seg_text in enumerate(segments, start=1):
            child = Chunk(
                doc_id=chunk.doc_id,
                chunk_id=f"{chunk.chunk_id}#S{idx}",
                text=seg_text,
                chunk_type=chunk.chunk_type,
                source_title=chunk.source_title,
                issuer=chunk.issuer,
                doc_no=chunk.doc_no,
                publish_date=chunk.publish_date,
                section_path=chunk.section_path,
                source_url=chunk.source_url,
                local_path=chunk.local_path,
                page_no=chunk.page_no,
                parent_chunk_id=effective_parent,
            )
            result.append(child)
    return result


def filter_min_length(chunks: List[Chunk]) -> List[Chunk]:
    return [c for c in chunks if len(c.text.strip()) >= MIN_CHUNK_CHARS
            and not c.text.lstrip().startswith(NOISE_PREFIXES)]


def _detect_sub_clause_boundaries(text: str) -> List[str]:
    for pattern in SUB_CLAUSE_PATTERNS:
        parts = pattern.split(text)
        parts = [p for p in parts if p.strip()]
        if len(parts) >= 2:
            return parts
    return [text]


def _split_at_sentence_boundaries(text: str, max_chars: int, overlap: int, split_chars: str = "。；") -> List[str]:
    pattern = f'(?<=[{re.escape(split_chars)}])'
    sentences = re.split(pattern, text)
    sentences = [s for s in sentences if s.strip()]

    if not sentences:
        return [text]

    segments: List[str] = []
    current_segment: List[str] = []
    current_len = 0

    for sentence in sentences:
        sent_len = len(sentence)
        if current_len + sent_len > max_chars and current_segment:
            segments.append("".join(current_segment))
            overlap_text = "".join(current_segment)[-overlap:] if overlap > 0 else ""
            current_segment = [overlap_text, sentence] if overlap_text else [sentence]
            current_len = len(overlap_text) + sent_len
        else:
            current_segment.append(sentence)
            current_len += sent_len

    if current_segment:
        segments.append("".join(current_segment))

    return segments if len(segments) > 1 else [text]
