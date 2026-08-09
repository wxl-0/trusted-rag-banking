import copy
import json
import re
import time
from src.generator.llm_client import LLMClient
from src.generator.prompt_builder import SYSTEM_PROMPT, build_user_prompt
from src.generator.decomposer import QueryDecomposer
from src.retriever.hybrid_retriever import HybridRetriever


class AnswerBuilder:
    def __init__(self, llm=None, retriever=None, decomposer=None):
        self.llm = llm or LLMClient()
        self.retriever = retriever or HybridRetriever()
        self.decomposer = decomposer or QueryDecomposer()

    def answer(self, question: str, filters: dict = None, history: list = None,
               system_prompt: str = None, include_diagnostics: bool = False) -> dict:
        start = time.perf_counter()

        decompose_start = time.perf_counter()
        sub_questions = self.decomposer.decompose(question)
        decompose_ms = int((time.perf_counter() - decompose_start) * 1000)

        retrieval_start = time.perf_counter()
        chunk_groups = []
        target_diagnostics = []
        supplemental_searches = 0
        initial_top_k = 8 if len(sub_questions) == 1 else 3
        for index, sq in enumerate(sub_questions, 1):
            planned_filters = dict(sq.get("filters") or {})
            strict_filters = dict(planned_filters)
            strict_filters.update(sq.get("strict_filters") or {})
            if filters:
                planned_filters.update(filters)
                strict_filters.update(filters)

            chunks = self.retriever.retrieve(
                query=sq["question"],
                query_type=sq.get("type"),
                filters=strict_filters or None,
                top_k=initial_top_k,
                title_hint=sq.get("source_title") or None,
            )
            searches = [copy.deepcopy(self.retriever.last_diagnostics)]
            coverage_terms = sq.get("coverage_terms") or []
            covered = self._chunks_cover_terms(chunks, coverage_terms)
            supplemented = False

            if not covered:
                supplemental_searches += 1
                supplemented = True
                supplemental = self.retriever.retrieve(
                    query=sq["question"],
                    query_type=sq.get("type"),
                    filters=planned_filters or None,
                    top_k=8,
                    title_hint=sq.get("source_title") or None,
                )
                searches.append(copy.deepcopy(self.retriever.last_diagnostics))
                chunks = self._dedupe_chunks(chunks + supplemental)
                covered = self._chunks_cover_terms(chunks, coverage_terms)

            target_id = sq.get("target_id") or f"target_{index}"
            label = sq.get("label") or sq["question"]
            tagged_chunks = [self._tag_chunk(chunk, target_id, label, sq) for chunk in chunks]
            chunk_groups.append(tagged_chunks)
            target_diagnostics.append({
                "target_id": target_id,
                "label": label,
                "type": sq.get("type"),
                "source_title": sq.get("source_title", ""),
                "filters": planned_filters,
                "strict_filters": strict_filters,
                "coverage_terms": coverage_terms,
                "covered": covered,
                "supplemented": supplemented,
                "result_count": len(chunks),
                "searches": searches,
            })
        retrieval_ms = int((time.perf_counter() - retrieval_start) * 1000)
        unique_chunks = self._round_robin_chunks(chunk_groups, limit=8)
        retrieval_diagnostics = {
            "targets": target_diagnostics,
            "supplemental_searches": supplemental_searches,
            "evidence_count": len(unique_chunks),
        }

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
                    result["latency_ms"], decompose_ms, retrieval_ms, 0, {},
                    retrieval_diagnostics,
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
                retrieval_diagnostics,
            )
            result["diagnostics"]["sub_questions"] = sub_questions
            result["diagnostics"]["routing"] = self._routing_diagnostics()
        return result

    def _build_diagnostics(self, total_ms: int, decompose_ms: int,
                           retrieval_ms: int, generation_ms: int,
                           generation_metrics: dict,
                           retrieval_diagnostics: dict = None) -> dict:
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
        diagnostics = {
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
        if retrieval_diagnostics is not None:
            diagnostics["retrieval"] = retrieval_diagnostics
        return diagnostics

    def _routing_diagnostics(self) -> dict:
        return {
            "method": self.decomposer.last_decision_method,
            "route": self.decomposer.last_route,
        }

    def _chunks_cover_terms(self, chunks: list, terms: list) -> bool:
        if not chunks:
            return False
        normalized_terms = [self._normalize_text(term) for term in terms if term]
        if not normalized_terms:
            return True
        for chunk in chunks:
            values = [
                chunk.get("text", ""),
                chunk.get("source_title", ""),
                chunk.get("table_name", ""),
                chunk.get("indicator", ""),
                chunk.get("row_label", ""),
                chunk.get("column_header", ""),
                " ".join(chunk.get("section_path", [])),
            ]
            normalized_chunk = self._normalize_text(" ".join(str(value) for value in values))
            if all(term in normalized_chunk for term in normalized_terms):
                return True
        return False

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value).lower())

    def _dedupe_chunks(self, chunks: list) -> list:
        seen = set()
        unique = []
        for index, chunk in enumerate(chunks):
            chunk_id = chunk.get("chunk_id") or f"anonymous_{index}"
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            unique.append(chunk)
        return unique

    def _tag_chunk(self, chunk: dict, target_id: str, label: str, sub_question: dict) -> dict:
        tagged = dict(chunk)
        tagged["_retrieval_targets"] = [{"id": target_id, "label": label}]
        if sub_question.get("option"):
            tagged["_retrieval_options"] = [sub_question["option"]]
        elif sub_question.get("options"):
            tagged["_retrieval_options"] = list(sub_question["options"])
        return tagged

    def _round_robin_chunks(self, groups: list, limit: int) -> list:
        selected = []
        selected_by_id = {}
        max_length = max((len(group) for group in groups), default=0)
        for position in range(max_length):
            for group in groups:
                if position >= len(group):
                    continue
                chunk = group[position]
                chunk_id = chunk.get("chunk_id") or f"anonymous_{id(chunk)}"
                if chunk_id in selected_by_id:
                    existing = selected_by_id[chunk_id]
                    for target in chunk.get("_retrieval_targets", []):
                        if target not in existing.get("_retrieval_targets", []):
                            existing.setdefault("_retrieval_targets", []).append(target)
                    for option in chunk.get("_retrieval_options", []):
                        if option not in existing.get("_retrieval_options", []):
                            existing.setdefault("_retrieval_options", []).append(option)
                    continue
                selected.append(chunk)
                selected_by_id[chunk_id] = chunk
                if len(selected) >= limit:
                    return selected
        return selected
