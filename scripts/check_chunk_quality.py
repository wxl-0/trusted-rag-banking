import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parser.excel_parser import ExcelParser
from src.parser.pdf_parser import PdfParser
from src.parser.word_parser import WordParser


def load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def parser_for(item: dict):
    path = Path(item["local_path"])
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return ExcelParser(
            doc_id=item["doc_id"],
            source_title=item.get("title") or path.stem,
            issuer=item.get("issuer", ""),
            publish_date=item.get("publish_date", ""),
            source_url=item.get("source_url", ""),
            local_path=str(path),
        )
    if suffix in {".docx", ".doc"}:
        return WordParser(
            doc_id=item["doc_id"],
            source_title=item.get("title") or path.stem,
            issuer=item.get("issuer", ""),
            doc_no=item.get("doc_no", ""),
            publish_date=item.get("publish_date", ""),
            source_url=item.get("source_url", ""),
            local_path=str(path),
        )
    if suffix == ".pdf":
        return PdfParser(
            doc_id=item["doc_id"],
            source_title=item.get("title") or path.stem,
            issuer=item.get("issuer", ""),
            doc_no=item.get("doc_no", ""),
            publish_date=item.get("publish_date", ""),
            source_url=item.get("source_url", ""),
            local_path=str(path),
        )
    raise ValueError(f"Unsupported file type: {path}")


def summarize(item: dict, limit: int) -> dict:
    path = Path(item["local_path"])
    print(f"Parsing {item['doc_id']} {path.name} ...", flush=True)
    chunks = parser_for(item).parse()
    type_counts = Counter(chunk.chunk_type for chunk in chunks)
    samples = []
    for chunk in chunks[:limit]:
        samples.append({
            "chunk_id": chunk.chunk_id,
            "type": chunk.chunk_type,
            "cell_ref": chunk.cell_ref,
            "page_no": chunk.page_no,
            "section_path": chunk.section_path,
            "text": chunk.text[:180],
        })
    return {
        "doc_id": item["doc_id"],
        "file": path.name,
        "suffix": path.suffix.lower(),
        "chunk_count": len(chunks),
        "type_counts": dict(type_counts),
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Quickly inspect parser output quality.")
    parser.add_argument("--manifest", default="data/manifest.json")
    parser.add_argument("--limit-files", type=int, default=5)
    parser.add_argument("--sample-chunks", type=int, default=3)
    parser.add_argument("--suffix", choices=[".xlsx", ".xls", ".docx", ".doc", ".pdf"])
    args = parser.parse_args()

    items = load_manifest(Path(args.manifest))
    if args.suffix:
        items = [item for item in items if Path(item["local_path"]).suffix.lower() == args.suffix]
    if not items:
        print("No files matched the given filters.", flush=True)
        return
    for item in items[:args.limit_files]:
        try:
            print(json.dumps(summarize(item, args.sample_chunks), ensure_ascii=False, indent=2))
        except Exception as exc:
            path = Path(item["local_path"])
            print(f"FAILED {item['doc_id']} {path.name}: {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    main()
