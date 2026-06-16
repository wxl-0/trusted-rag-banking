from unittest.mock import MagicMock
from src.retriever.hybrid_retriever import HybridRetriever


def test_rrf_merge_combines_results():
    retriever = HybridRetriever.__new__(HybridRetriever)
    list_a = [
        {"chunk_id": "A", "text": "制度文本A"},
        {"chunk_id": "B", "text": "制度文本B"},
    ]
    list_b = [
        {"chunk_id": "B", "text": "制度文本B"},
        {"chunk_id": "C", "text": "表格数据C"},
    ]
    merged = retriever._rrf_merge(list_a, list_b)
    ids = [m["chunk_id"] for m in merged]
    assert "B" in ids
    assert ids.index("B") == 0  # B 在两个列表都有，RRF 分数最高


def test_retrieve_out_of_scope_returns_empty():
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.router = MagicMock()
    retriever.router.route.return_value = "out_of_scope"
    result = retriever.retrieve("今天天气怎么样")
    assert result == []
