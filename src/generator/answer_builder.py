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

    def answer(self, question: str, filters: dict = None, history: list = None,
               system_prompt: str = None, include_diagnostics: bool = False) -> dict:
        start = time.perf_counter()

        decompose_start = time.perf_counter()
        sub_questions = self.decomposer.decompose(question)
        decompose_ms = int((time.perf_counter() - decompose_start) * 1000)

        retrieval_start = time.perf_counter()
        all_chunks = []
        for sq in sub_questions:
            chunks = self.retriever.retrieve(
                query=sq["question"],
                query_type=sq.get("type"),
                filters=filters,
                top_k=8,
            )
            all_chunks.extend(chunks)
        retrieval_ms = int((time.perf_counter() - retrieval_start) * 1000)

        seen = set()
        unique_chunks = []
        for c in all_chunks:
            cid = c.get("chunk_id", "")
            if cid not in seen:
                seen.add(cid)
                unique_chunks.append(c)

        if not unique_chunks:
            result = {
                "answer": "",
                "confidence": "low",
                "evidence": [],
                "refuse_reason": "知识库中未检索到与该问题相关的监管依据",
                "latency_ms": int((time.perf_counter() - start) * 1000),
            }
            if include_diagnostics:
                result["diagnostics"] = self._build_diagnostics(
                    result["latency_ms"], decompose_ms, retrieval_ms, 0, {}
                )
                result["diagnostics"]["sub_questions"] = sub_questions
                result["diagnostics"]["routing"] = self._routing_diagnostics()
            return result

        user_msg = build_user_prompt(question, unique_chunks[:8])
        generation_start = time.perf_counter()
        raw = self.llm.chat(system_prompt or SYSTEM_PROMPT, user_msg, history=history)
        generation_ms = int((time.perf_counter() - generation_start) * 1000)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "answer": raw,
                "confidence": "low",
                "evidence": [],
                "refuse_reason": None,
            }

        result["latency_ms"] = int((time.perf_counter() - start) * 1000)
        if include_diagnostics:
            result["diagnostics"] = self._build_diagnostics(
                result["latency_ms"],
                decompose_ms,
                retrieval_ms,
                generation_ms,
                dict(self.llm.last_call_metrics),
            )
            result["diagnostics"]["sub_questions"] = sub_questions
            result["diagnostics"]["routing"] = self._routing_diagnostics()
        return result

    def _build_diagnostics(self, total_ms: int, decompose_ms: int,
                           retrieval_ms: int, generation_ms: int,
                           generation_metrics: dict) -> dict:
        decomposition_metrics = (
            dict(self.decomposer.llm.last_call_metrics)
            if self.decomposer.last_decision_method == "model"
            else {}
        )
        llm_calls = (
            decomposition_metrics.get("api_calls", 0)
            + generation_metrics.get("api_calls", 0)
        )
        token_values = [
            metrics.get("total_tokens")
            for metrics in (decomposition_metrics, generation_metrics)
            if metrics.get("total_tokens") is not None
        ]
        cost_values = [
            metrics.get("provider_reported_cost")
            for metrics in (decomposition_metrics, generation_metrics)
            if metrics.get("provider_reported_cost") is not None
        ]
        return {
            "timing_ms": {
                "decomposition": decompose_ms,
                "retrieval": retrieval_ms,
                "generation": generation_ms,
                "total": total_ms,
            },
            "llm": {
                "decomposition": decomposition_metrics,
                "generation": generation_metrics,
                "total_api_calls": llm_calls,
                "total_tokens": sum(token_values) if token_values else None,
                "provider_reported_cost": sum(cost_values) if cost_values else None,
            },
        }

    def _routing_diagnostics(self) -> dict:
        return {
            "method": self.decomposer.last_decision_method,
            "route": self.decomposer.last_route,
        }
