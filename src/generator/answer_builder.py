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
        target_states = []
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
                top_k=8,
                title_hint=sq.get("source_title") or None,
                full_source=bool(sq.get("full_source")),
            )
            searches = [copy.deepcopy(self.retriever.last_diagnostics)]
            target_states.append({
                "index": index,
                "sub_question": sq,
                "planned_filters": planned_filters,
                "strict_filters": strict_filters,
                "chunks": chunks,
                "searches": searches,
                "supplemented": False,
            })

        supplemental_searches = 0
        for state in target_states:
            sq = state["sub_question"]
            coverage_chunks, coverage_searches = self._coverage_context(
                state, target_states
            )
            coverage_status = self._coverage_status(
                coverage_chunks, sq, coverage_searches
            )
            supplemental_query = ""
            if coverage_status == "missing":
                if state["strict_filters"] != state["planned_filters"]:
                    supplemental_query = sq["question"]
                elif self._resolved_source_key(state):
                    supplemental_query = self._structural_supplement_query(sq)
            if supplemental_query:
                supplemental_searches += 1
                state["supplemented"] = True
                supplemental = self.retriever.retrieve(
                    query=supplemental_query,
                    query_type=sq.get("type"),
                    filters=state["planned_filters"] or None,
                    top_k=8,
                    title_hint=sq.get("source_title") or None,
                    full_source=bool(sq.get("full_source")),
                )
                state["searches"].append(
                    copy.deepcopy(self.retriever.last_diagnostics)
                )
                state["chunks"] = self._dedupe_chunks(
                    state["chunks"] + supplemental
                )

        chunk_groups = []
        target_diagnostics = []
        for state in target_states:
            sq = state["sub_question"]
            coverage_chunks, coverage_searches = self._coverage_context(
                state, target_states
            )
            coverage_status = self._coverage_status(
                coverage_chunks, sq, coverage_searches
            )
            chunks = self._prioritize_supporting_chunks(
                state["chunks"], coverage_chunks, sq, coverage_status
            )
            coverage_terms = sq.get("coverage_terms") or []
            index = state["index"]
            target_id = sq.get("target_id") or f"target_{index}"
            label = sq.get("label") or sq["question"]
            tagged_chunks = [self._tag_chunk(chunk, target_id, label, sq) for chunk in chunks]
            chunk_groups.append(tagged_chunks)
            target_diagnostics.append({
                "target_id": target_id,
                "label": label,
                "type": sq.get("type"),
                "source_title": sq.get("source_title", ""),
                "filters": state["planned_filters"],
                "strict_filters": state["strict_filters"],
                "coverage_terms": coverage_terms,
                "coverage_status": coverage_status,
                "covered": coverage_status == "supported",
                "supplemented": state["supplemented"],
                "result_count": len(chunks),
                "searches": state["searches"],
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

    def _chunks_cover_terms(self, chunks: list, terms: list,
                            aggregate_context: bool = False) -> bool:
        if not chunks:
            return False
        normalized_terms = [self._normalize_text(term) for term in terms if term]
        if not normalized_terms:
            return True
        search_texts = [self._chunk_search_text(chunk) for chunk in chunks]
        if aggregate_context:
            contexts = {}
            for index, chunk in enumerate(chunks):
                parent_id = chunk.get("parent_chunk_id")
                section_path = tuple(chunk.get("section_path", []))
                context_key = (
                    chunk.get("doc_id"),
                    ("parent", parent_id) if parent_id
                    else ("section", section_path) if section_path
                    else ("chunk", index),
                )
                contexts.setdefault(context_key, []).append(chunk)
            for context_chunks in contexts.values():
                ordered = sorted(
                    context_chunks,
                    key=lambda item: (
                        item.get("page_no") or 0,
                        item.get("row_index") or 0,
                        item.get("chunk_id") or "",
                    ),
                )
                search_texts.append(
                    "".join(
                        self._normalize_text(chunk.get("text", ""))
                        for chunk in ordered
                    )
                )
        return any(
            all(self._term_covered(term, search_text) for term in normalized_terms)
            for search_text in search_texts
        )

    def _term_covered(self, normalized_term: str, search_text: str) -> bool:
        if normalized_term in search_text:
            return True
        if len(normalized_term) < 12:
            return False
        numbers = re.findall(r"\d+(?:\.\d+)?", normalized_term)
        if any(number not in search_text for number in numbers):
            return False
        anchor_size = 4
        anchors = {
            normalized_term[index:index + anchor_size]
            for index in range(len(normalized_term) - anchor_size + 1)
        }
        if not anchors:
            return False
        matched = sum(anchor in search_text for anchor in anchors)
        if matched / len(anchors) >= 0.55:
            return True
        if not numbers:
            return False
        short_anchor_size = 2
        short_anchors = {
            normalized_term[index:index + short_anchor_size]
            for index in range(len(normalized_term) - short_anchor_size + 1)
        }
        short_matched = sum(anchor in search_text for anchor in short_anchors)
        return short_matched / len(short_anchors) >= 0.5

    def _chunk_search_text(self, chunk: dict) -> str:
        values = [
            chunk.get("text", ""),
            chunk.get("table_name", ""),
            chunk.get("indicator", ""),
            chunk.get("row_label", ""),
            chunk.get("column_header", ""),
            " ".join(chunk.get("section_path", [])),
        ]
        return self._normalize_text(" ".join(str(value) for value in values))

    def _coverage_status(self, chunks: list, sub_question: dict,
                         searches: list = None) -> str:
        chunks = self._source_scoped_chunks(chunks, sub_question, searches or [])
        if not chunks:
            return "missing"
        coverage_terms = sub_question.get("coverage_terms") or []
        aggregate_context = sub_question.get("type") in {"regulation", "hybrid"}
        if not coverage_terms or self._chunks_cover_terms(
            chunks, coverage_terms, aggregate_context=aggregate_context
        ):
            return "supported"
        if (
            sub_question.get("type") in {"regulation", "hybrid"}
            and any(self._search_is_exhaustive(search) for search in searches or [])
        ):
            return "not_supported"
        return "missing"

    def _coverage_context(self, state: dict, states: list) -> tuple[list, list]:
        source_key = self._resolved_source_key(state)
        if not source_key:
            return state["chunks"], state["searches"]
        matching_states = [
            candidate for candidate in states
            if self._resolved_source_key(candidate) == source_key
        ]
        chunks = self._dedupe_chunks([
            chunk
            for candidate in matching_states
            for chunk in candidate["chunks"]
        ])
        searches = [
            search
            for candidate in matching_states
            for search in candidate["searches"]
        ]
        return chunks, searches

    def _prioritize_supporting_chunks(self, chunks: list, coverage_chunks: list,
                                      sub_question: dict,
                                      coverage_status: str) -> list:
        coverage_terms = sub_question.get("coverage_terms") or []
        if coverage_status != "supported" or not coverage_terms:
            return chunks
        supporting = [
            chunk for chunk in coverage_chunks
            if self._chunks_cover_terms([chunk], coverage_terms)
        ]
        return self._dedupe_chunks(supporting + chunks)

    def _resolved_source_key(self, state: dict) -> tuple:
        titles = []
        for search in state["searches"]:
            titles.extend(search.get("matched_titles") or [])
            if not search.get("matched_titles"):
                source_filter = (search.get("filters") or {}).get("source_title")
                if isinstance(source_filter, (list, tuple, set)):
                    titles.extend(source_filter)
                elif source_filter:
                    titles.append(source_filter)
        normalized = sorted({self._normalize_text(title) for title in titles if title})
        return tuple(normalized)

    def _source_scoped_chunks(self, chunks: list, sub_question: dict,
                              searches: list) -> list:
        if not sub_question.get("source_title"):
            return chunks
        allowed_titles = {
            self._normalize_text(title)
            for search in searches
            for title in self._search_source_titles(search)
            if title
        }
        if not allowed_titles:
            return []
        return [
            chunk for chunk in chunks
            if self._normalize_text(chunk.get("source_title", "")) in allowed_titles
        ]

    def _search_source_titles(self, search: dict) -> list:
        matched_titles = search.get("matched_titles") or []
        if matched_titles:
            return list(matched_titles)
        source_filter = (search.get("filters") or {}).get("source_title")
        if isinstance(source_filter, (list, tuple, set)):
            return list(source_filter)
        return [source_filter] if source_filter else []

    def _search_is_exhaustive(self, search: dict) -> bool:
        if search.get("strategy") == "full_source":
            return True
        counts = search.get("candidate_counts") or {}
        merged = counts.get("merged")
        final = counts.get("final")
        return (
            bool(self._search_source_titles(search))
            and isinstance(merged, int)
            and isinstance(final, int)
            and merged <= final
        )

    def _structural_supplement_query(self, sub_question: dict) -> str:
        terms = sub_question.get("coverage_terms") or []
        if sub_question.get("type") not in {"regulation", "hybrid"}:
            return ""
        for term in terms:
            if "属于" not in term:
                continue
            subject, category = term.split("属于", 1)
            category = re.sub(r"类?行政许可事项", "", category)
            subject = subject.strip(" ，。；：")
            category = category.strip(" ，。；：")
            if subject and category:
                return f"{subject} {category} 申请材料目录"
        return ""

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
