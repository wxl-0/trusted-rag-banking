from unittest.mock import MagicMock
from rank_bm25 import BM25Okapi

from src.indexer.bm25_index import BM25Index
from src.retriever.hybrid_retriever import HybridRetriever


class FakeQdrant:
    def __init__(self, chunks):
        self.chunks = chunks

    def search(self, query, collection_name, filters=None, top_k=20):
        chunks = self.chunks
        if filters:
            chunks = [chunk for chunk in chunks if _matches_filters(chunk, filters)]
        return chunks[:top_k]


class FakeReranker:
    def rerank(self, query, chunks, top_k=5):
        return chunks[:top_k]


def _matches_filters(chunk, filters):
    for key, expected in filters.items():
        actual = chunk.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


def _bm25_with_chunks(chunks):
    index = BM25Index()
    index.chunks = chunks
    index.bm25 = BM25Okapi([index._tokenize(chunk["text"]) for chunk in chunks])
    return index


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


def test_retrieve_exact_title_scopes_vector_and_keyword_results():
    target_title = "应当编报保险集团偿付能力报告的公司名单"
    chunks = [
        {
            "chunk_id": "target",
            "chunk_type": "clause",
            "source_title": target_title,
            "text": "列入名单的保险集团应当编报保险集团偿付能力报告。",
        },
        {
            "chunk_id": "noise",
            "chunk_type": "clause",
            "source_title": "寿险合同负债评估折现率曲线",
            "text": "寿险合同负债评估采用折现率曲线。",
        },
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )

    result = retriever.retrieve(
        "哪一项与材料内容一致",
        query_type="regulation",
        title_hint=target_title,
        top_k=5,
    )

    assert [chunk["chunk_id"] for chunk in result] == ["target"]
    assert retriever.last_diagnostics["title_match"] == "exact"


def test_retrieve_near_title_boosts_match_without_hiding_other_documents():
    title_hint = "应当编报保险集团偿付能力报告的公司名单"
    target_title = f"关于公布《{title_hint}》的通知"
    chunks = [
        {
            "chunk_id": f"noise-{index}",
            "chunk_type": "clause",
            "source_title": "寿险合同负债评估折现率曲线",
            "text": "寿险合同负债评估采用折现率曲线。",
        }
        for index in range(21)
    ] + [
        {
            "chunk_id": "target",
            "chunk_type": "clause",
            "source_title": target_title,
            "text": "列入名单的保险集团应当编报报告。",
        },
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )

    result = retriever.retrieve(
        "折现率",
        query_type="regulation",
        title_hint=title_hint,
        top_k=1,
    )

    assert [chunk["chunk_id"] for chunk in result] == ["target"]
    assert retriever.last_diagnostics["title_match"] == "near"
    assert retriever.last_diagnostics["filters"] == {}


def test_retrieve_regulation_includes_neighbor_from_same_section():
    title = "意外伤害保险业务监管办法"
    hit = {
        "doc_id": "doc-1",
        "chunk_id": "hit",
        "chunk_type": "clause",
        "source_title": title,
        "section_path": ["保险费率"],
        "parent_chunk_id": "parent-1",
        "text": "保险公司在厘定保险费时应符合一般精算原理。",
    }
    sibling = {
        "doc_id": "doc-1",
        "chunk_id": "sibling",
        "chunk_type": "clause",
        "source_title": title,
        "section_path": ["保险费率"],
        "parent_chunk_id": "parent-1",
        "text": "采用公平、合理的定价假设。",
    }
    other = {
        "doc_id": "doc-1",
        "chunk_id": "other",
        "chunk_type": "clause",
        "source_title": title,
        "section_path": ["信息披露"],
        "text": "保险公司应当披露相关信息。",
    }
    retriever = HybridRetriever(
        qdrant=FakeQdrant([hit]),
        bm25=_bm25_with_chunks([hit, sibling, other]),
        reranker=FakeReranker(),
    )

    result = retriever.retrieve(
        "精算",
        query_type="regulation",
        title_hint=title,
        top_k=2,
    )

    assert [chunk["chunk_id"] for chunk in result] == ["hit", "sibling"]
    assert retriever.last_diagnostics["candidate_counts"]["context_added"] == 1


def test_retrieve_returns_every_chunk_when_explicit_source_is_short():
    title_hint = "应当编报保险集团偿付能力报告的公司名单"
    source_title = f"有关事项的通知 附件8：{title_hint}"
    target_chunks = [
        {
            "doc_id": "NFRA-467",
            "chunk_id": f"NFRA-467#{index}",
            "chunk_type": "clause",
            "source_title": source_title,
            "page_no": index,
            "text": f"名单内容 {index}",
        }
        for index in range(1, 8)
    ]
    noise = {
        "doc_id": "other",
        "chunk_id": "noise",
        "chunk_type": "clause",
        "source_title": "寿险合同负债评估折现率曲线",
        "text": "折现率曲线内容",
    }
    chunks = [noise, *target_chunks]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )

    result = retriever.retrieve(
        "以下哪项与名单内容一致",
        query_type="regulation",
        title_hint=title_hint,
        top_k=3,
        full_source=True,
    )

    assert [chunk["chunk_id"] for chunk in result] == [
        f"NFRA-467#{index}" for index in range(1, 8)
    ]
    assert retriever.last_diagnostics["strategy"] == "full_source"
