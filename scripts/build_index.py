#!/usr/bin/env python
"""
将 data/chunks/ 中的 JSONL 文件写入 Qdrant 向量数据库并构建 BM25 索引。
用法：python scripts/build_index.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indexer.qdrant_index import QdrantIndex
from src.indexer.bm25_index import BM25Index

CHUNKS_DIR = Path("data/chunks")
CLAUSE_PATH = CHUNKS_DIR / "clause_chunks.jsonl"
TABLE_PATH = CHUNKS_DIR / "table_chunks.jsonl"


def main():
    if not CLAUSE_PATH.exists() and not TABLE_PATH.exists():
        print("错误：data/chunks/ 下无 JSONL 文件，请先运行 python scripts/ingest.py")
        sys.exit(1)

    idx = QdrantIndex()
    idx.create_collections()

    if CLAUSE_PATH.exists():
        idx.index_chunks(str(CLAUSE_PATH), "regulations")
    if TABLE_PATH.exists():
        idx.index_chunks(str(TABLE_PATH), "tables")

    jsonl_files = [str(p) for p in [CLAUSE_PATH, TABLE_PATH] if p.exists()]
    bm25 = BM25Index()
    bm25.build(jsonl_files)

    print("\n完成。向量索引 + BM25 索引已构建。")


if __name__ == "__main__":
    main()
