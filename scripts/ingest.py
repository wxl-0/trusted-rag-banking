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


def save_chunks(chunks: list, output_path: Path):
    with open(output_path, "a", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


def main():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    clause_path = CHUNKS_DIR / "clause_chunks.jsonl"
    table_path = CHUNKS_DIR / "table_chunks.jsonl"
    clause_path.write_text("", encoding="utf-8")
    table_path.write_text("", encoding="utf-8")

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

        common = dict(
            doc_id=entry["doc_id"],
            source_title=entry["title"],
            issuer=entry.get("issuer", ""),
            source_url=entry.get("source_url", ""),
            local_path=str(local_path),
        )

        if profile == "pdf_table":
            parser = PdfTableParser(
                **common,
                publish_date=entry.get("publish_date", ""),
            )
            save_chunks(parser.parse(), table_path)
        elif profile == "report":
            parser = PdfParser(
                **common,
                doc_no=entry.get("doc_no", ""),
                publish_date=entry.get("publish_date", ""),
            )
            save_chunks(process_chunks(parser.parse(), profile="report"), clause_path)
        elif suffix in (".xlsx", ".xls"):
            parser = ExcelParser(
                **common,
                publish_date=entry.get("publish_date", ""),
            )
            save_chunks(parser.parse(), table_path)
        elif suffix in (".docx", ".doc"):
            parser = WordParser(
                **common,
                doc_no=entry.get("doc_no", ""),
                publish_date=entry.get("publish_date", ""),
            )
            save_chunks(process_chunks(parser.parse(), profile="regulation"), clause_path)
        elif suffix == ".pdf":
            parser = PdfParser(
                **common,
                doc_no=entry.get("doc_no", ""),
                publish_date=entry.get("publish_date", ""),
            )
            save_chunks(process_chunks(parser.parse(), profile="regulation"), clause_path)
        else:
            print(f"[跳过] 不支持的格式: {suffix}")

    print(f"\n完成。clause_chunks: {clause_path}, table_chunks: {table_path}")


if __name__ == "__main__":
    main()
