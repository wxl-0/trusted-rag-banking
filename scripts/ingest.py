#!/usr/bin/env python
"""
将 data/manifest.json 中记录的文件解析为 Chunk 并写入 data/chunks/。
用法：python scripts/ingest.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.parser.word_parser import WordParser
from src.parser.pdf_parser import PdfParser
from src.parser.excel_parser import ExcelParser
from src.parser.pdf_table_parser import PdfTableParser
from src.parser.chunk_processor import process_chunks

RAW_DIR = Path("data/raw")
CHUNKS_DIR = Path("data/chunks")
MANIFEST_PATH = Path("data/manifest.json")
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_local_path(local_path: str, repo_root: Path = None) -> Path:
    path = Path(local_path)
    if path.is_absolute():
        return path
    return (repo_root or REPO_ROOT) / path


def load_manifest() -> list:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return []


def save_chunks(chunks: list, output_path: Path, seen_texts: set):
    with open(output_path, "a", encoding="utf-8") as f:
        for chunk in chunks:
            text = chunk.text
            if text in seen_texts:
                continue
            seen_texts.add(text)
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


def compose_source_title(title: str, notice_title: str = "") -> str:
    title = str(title or "").strip()
    notice_title = str(notice_title or "").strip()
    if not notice_title:
        return title

    normalize = lambda value: "".join(char for char in value if char.isalnum()).lower()
    normalized_title = normalize(title)
    normalized_notice = normalize(notice_title)
    if normalized_title and normalized_title in normalized_notice:
        return notice_title
    if normalized_notice and normalized_notice in normalized_title:
        return title
    title_alias = normalized_title.replace("表", "")
    notice_alias = normalized_notice.replace("表", "")
    if title_alias and title_alias in notice_alias:
        return notice_title
    if notice_alias and notice_alias in title_alias:
        return title
    return f"{notice_title} {title}"


def parse_manifest_entry(entry: dict) -> tuple[str, list]:
    local_path = resolve_local_path(entry["local_path"])
    if not local_path.exists():
        raise FileNotFoundError(local_path)

    suffix = local_path.suffix.lower()
    profile = entry.get("parse_profile", "regulation")
    if profile == "skip":
        return "skip", []

    source_title = compose_source_title(
        entry["title"], entry.get("notice_title", "")
    )

    common = dict(
        doc_id=entry["doc_id"],
        source_title=source_title,
        issuer=entry.get("issuer", ""),
        source_url=entry.get("source_url", ""),
        local_path=str(local_path),
    )

    if profile == "pdf_table":
        parser = PdfTableParser(
            **common,
            publish_date=entry.get("publish_date", ""),
        )
        return "tables", parser.parse()
    if profile == "report":
        parser = PdfParser(
            **common,
            doc_no=entry.get("doc_no", ""),
            publish_date=entry.get("publish_date", ""),
        )
        return "regulations", process_chunks(parser.parse(), profile="report")
    if suffix in (".xlsx", ".xls"):
        parser = ExcelParser(
            **common,
            publish_date=entry.get("publish_date", ""),
        )
        return "tables", parser.parse()
    if suffix in (".docx", ".doc"):
        parser = WordParser(
            **common,
            doc_no=entry.get("doc_no", ""),
            publish_date=entry.get("publish_date", ""),
        )
        return "regulations", process_chunks(parser.parse(), profile="regulation")
    if suffix == ".pdf":
        parser = PdfParser(
            **common,
            doc_no=entry.get("doc_no", ""),
            publish_date=entry.get("publish_date", ""),
        )
        return "regulations", process_chunks(parser.parse(), profile="regulation")
    raise ValueError(f"Unsupported file type: {suffix}")


def main():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    clause_path = CHUNKS_DIR / "clause_chunks.jsonl"
    table_path = CHUNKS_DIR / "table_chunks.jsonl"
    clause_path.write_text("", encoding="utf-8")
    table_path.write_text("", encoding="utf-8")

    seen_texts: set = set()

    for entry in manifest:
        local_path = resolve_local_path(entry["local_path"])
        if not local_path.exists():
            print(f"[跳过] 文件不存在: {local_path}")
            continue

        suffix = local_path.suffix.lower()
        profile = entry.get("parse_profile", "regulation")

        if profile == "skip":
            print(f"[跳过] {local_path.name} (profile=skip)")
            continue

        print(f"[解析] {local_path.name} (profile={profile})")

        try:
            collection, chunks = parse_manifest_entry(entry)
        except ValueError:
            print(f"[跳过] 不支持的格式: {suffix}")
            continue
        output_path = table_path if collection == "tables" else clause_path
        save_chunks(chunks, output_path, seen_texts)

    print(f"\n完成。clause_chunks: {clause_path}, table_chunks: {table_path}")
    print(f"  去重跳过: {len(seen_texts)} 个唯一文本已记录")


if __name__ == "__main__":
    main()
