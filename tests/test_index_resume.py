"""测试 build_index 断点续传逻辑（mock Embedder 和 QdrantClient）。"""
import json
import sys
from unittest.mock import MagicMock, patch

import pytest


def _make_jsonl(tmp_path, n=5):
    path = tmp_path / "chunks.jsonl"
    lines = []
    for i in range(n):
        lines.append(json.dumps({
            "doc_id": f"D-{i}",
            "chunk_id": f"D-{i}#body",
            "text": f"测试文本第{i}条内容用于索引。",
            "chunk_type": "clause",
        }, ensure_ascii=False))
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _mock_heavy_deps(monkeypatch):
    """Mock sentence_transformers and qdrant_client at import level."""
    mock_st = MagicMock()
    mock_qdrant = MagicMock()
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_st)
    # Ensure qdrant_client sub-modules are available
    if "qdrant_client" not in sys.modules:
        monkeypatch.setitem(sys.modules, "qdrant_client", mock_qdrant)
        monkeypatch.setitem(sys.modules, "qdrant_client.models", mock_qdrant.models)


def _get_qdrant_index_class():
    """Import QdrantIndex after mocking dependencies."""
    from src.indexer.qdrant_index import QdrantIndex
    return QdrantIndex


class TestIndexResume:
    def test_skip_when_all_indexed(self, tmp_path):
        QdrantIndex = _get_qdrant_index_class()
        jsonl_path = _make_jsonl(tmp_path, n=3)

        idx = QdrantIndex.__new__(QdrantIndex)
        idx.client = MagicMock()
        idx.embedder = MagicMock()

        collection_info = MagicMock()
        collection_info.points_count = 3
        idx.client.get_collection.return_value = collection_info

        idx.index_chunks(jsonl_path, "regulations")

        idx.embedder.embed_batch.assert_not_called()
        idx.client.upsert.assert_not_called()

    def test_resume_from_existing(self, tmp_path):
        QdrantIndex = _get_qdrant_index_class()
        jsonl_path = _make_jsonl(tmp_path, n=5)

        idx = QdrantIndex.__new__(QdrantIndex)
        idx.client = MagicMock()
        idx.embedder = MagicMock()
        idx.embedder.embed_batch.return_value = [[0.1] * 1024] * 5

        collection_info = MagicMock()
        collection_info.points_count = 2  # 已有2条
        idx.client.get_collection.return_value = collection_info

        idx.index_chunks(jsonl_path, "regulations", batch_size=2)

        # 从第3条开始，还有3条，batch_size=2 → 2次 upsert
        assert idx.client.upsert.call_count == 2

    def test_full_index_from_zero(self, tmp_path):
        QdrantIndex = _get_qdrant_index_class()
        jsonl_path = _make_jsonl(tmp_path, n=4)

        idx = QdrantIndex.__new__(QdrantIndex)
        idx.client = MagicMock()
        idx.embedder = MagicMock()
        idx.embedder.embed_batch.return_value = [[0.1] * 1024] * 4

        collection_info = MagicMock()
        collection_info.points_count = 0
        idx.client.get_collection.return_value = collection_info

        idx.index_chunks(jsonl_path, "tables", batch_size=50)

        assert idx.client.upsert.call_count == 1
        points = idx.client.upsert.call_args[1]["points"]
        assert len(points) == 4

    def test_skip_when_more_than_file(self, tmp_path):
        """Qdrant 已有比文件更多的点，应跳过。"""
        QdrantIndex = _get_qdrant_index_class()
        jsonl_path = _make_jsonl(tmp_path, n=3)

        idx = QdrantIndex.__new__(QdrantIndex)
        idx.client = MagicMock()
        idx.embedder = MagicMock()

        collection_info = MagicMock()
        collection_info.points_count = 10
        idx.client.get_collection.return_value = collection_info

        idx.index_chunks(jsonl_path, "regulations")

        idx.embedder.embed_batch.assert_not_called()
        idx.client.upsert.assert_not_called()
