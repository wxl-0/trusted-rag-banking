import copy
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from src.context_control import ContextAssembler
from src.generator.llm_client import LLMClient
from src.generator.prompt_builder import SYSTEM_PROMPT, build_user_prompt
from src.generator.decomposer import QueryDecomposer
from src.retriever.hybrid_retriever import HybridRetriever


class AnswerBuilder:
    def __init__(self, llm=None, retriever=None, decomposer=None, context_assembler=None):
        self.llm = llm or LLMClient()
        self.retriever = retriever or HybridRetriever()
        self.decomposer = decomposer or QueryDecomposer()
        self.context_assembler = context_assembler or ContextAssembler()

    def answer(self, question: str, filters: dict = None, history: list = None,
               system_prompt: str = None, include_diagnostics: bool = False,
               progress_callback=None) -> dict:
        start = time.perf_counter()

        def report(stage: str):
            if progress_callback:
                progress_callback(stage)

        report("analyzing")
        decompose_start = time.perf_counter()
        sub_questions = self.decomposer.decompose(question, history=history)
        decompose_ms = int((time.perf_counter() - decompose_start) * 1000)

        report("retrieving")
        retrieval_start = time.perf_counter()
        target_plans = []
        for index, sq in enumerate(sub_questions, 1):
            planned_filters = dict(sq.get("filters") or {})
            strict_filters = dict(planned_filters)
            strict_filters.update(sq.get("strict_filters") or {})
            if filters:
                planned_filters.update(filters)
                strict_filters.update(filters)
            target_plans.append((index, sq, planned_filters, strict_filters))

        def retrieve_initial(plan):
            index, sq, planned_filters, strict_filters = plan
            chunks, diagnostics = self._retrieve(
                query=sq["question"],
                query_type=sq.get("type"),
                filters=strict_filters or None,
                top_k=8,
                title_hint=sq.get("source_title") or None,
                full_source=bool(sq.get("full_source")),
            )
            return {
                "index": index,
                "sub_question": sq,
                "planned_filters": planned_filters,
                "strict_filters": strict_filters,
                "chunks": chunks,
                "searches": [diagnostics],
                "supplemented": False,
            }

        max_workers = max(1, int(os.getenv("RETRIEVAL_MAX_WORKERS", "2")))
        if len(target_plans) > 1 and max_workers > 1:
            with ThreadPoolExecutor(
                max_workers=min(max_workers, len(target_plans)),
                thread_name_prefix="rag-retrieval",
            ) as executor:
                target_states = list(executor.map(retrieve_initial, target_plans))
        else:
            target_states = [retrieve_initial(plan) for plan in target_plans]

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
                supplemental, supplemental_diagnostics = self._retrieve(
                    query=supplemental_query,
                    query_type=sq.get("type"),
                    filters=state["planned_filters"] or None,
                    top_k=8,
                    title_hint=sq.get("source_title") or None,
                    full_source=bool(sq.get("full_source")),
                )
                state["searches"].append(supplemental_diagnostics)
                state["chunks"] = self._dedupe_chunks(
                    state["chunks"] + supplemental
                )

        report("organizing")
        chunk_groups = []
        calculation_facts = []
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
            if target_id.startswith("operand_"):
                fact_chunk = next(
                    (chunk for chunk in chunks if chunk.get("raw_value") is not None),
                    None,
                )
                if fact_chunk:
                    calculation_facts.append({
                        "target_id": target_id,
                        "label": label,
                        "period": (
                            sq.get("operand_label")
                            or state["strict_filters"].get("column_header")
                            or label
                        ),
                        "raw_value": self._table_display_value(fact_chunk),
                        "unit": self._table_display_unit(fact_chunk),
                        "evidence": self._evidence_item(fact_chunk),
                    })
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
        evidence_limit = (
            4
            if len(sub_questions) == 1
            and sub_questions[0].get("type") == "regulation"
            else 8
        )
        unique_chunks = self._round_robin_chunks(
            chunk_groups, limit=evidence_limit
        )
        retrieval_diagnostics = {
            "targets": target_diagnostics,
            "supplemental_searches": supplemental_searches,
            "evidence_count": len(unique_chunks),
        }

        calculation_targets = [
            target for target in target_diagnostics
            if target["target_id"].startswith("operand_")
        ]
        incomplete_targets = [
            target for target in calculation_targets
            if target["coverage_status"] != "supported"
        ]
        if calculation_targets and incomplete_targets:
            missing_labels = "、".join(
                target["label"] for target in incomplete_targets
            )
            result = {
                "answer": "",
                "evidence": [],
                "refuse_reason": (
                    "参考资料未同时提供计算所需的全部数值，缺少："
                    f"{missing_labels}。"
                ),
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

        comparison_targets = [
            target for target in target_diagnostics
            if target["type"] == "table"
            and target["target_id"].startswith("option_")
        ]
        incomplete_comparison_targets = [
            target for target in comparison_targets
            if target["coverage_status"] != "supported"
        ]
        if comparison_targets and incomplete_comparison_targets:
            missing_labels = "、".join(
                target["label"] for target in incomplete_comparison_targets
            )
            result = {
                "answer": "",
                "evidence": [],
                "refuse_reason": (
                    "参考资料未提供比较所需的全部数值，缺少："
                    f"{missing_labels}。"
                ),
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

        if not unique_chunks:
            result = {
                "answer": "",
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

        context = self.context_assembler.assemble(
            system=system_prompt or SYSTEM_PROMPT,
            user=build_user_prompt(question, unique_chunks),
            history=history,
            complex_query=(
                len(sub_questions) > 1
                or any(item.get("type") == "hybrid" for item in sub_questions)
            ),
        )
        report("generating")
        generation_start = time.perf_counter()
        raw = self.llm.chat(
            context.system,
            context.user,
            history=context.history,
        )
        generation_ms = int((time.perf_counter() - generation_start) * 1000)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "answer": raw,
                "evidence": [],
                "refuse_reason": None,
            }

        deterministic_answer = self._build_deterministic_change_answer(
            question, calculation_facts
        )
        if deterministic_answer:
            result["answer"] = deterministic_answer
            result["evidence"] = self._build_calculation_evidence(
                calculation_facts
            )
            result["refuse_reason"] = None
            result.pop("evidence_ids", None)
        else:
            result = self._ground_model_result(result, unique_chunks)
        if isinstance(result.get("answer"), str):
            result["answer"] = self._normalize_answer_format(result["answer"])
        result.pop("confidence", None)
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

    def _retrieve(self, **kwargs) -> tuple[list, dict]:
        if hasattr(self.retriever, "retrieve_with_diagnostics"):
            result = self.retriever.retrieve_with_diagnostics(**kwargs)
            return result.chunks, copy.deepcopy(result.diagnostics)
        chunks = self.retriever.retrieve(**kwargs)
        return chunks, copy.deepcopy(
            getattr(self.retriever, "last_diagnostics", {})
        )

    def _ground_model_result(self, result: dict, chunks: list[dict]) -> dict:
        answer = result.get("answer")
        result.pop("evidence", None)
        evidence_ids = result.pop("evidence_ids", None)
        if not isinstance(answer, str) or not answer.strip():
            result["answer"] = "" if answer is None else answer
            result["evidence"] = []
            return result

        evidence_by_id = {
            f"E{index}": self._evidence_item(chunk)
            for index, chunk in enumerate(chunks, 1)
        }
        if (
            not isinstance(evidence_ids, list)
            or not evidence_ids
            or any(
                not isinstance(evidence_id, str)
                or evidence_id not in evidence_by_id
                for evidence_id in evidence_ids
            )
        ):
            return {
                "answer": "",
                "evidence": [],
                "refuse_reason": "模型回答未提供有效的原文证据引用",
            }

        selected = []
        seen = set()
        for evidence_id in evidence_ids:
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            selected.append(evidence_by_id[evidence_id])
        if not self._numeric_claims_are_grounded(answer, selected):
            return {
                "answer": "",
                "evidence": [],
                "refuse_reason": "模型回答包含参考资料中无法核验的数值或日期",
            }
        result["evidence"] = selected
        return result

    @classmethod
    def _numeric_claims_are_grounded(cls, answer: str, evidence: list[dict]) -> bool:
        answer_without_list_markers = re.sub(
            r"(?m)(^|[\n：:；;])\s*\d+[.．、]\s*",
            lambda match: match.group(1),
            answer,
        )
        answer_numbers = cls._numeric_tokens(answer_without_list_markers)
        if not answer_numbers:
            return True
        evidence_numbers = cls._numeric_tokens(
            "\n".join(str(item.get("text") or "") for item in evidence)
        )
        return answer_numbers.issubset(evidence_numbers)

    @staticmethod
    def _numeric_tokens(text: str) -> set[str]:
        tokens = set()
        for match in re.finditer(
            r"(?<![0-9a-z])\d[\d,]*(?:\.\d+)?%?",
            text.lower(),
        ):
            raw = match.group(0).replace(",", "")
            percent = raw.endswith("%")
            number = raw[:-1] if percent else raw
            try:
                normalized = format(Decimal(number), "f")
                if "." in normalized:
                    normalized = normalized.rstrip("0").rstrip(".")
            except InvalidOperation:
                normalized = number
            tokens.add(normalized + ("%" if percent else ""))
        return tokens

    @staticmethod
    def _normalize_answer_format(answer: str) -> str:
        markers = [
            int(match.group(1))
            for match in re.finditer(
                r"(?<!\d)([1-9]\d*)[.．、](?!\d)\s*", answer
            )
        ]
        if len(markers) < 2 or markers[:2] != [1, 2]:
            return answer.strip()
        normalized = re.sub(
            r"(?<![\d\n])[ \t]*(?=(?:[1-9]\d*)[.．、](?!\d)\s*)",
            "\n",
            answer,
        )
        return normalized.strip()

    @staticmethod
    def _table_display_value(chunk: dict) -> str:
        match = re.search(
            r"原始值为\s*([-+]?\d[\d,]*(?:\.\d+)?)",
            str(chunk.get("text") or ""),
        )
        if match:
            return match.group(1)
        return str(chunk.get("raw_value") or "").strip()

    @staticmethod
    def _table_display_unit(chunk: dict) -> str:
        unit = re.sub(
            r"^\s*单位\s*[:：]?\s*", "", str(chunk.get("unit") or "")
        ).strip()
        candidates = [
            candidate.strip()
            for candidate in re.split(r"[、,，/]", unit)
            if candidate.strip()
        ]
        if not candidates:
            return ""
        row_label = str(chunk.get("row_label") or chunk.get("indicator") or "")
        if re.search(r"率|比例|占比", row_label) and "%" in candidates:
            return "%"
        return candidates[0]

    @staticmethod
    def _evidence_item(chunk: dict) -> dict:
        section_path = chunk.get("section_path") or []
        if isinstance(section_path, (list, tuple)):
            section = "·".join(str(part) for part in section_path if part)
        else:
            section = str(section_path).strip()
        return {
            "source_title": str(chunk.get("source_title") or ""),
            "section": section or str(chunk.get("table_name") or ""),
            "text": str(chunk.get("text") or ""),
            "source_url": str(chunk.get("source_url") or ""),
        }

    @staticmethod
    def _build_calculation_evidence(facts: list) -> list:
        evidence = []
        seen = set()
        for fact in sorted(facts, key=lambda item: item["target_id"]):
            item = fact.get("evidence")
            if not isinstance(item, dict):
                continue
            key = (
                item.get("source_title"),
                item.get("section"),
                item.get("text"),
                item.get("source_url"),
            )
            if key in seen:
                continue
            seen.add(key)
            evidence.append(item)
        return evidence

    @staticmethod
    def _build_deterministic_change_answer(question: str, facts: list) -> str | None:
        if len(facts) != 2:
            return None
        facts = sorted(facts, key=lambda fact: fact["target_id"])
        try:
            first = Decimal(facts[0]["raw_value"].replace(",", ""))
            second = Decimal(facts[1]["raw_value"].replace(",", ""))
        except InvalidOperation:
            return None
        if facts[0]["unit"] != facts[1]["unit"]:
            return None

        if re.search(r"差额|相差|差多少", question):
            result = abs(second - first)
            operation_label = "差额"
            if first >= second:
                left, right = facts[0], facts[1]
            else:
                left, right = facts[1], facts[0]
        elif re.search(r"减少|下降", question):
            result = first - second
            operation_label = "减少量"
            left, right = facts[0], facts[1]
        else:
            result = second - first
            operation_label = "增加量" if re.search(r"增加|增长|上升", question) else "变化量"
            left, right = facts[1], facts[0]

        result_text = format(result, "f").rstrip("0").rstrip(".")
        unit = facts[0]["unit"]
        return (
            f"{facts[0]['period']}为{facts[0]['raw_value']}{unit}，"
            f"{facts[1]['period']}为{facts[1]['raw_value']}{unit}，"
            f"{operation_label}为{left['raw_value']} - {right['raw_value']} "
            f"= {result_text}{unit}。"
        )

    def _build_diagnostics(self, total_ms: int, decompose_ms: int,
                           retrieval_ms: int, generation_ms: int,
                           generation_metrics: dict,
                           retrieval_diagnostics: dict = None) -> dict:
        contextualization_metrics = dict(
            getattr(self.decomposer, "last_contextualization_metrics", {}) or {}
        )
        decomposition_metrics = (
            dict(self.decomposer.llm.last_call_metrics)
            if self.decomposer.last_decision_method == "model"
            else {}
        )
        llm_calls = (
            contextualization_metrics.get("api_calls", 0)
            + decomposition_metrics.get("api_calls", 0)
            + generation_metrics.get("api_calls", 0)
        )
        token_values = [
            metrics.get("total_tokens")
            for metrics in (
                contextualization_metrics, decomposition_metrics, generation_metrics,
            )
            if metrics.get("total_tokens") is not None
        ]
        cost_values = [
            metrics.get("provider_reported_cost")
            for metrics in (
                contextualization_metrics, decomposition_metrics, generation_metrics,
            )
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
                "contextualization": contextualization_metrics,
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
            "contextualized_question": getattr(
                self.decomposer, "last_contextualized_question", None
            ),
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
        structured_chunks = self._structured_table_chunks(chunks, sub_question)
        if sub_question.get("type") == "table" and self._table_filters(sub_question):
            return "supported" if structured_chunks else "missing"
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
        if sub_question.get("type") == "table" and self._table_filters(sub_question):
            if coverage_status != "supported":
                return []
            return self._structured_table_chunks(coverage_chunks, sub_question)
        coverage_terms = sub_question.get("coverage_terms") or []
        if coverage_status != "supported" or not coverage_terms:
            return chunks
        supporting = [
            chunk for chunk in coverage_chunks
            if self._chunks_cover_terms([chunk], coverage_terms)
        ]
        return self._dedupe_chunks(supporting + chunks)

    @staticmethod
    def _table_filters(sub_question: dict) -> dict:
        structural_keys = {
            "table_name", "indicator", "row_label", "column_header", "section_path",
        }
        return {
            key: value
            for key, value in (sub_question.get("strict_filters") or {}).items()
            if key in structural_keys and value not in (None, "", [])
        }

    def _structured_table_chunks(self, chunks: list, sub_question: dict) -> list:
        filters = self._table_filters(sub_question)
        if not filters:
            return chunks
        return [
            chunk for chunk in chunks
            if all(
                self._structured_value_matches(chunk.get(key), expected, key)
                for key, expected in filters.items()
            )
        ]

    def _structured_value_matches(self, actual, expected, key: str) -> bool:
        if isinstance(actual, (list, tuple, set)):
            actual = " ".join(str(value) for value in actual)
        normalized_actual = self._normalize_text(actual or "")
        normalized_expected = self._normalize_text(expected or "")
        if not normalized_actual or not normalized_expected:
            return False
        if key == "table_name":
            return normalized_actual == normalized_expected
        return (
            normalized_expected in normalized_actual
            or normalized_actual in normalized_expected
        )

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
