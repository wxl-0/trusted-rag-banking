import json
import time
from src.generator.llm_client import LLMClient
from src.generator.prompt_builder import SYSTEM_PROMPT, build_user_prompt
from src.generator.decomposer import QueryDecomposer
from src.retriever.hybrid_retriever import HybridRetriever


class AnswerBuilder:
    def __init__(self):
        self.llm = LLMClient()
        self.retriever = HybridRetriever()
        self.decomposer = QueryDecomposer()

    def answer(self, question: str, filters: dict = None, history: list = None) -> dict:
        start = time.time()

        sub_questions = self.decomposer.decompose(question)

        all_chunks = []
        for sq in sub_questions:
            chunks = self.retriever.retrieve(
                query=sq["question"],
                query_type=sq.get("type"),
                filters=filters,
                top_k=8,
            )
            all_chunks.extend(chunks)

        seen = set()
        unique_chunks = []
        for c in all_chunks:
            cid = c.get("chunk_id", "")
            if cid not in seen:
                seen.add(cid)
                unique_chunks.append(c)

        if not unique_chunks:
            return {
                "answer": "",
                "confidence": "low",
                "evidence": [],
                "refuse_reason": "知识库中未检索到与该问题相关的监管依据",
                "latency_ms": int((time.time() - start) * 1000),
            }

        user_msg = build_user_prompt(question, unique_chunks[:8])
        raw = self.llm.chat(SYSTEM_PROMPT, user_msg, history=history)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "answer": raw,
                "confidence": "low",
                "evidence": [],
                "refuse_reason": None,
            }

        result["latency_ms"] = int((time.time() - start) * 1000)
        return result
