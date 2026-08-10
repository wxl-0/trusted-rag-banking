import json

from rank_bm25 import BM25Okapi

from src.generator.answer_builder import AnswerBuilder
from src.generator.decomposer import QueryDecomposer
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


class OrderedReranker:
    def rerank(self, query, chunks, top_k=5):
        return sorted(chunks, key=lambda chunk: chunk["rank"])[:top_k]


class TargetAwareReranker:
    def rerank(self, query, chunks, top_k=5):
        rank_key = "rank_a" if "目标甲" in query else "rank_b"
        return sorted(chunks, key=lambda chunk: chunk[rank_key])[:top_k]


class StructuralReranker:
    def __init__(self):
        self.queries = []

    def rerank(self, query, chunks, top_k=5):
        self.queries.append(query)
        rank_key = "structural_rank" if "申请材料目录" in query else "initial_rank"
        return sorted(chunks, key=lambda chunk: chunk[rank_key])[:top_k]


class StaticDecomposer:
    def __init__(self, targets):
        self.targets = targets
        self.last_decision_method = "rule"
        self.last_route = "regulation"

    def decompose(self, question):
        return self.targets


class FakeLLM:
    def __init__(self):
        self.last_call_metrics = {
            "api_calls": 1,
            "total_tokens": 10,
            "provider_reported_cost": 0,
        }
        self.last_user_message = ""

    def chat(self, system, user, history=None):
        self.last_user_message = user
        return json.dumps({
            "answer": "健康险减合计为 -42212.17。",
            "confidence": "high",
            "evidence": [],
            "refuse_reason": None,
        }, ensure_ascii=False)


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


def test_answer_supplements_only_missing_table_target_once():
    title = "2023年12月全国各地区原保险保费收入情况表"
    chunks = [
        {
            "doc_id": "table-1",
            "chunk_id": "total",
            "chunk_type": "table_row",
            "source_title": title,
            "row_label": "全国合计",
            "column_header": "合计",
            "raw_value": "51246.71",
            "text": "全国合计，合计为 51246.71。",
        },
        {
            "doc_id": "table-1",
            "chunk_id": "health",
            "chunk_type": "table_row",
            "source_title": title,
            "row_label": "全国合计",
            "column_header": "健康险（原保险）",
            "raw_value": "9034.54",
            "text": "全国合计，健康险为 9034.54。",
        },
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )
    llm = FakeLLM()
    builder = AnswerBuilder(
        llm=llm,
        retriever=retriever,
        decomposer=QueryDecomposer(),
    )
    question = (
        f"根据《{title}》，"
        "“全国合计”从“合计”到“健康险”的数值变化约为多少？"
    )

    result = builder.answer(question, include_diagnostics=True)

    retrieval = result["diagnostics"]["retrieval"]
    assert retrieval["supplemental_searches"] == 1
    assert [target["covered"] for target in retrieval["targets"]] == [True, True]
    assert [target["supplemented"] for target in retrieval["targets"]] == [False, True]
    assert "51246.71" in llm.last_user_message
    assert "9034.54" in llm.last_user_message
    assert "检索目标：全国合计 / 合计" in llm.last_user_message
    assert "检索目标：全国合计 / 健康险" in llm.last_user_message


def test_answer_does_not_supplement_unsupported_regulation_claims():
    title = "意外伤害保险业务监管办法"
    source_title = f"中国银保监会办公厅关于印发《{title}》的通知"
    shared = (
        "意外伤害保险是以被保险人因遭受意外伤害造成死亡、伤残或者"
        "发生保险合同约定的其他事故为给付保险金条件的人身保险。"
    )
    pricing = "保险公司厘定保险费应采用公平、合理的定价假设。"
    chunks = [
        {
            "doc_id": "reg-1",
            "chunk_id": "definition-1",
            "chunk_type": "clause",
            "source_title": source_title,
            "section_path": ["总则"],
            "parent_chunk_id": "definition",
            "text": "第二条 本办法所称意外伤害保险（以下简称意外险）",
        },
        {
            "doc_id": "reg-1",
            "chunk_id": "definition-2",
            "chunk_type": "clause",
            "source_title": source_title,
            "section_path": ["总则"],
            "parent_chunk_id": "definition",
            "text": (
                "是以被保险人因遭受意外伤害造成死亡、伤残或者发生保险 "
                "合同约定的其他事故为给付保险金条件的人身保险。"
            ),
        },
        {
            "doc_id": "reg-1",
            "chunk_id": "pricing",
            "chunk_type": "clause",
            "source_title": source_title,
            "section_path": ["产品管理"],
            "text": pricing,
        },
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )
    llm = FakeLLM()
    builder = AnswerBuilder(
        llm=llm,
        retriever=retriever,
        decomposer=QueryDecomposer(),
    )
    question = (
        f"关于《{title}》，下列哪一组选项中的两项表述均属于该材料内容？\n"
        f"A. {shared}；基础利率曲线由三段组成。\n"
        f"B. {shared}；移动平均曲线适用于0年到20年。\n"
        f"C. {shared}；{pricing}\n"
        f"D. {shared}；折现率曲线由基础利率曲线加综合溢价形成。"
    )

    result = builder.answer(question, include_diagnostics=True)

    retrieval = result["diagnostics"]["retrieval"]
    assert retrieval["supplemental_searches"] == 0
    assert [target["coverage_status"] for target in retrieval["targets"]] == [
        "supported",
        "not_supported",
        "not_supported",
        "supported",
        "not_supported",
    ]


