import json
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


class CandidateCountingReranker:
    def __init__(self):
        self.candidate_count = 0

    def rerank(self, query, chunks, top_k=5):
        self.candidate_count = len(chunks)
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


def test_retrieve_limits_candidates_before_local_reranking():
    vector_chunks = [
        {
            "chunk_id": f"vector-{index}",
            "chunk_type": "clause",
            "source_title": "向量来源",
            "text": f"向量候选 {index}",
        }
        for index in range(20)
    ]
    keyword_chunks = [
        {
            "chunk_id": f"keyword-{index}",
            "chunk_type": "clause",
            "source_title": "关键词来源",
            "text": f"关键词候选 {index}",
        }
        for index in range(20)
    ]
    qdrant = MagicMock()
    qdrant.search.return_value = vector_chunks
    bm25 = MagicMock()
    bm25.search.return_value = keyword_chunks
    bm25.related_chunks.return_value = []
    reranker = CandidateCountingReranker()
    retriever = HybridRetriever(
        qdrant=qdrant,
        bm25=bm25,
        reranker=reranker,
    )

    retriever.retrieve("银行询证函回复时限", query_type="regulation", top_k=8)

    assert reranker.candidate_count <= 24


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


def test_retrieve_near_title_scopes_results_to_matching_documents():
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
    assert retriever.last_diagnostics["filters"] == {"source_title": target_title}


def test_retrieve_unique_title_alias_scopes_results_to_parent_document():
    title_hint = "中资商业银行行政许可事项申请材料目录及格式要求（2023年版）"
    parent_title = (
        "中国银保监会关于印发中资商业银行行政许可事项申请材料"
        "目录及格式要求的通知"
    )
    chunks = [
        {
            "chunk_id": "noise",
            "chunk_type": "clause",
            "source_title": "寿险合同负债评估折现率曲线",
            "text": "折现率曲线由基础利率曲线加综合溢价形成。",
        },
        {
            "chunk_id": "target",
            "chunk_type": "clause",
            "source_title": parent_title,
            "text": "中资商业银行法人机构开业核准属于机构设立类行政许可事项。",
        },
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )

    result = retriever.retrieve(
        "折现率曲线由基础利率曲线加综合溢价形成",
        query_type="regulation",
        title_hint=title_hint,
        top_k=3,
    )

    assert [chunk["chunk_id"] for chunk in result] == ["target"]
    assert retriever.last_diagnostics["title_match"] == "alias"
    assert retriever.last_diagnostics["matched_titles"] == [parent_title]
    assert retriever.last_diagnostics["filters"] == {"source_title": parent_title}


def test_resolve_source_title_ignores_trailing_file_type_label():
    title = (
        "财政部办公厅 金融监管总局办公厅关于印发"
        "《银行函证工作操作指引》的通知 银行函证工作操作指引"
    )
    index = _bm25_with_chunks([{
        "chunk_id": "guide",
        "chunk_type": "clause",
        "source_title": title,
        "text": "银行函证工作操作指引对具体事项予以明确和细化。",
    }])

    matched, match_type = index.resolve_source_titles("银行函证工作操作指引（PDF）")

    assert matched == [title]
    assert match_type == "alias"


def test_resolve_source_title_treats_property_insurance_as_property_alias():
    indexed_title = "2024年9月财产险公司经营情况表"
    index = _bm25_with_chunks([
        {
            "chunk_id": "property-insurance-2024-09",
            "chunk_type": "table_row",
            "source_title": indexed_title,
            "text": "保险金额为 125426586.62。",
        },
        {
            "chunk_id": "property-insurance-2025-03",
            "chunk_type": "table_row",
            "source_title": "2025年3月财产险公司经营情况表",
            "text": "保险金额为 45933310.37。",
        },
        {
            "chunk_id": "property-insurance-2025-09",
            "chunk_type": "table_row",
            "source_title": "2025年9月财产险公司经营情况表",
            "text": "保险金额为 138937806.41。",
        },
    ])

    matched, match_type = index.resolve_source_titles(
        "2024年9月财产保险公司经营情况表"
    )

    assert matched == [indexed_title]
    assert match_type == "alias"


def test_bm25_search_matches_a_value_inside_section_path(tmp_path):
    from src.indexer.bm25_index import BM25Index

    chunks_path = tmp_path / "chunks.jsonl"
    chunks_path.write_text(
        "\n".join([
            json.dumps({
                "doc_id": "D1",
                "chunk_id": "D1#top",
                "text": "总负债 一季度 3648440.27",
                "section_path": ["1. 银行业金融机构"],
            }, ensure_ascii=False),
                json.dumps({
                    "doc_id": "D1",
                    "chunk_id": "D1#other",
                    "text": "总负债 一季度 492233.38",
                    "section_path": ["5. 农村金融机构"],
                }, ensure_ascii=False),
                json.dumps({
                    "doc_id": "D2",
                    "chunk_id": "D2#1",
                    "text": "资本充足率 四季度",
                    "section_path": ["监管指标"],
                }, ensure_ascii=False),
                json.dumps({
                    "doc_id": "D3",
                    "chunk_id": "D3#1",
                    "text": "保费收入 本年累计",
                    "section_path": ["保险数据"],
                }, ensure_ascii=False),
                json.dumps({
                    "doc_id": "D4",
                    "chunk_id": "D4#1",
                    "text": "贷款余额 三季度",
                    "section_path": ["贷款数据"],
                }, ensure_ascii=False),
            ]) + "\n",
        encoding="utf-8",
    )
    index = BM25Index(index_path=str(tmp_path / "bm25.pkl"))
    index.build([str(chunks_path)])

    results = index.search(
        "总负债 一季度",
        filters={"section_path": "1. 银行业金融机构"},
    )

    assert [result["chunk_id"] for result in results] == ["D1#top"]


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
