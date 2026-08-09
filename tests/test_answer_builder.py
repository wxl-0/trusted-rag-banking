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