def test_answer_multi_fact_uses_relevant_evidence_ranked_after_third():
    title = "测试监管办法"
    shared = "监管机构应当依法审查申请材料。"
    correct = "法人机构开业核准属于机构设立类行政许可事项。"
    chunks = [
        {
            "doc_id": "reg-long",
            "chunk_id": "shared",
            "chunk_type": "clause",
            "source_title": title,
            "rank": 1,
            "text": shared,
        },
        *[
            {
                "doc_id": "reg-long",
                "chunk_id": f"filler-{rank}",
                "chunk_type": "clause",
                "source_title": title,
                "rank": rank,
                "text": f"第{rank}条无关的程序性规定。",
            }
            for rank in (2, 3)
        ],
        {
            "doc_id": "reg-long",
            "chunk_id": "correct",
            "chunk_type": "clause",
            "source_title": title,
            "rank": 4,
            "text": correct,
        },
        *[
            {
                "doc_id": "reg-long",
                "chunk_id": f"filler-{rank}",
                "chunk_type": "clause",
                "source_title": title,
                "rank": rank,
                "text": f"第{rank}条其他程序性规定。",
            }
            for rank in range(5, 10)
        ],
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=OrderedReranker(),
    )
    builder = AnswerBuilder(
        llm=FakeLLM(),
        retriever=retriever,
        decomposer=QueryDecomposer(),
    )
    question = (
        f"关于《{title}》，下列哪一组选项中的两项表述均属于该材料内容？\n"
        f"A. {shared}；{correct}\n"
        f"B. {shared}；寿险合同负债采用折现率曲线。\n"
        f"C. {shared}；基础利率曲线由三段组成。\n"
        f"D. {shared}；移动平均曲线适用于0年到20年。"
    )

    result = builder.answer(question, include_diagnostics=True)

    retrieval = result["diagnostics"]["retrieval"]
    assert retrieval["targets"][1]["coverage_status"] == "supported"
    assert retrieval["supplemental_searches"] == 0


def test_answer_pools_initial_evidence_from_targets_with_same_resolved_source():
    title = "测试监管办法"
    claim_a = "目标甲应当按照规定办理开业核准。"
    claim_b = "目标乙应当提交完整申请材料。"
    chunks = [
        {
            "doc_id": "reg-shared",
            "chunk_id": "claim-a",
            "chunk_type": "clause",
            "source_title": title,
            "rank_a": 9,
            "rank_b": 1,
            "text": claim_a,
        },
        {
            "doc_id": "reg-shared",
            "chunk_id": "claim-b",
            "chunk_type": "clause",
            "source_title": title,
            "rank_a": 1,
            "rank_b": 2,
            "text": claim_b,
        },
        *[
            {
                "doc_id": "reg-shared",
                "chunk_id": f"filler-{rank}",
                "chunk_type": "clause",
                "source_title": title,
                "rank_a": rank,
                "rank_b": rank + 1,
                "text": f"第{rank}条其他程序性规定。",
            }
            for rank in range(2, 10)
        ],
    ]
    targets = [
        {
            "target_id": "claim_a",
            "label": claim_a,
            "question": f"《{title}》目标甲：{claim_a}",
            "type": "regulation",
            "source_title": title,
            "filters": {},
            "strict_filters": {},
            "coverage_terms": [claim_a],
        },
        {
            "target_id": "claim_b",
            "label": claim_b,
            "question": f"《{title}》目标乙：{claim_b}",
            "type": "regulation",
            "source_title": title,
            "filters": {},
            "strict_filters": {},
            "coverage_terms": [claim_b],
        },
    ]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=TargetAwareReranker(),
    )
    builder = AnswerBuilder(
        llm=FakeLLM(),
        retriever=retriever,
        decomposer=StaticDecomposer(targets),
    )

    result = builder.answer("测试同源证据复用", include_diagnostics=True)

    retrieval = result["diagnostics"]["retrieval"]
    assert [target["coverage_status"] for target in retrieval["targets"]] == [
        "supported",
        "supported",
    ]
    assert retrieval["supplemental_searches"] == 0


def test_answer_does_not_accept_claim_from_unresolved_unrelated_source():
    claim = "法人机构开业核准属于机构设立类行政许可事项。"
    chunks = [
        {
            "doc_id": "other-source",
            "chunk_id": "other-claim",
            "chunk_type": "clause",
            "source_title": "寿险合同负债评估折现率曲线",
            "text": claim,
        },
    ]
    targets = [{
        "target_id": "claim",
        "label": claim,
        "question": claim,
        "type": "regulation",
        "source_title": "完全不存在的监管材料",
        "filters": {},
        "strict_filters": {},
        "coverage_terms": [claim],
    }]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )
    builder = AnswerBuilder(
        llm=FakeLLM(),
        retriever=retriever,
        decomposer=StaticDecomposer(targets),
    )

    result = builder.answer("测试来源约束", include_diagnostics=True)

    retrieval = result["diagnostics"]["retrieval"]
    assert retrieval["targets"][0]["coverage_status"] == "missing"
    assert retrieval["supplemental_searches"] == 0


def test_answer_accepts_reordered_numeric_fact_anchors_from_same_source():
    title = "意外伤害保险业务监管办法"
    claim = "保险期限一年及以下的个人意外险平均附加费用率上限为35%。"
    chunks = [{
        "doc_id": "reg-fee",
        "chunk_id": "fee-cap",
        "chunk_type": "clause",
        "source_title": title,
        "text": "业务类 保险期限一年及以下的意外险 个人 35%",
    }]
    targets = [{
        "target_id": "fee_cap",
        "label": claim,
        "question": claim,
        "type": "regulation",
        "source_title": title,
        "filters": {},
        "strict_filters": {},
        "coverage_terms": [claim],
    }]
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=FakeReranker(),
    )
    builder = AnswerBuilder(
        llm=FakeLLM(),
        retriever=retriever,
        decomposer=StaticDecomposer(targets),
    )

    result = builder.answer("测试数值事实锚点", include_diagnostics=True)

    target = result["diagnostics"]["retrieval"]["targets"][0]
    assert target["coverage_status"] == "supported"
    assert target["supplemented"] is False


def test_answer_uses_distinct_structural_query_for_partial_classification_fact():
    title = "测试监管办法"
    claim = "法人机构开业核准属于机构设立类行政许可事项。"
    evidence_text = f"关键目录证据：{claim}"
    chunks = [
        {
            "doc_id": "reg-structure",
            "chunk_id": "correct-structure",
            "chunk_type": "clause",
            "source_title": title,
            "initial_rank": 9,
            "structural_rank": 1,
            "text": evidence_text,
        },
        *[
            {
                "doc_id": "reg-structure",
                "chunk_id": f"filler-{rank}",
                "chunk_type": "clause",
                "source_title": title,
                "initial_rank": rank,
                "structural_rank": rank + 1,
                "text": (
                    "法人机构设立申请应当提交完整材料。"
                    if rank == 1 else f"第{rank}条其他程序性规定。"
                ),
            }
            for rank in range(1, 10)
        ],
    ]
    targets = [{
        "target_id": "classification",
        "label": claim,
        "question": claim,
        "type": "regulation",
        "source_title": title,
        "filters": {},
        "strict_filters": {},
        "coverage_terms": [claim],
    }]
    reranker = StructuralReranker()
    retriever = HybridRetriever(
        qdrant=FakeQdrant(chunks),
        bm25=_bm25_with_chunks(chunks),
        reranker=reranker,
    )
    llm = FakeLLM()
    builder = AnswerBuilder(
        llm=llm,
        retriever=retriever,
        decomposer=StaticDecomposer(targets),
    )

    result = builder.answer("测试结构分类补搜", include_diagnostics=True)

    retrieval = result["diagnostics"]["retrieval"]
    assert retrieval["targets"][0]["coverage_status"] == "supported"
    assert retrieval["targets"][0]["supplemented"] is True
    assert retrieval["supplemental_searches"] == 1
    assert len(reranker.queries) == 2
    assert "申请材料目录" not in reranker.queries[0]
    assert "申请材料目录" in reranker.queries[1]
    assert evidence_text in llm.last_user_message
