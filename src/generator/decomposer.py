import json
import re

from src.context_control import select_controlled_history
from src.generator.llm_client import LLMClient
from src.indexer.bm25_index import PublishedBM25Index
from src.judgment import MAX_CHOICE_OPTIONS, Judge
from src.retriever.router import QueryRouter

# 枚举候选坐标要看完整张表，不能被 chunks_for_source_titles 的默认上限截断
_MAX_INDEX_CHUNKS = 100_000

CONTEXTUALIZE_PROMPT = """结合对话历史，把当前追问改写成不依赖上文、可以直接用于知识库检索的独立问题。

要求：
1. 不要回答问题，只改写问题
2. 只补全历史中明确出现的文件名、主体、指标、时间和口径，不得猜测
3. 保留当前追问真正想问的内容，不要重复上一轮已经回答的问题
4. 只输出 JSON：{{"question": "改写后的独立问题"}}

【对话历史】
{history}

【当前追问】
{question}"""


class QueryDecomposer:
    def __init__(self, include_single_fact_options: bool = False,
                 bm25=None, judge=None):
        self.llm = LLMClient()
        self.judge = judge or Judge()
        self.router = QueryRouter(judge=self.judge)
        self.bm25 = bm25 or PublishedBM25Index()
        self.include_single_fact_options = include_single_fact_options
        self.last_decision_method = None
        self.last_route = None
        self.last_contextualized_question = None
        self.last_contextualization_metrics = {}
        self.last_judgment_metrics = {"api_calls": 0}

    def decompose(self, question: str, history: list = None) -> list:
        history = history or []
        self.last_contextualized_question = None
        self.last_contextualization_metrics = {}
        self.last_judgment_metrics = {"api_calls": 0}

        conversation = self._conversation_digest(history)
        route = self.router.route(question, conversation)
        self._count_judgment()
        self.last_decision_method = "judgment"
        self.last_route = route

        if route == "table":
            table_targets = self._decompose_table(
                question, history, conversation
            )
            if table_targets:
                return table_targets

        if history and self._needs_history_context(question):
            question = self._contextualize(question, history)
            self.last_contextualized_question = question

        if route in {"regulation", "hybrid"}:
            claim_targets = self._decompose_multi_fact_options(question, route)
            if claim_targets:
                return claim_targets
            if self.include_single_fact_options:
                option_targets = self._decompose_single_fact_options(question, route)
                if option_targets:
                    return option_targets
            reference_targets = self._decompose_option_references(question, route)
            if reference_targets:
                return reference_targets
        return [self._single_target(question, route)]

    def _count_judgment(self):
        self.last_judgment_metrics["api_calls"] += 1

    def _conversation_digest(self, history: list) -> str:
        lines = []
        for message in select_controlled_history(history):
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role not in {"system", "user", "assistant"} or not content:
                continue
            lines.append(f"{role}: {content}")
            for item in message.get("evidence") or []:
                lines.append(
                    f"  证据《{item.get('source_title', '')}》"
                    f"{item.get('text', '')}"
                )
        return "\n".join(lines)

    def _needs_history_context(self, question: str) -> bool:
        text = question.strip()
        if re.match(
            r"^(?:那|那么)(?:一|每|各|任一)(?:份|个|家|项|类|种|条|笔|张)",
            text,
        ):
            return False
        return bool(re.search(
            r"^(?:那|那么|它|其|该|这个|这项|这些|上述|前述|其中|前者|后者|"
            r"具体|还有|另外|两地|两者|二者)|(?:该|上述|前述|这个|这些|其)"
            r"(?:规定|文件|公司|机构|指标|数值|要求|情况)|(?:呢|又如何)[？?]?$",
            text,
        ))

    def _contextualize(self, question: str, history: list) -> str:
        history = select_controlled_history(history)
        messages = [
            message for message in history
            if message.get("role") in {"system", "user", "assistant"}
            and str(message.get("content", "")).strip()
        ]
        if not messages:
            return question
        history_text = "\n".join(
            f"{message['role']}: {message['content']}" for message in messages
        )
        try:
            response = self.llm.chat(
                system="你是一个检索问题改写助手，只输出 JSON。",
                user=CONTEXTUALIZE_PROMPT.format(
                    history=history_text,
                    question=question,
                ),
            )
            metrics = getattr(self.llm, "last_call_metrics", {})
            if isinstance(metrics, dict):
                self.last_contextualization_metrics = dict(metrics)
            rewritten = json.loads(response).get("question", "").strip()
            if rewritten:
                return rewritten
        except Exception:
            pass
        previous_user = next(
            (
                str(message["content"]).strip()
                for message in reversed(messages)
                if message["role"] == "user"
            ),
            "",
        )
        return f"{previous_user} 当前追问：{question}".strip()

    def _routing_text(self, question: str) -> str:
        return re.split(r"\n\s*[AＡ][\.．、:：\)）]\s*", question, maxsplit=1)[0]

    def _decompose_table(self, question: str, history: list,
                         conversation: str) -> list:
        stem = self._routing_text(question)
        title_hint = self._title_hint(stem, history)
        titles, match_mode = [], "none"
        if title_hint:
            titles, match_mode = self.bm25.resolve_source_titles(title_hint)
        if not titles or match_mode not in {"exact", "near", "alias"}:
            # 问题里没写文件名，就让 BM25 先决定问的是哪一张表
            titles = self._titles_from_search(question)
        if not titles:
            return []
        chunks = self.bm25.chunks_for_source_titles(
            titles,
            filters={"chunk_type": "table_row"},
            max_chunks=_MAX_INDEX_CHUNKS,
        )
        if not chunks:
            return []

        source_title = titles[0]
        candidates = self._candidates(chunks, question, titles)
        state = {"question": question, "source_title": source_title}
        if conversation:
            state["conversation"] = conversation

        options = self._parse_options(question)
        if options:
            # 选项匹不到任何一行时说明不是选项匹配题，按两处取数再算
            option_targets = self._table_option_targets(
                options, source_title, candidates, state
            )
            if option_targets:
                return option_targets
        return self._table_operand_targets(
            source_title, candidates, state, bool(history)
        )

    def _title_hint(self, stem: str, history: list) -> str:
        match = re.search(r"《([^》]+)》", stem)
        if match:
            return match.group(1).strip()
        for message in reversed(history):
            for item in message.get("evidence") or []:
                title = str(item.get("source_title") or "").strip()
                if title:
                    return title
        return ""

    def _titles_from_search(self, question: str) -> list:
        hits = self.bm25.search(
            question,
            top_k=8,
            filters={"chunk_type": "table_row"},
        )
        for hit in hits:
            title = str(hit.get("source_title") or "").strip()
            if title:
                return [title]
        return []

    def _candidates(self, chunks: list, question: str, titles: list) -> dict:
        candidates = {}
        for field in ("row_label", "column_header", "period", "table_name"):
            values = set()
            for chunk in chunks:
                value = str(chunk.get(field) or "").strip()
                if value:
                    values.add(value)
            candidates[field] = self._narrow(
                sorted(values), question, titles, field
            )
        sections = set()
        for chunk in chunks:
            for part in chunk.get("section_path") or []:
                text = str(part or "").strip()
                if text:
                    sections.add(text)
        candidates["section_path"] = self._narrow(
            sorted(sections), question, titles, "section_path"
        )
        return candidates

    def _narrow(self, values: list, question: str, titles: list,
                field: str) -> list:
        if len(values) <= MAX_CHOICE_OPTIONS:
            return values
        # 候选超过 Choice 上限，先用 BM25 把这张表的行收窄到与问题最相关的一批
        hits = self.bm25.search(
            question,
            top_k=MAX_CHOICE_OPTIONS,
            filters={"source_title": titles, "chunk_type": "table_row"},
        )
        ranked = []
        for hit in hits:
            raw = hit.get(field)
            for part in raw if isinstance(raw, list) else [raw]:
                text = str(part or "").strip()
                if text and text not in ranked:
                    ranked.append(text)
        return (ranked or values)[:MAX_CHOICE_OPTIONS]

    def _table_operand_targets(self, source_title: str, candidates: dict,
                               state: dict, has_history: bool) -> list:
        selected = self.judge.table_coordinates(state, candidates)
        self._count_judgment()
        row_1 = selected.get("row_1")
        column_1 = selected.get("column_1")
        if not row_1 and not column_1:
            return []
        row_2 = selected.get("row_2")
        column_2 = selected.get("column_2")
        section = selected.get("section")
        period = selected.get("period")

        pairs = [(row_1, column_1)]
        second = (row_2 or row_1, column_2 or column_1)
        if (row_2 or column_2) and second != pairs[0]:
            pairs.append(second)
        # 问题要两个数值，但表格里找不到第二个坐标：必须拒答，不能只答一个数
        unresolved_second = len(pairs) == 1 and bool(selected.get("needs_second"))

        targets = []
        for index, (row_label, column_header) in enumerate(pairs, 1):
            display_row = re.sub(r"\s+", "", row_label) if row_label else ""
            label_parts = [part for part in (display_row, column_header) if part]
            strict_filters = {}
            if row_label:
                strict_filters["row_label"] = row_label
            if column_header:
                strict_filters["column_header"] = column_header
            coverage_terms = list(label_parts)
            if section:
                strict_filters["section_path"] = section
                coverage_terms.append(section)
            query_parts = [
                f"《{source_title}》", section, period, display_row, column_header,
            ]
            target = {
                "target_id": "operand_1" if unresolved_second else (
                    "main" if len(pairs) == 1 else f"operand_{index}"
                ),
                "label": " / ".join(label_parts),
                "question": " ".join(part for part in query_parts if part),
                "type": "table",
                "source_title": source_title,
                "filters": {},
                "strict_filters": strict_filters,
                "coverage_terms": coverage_terms,
            }
            if len(pairs) == 2 and pairs[0][0] != pairs[1][0]:
                target["operand_label"] = display_row
            targets.append(target)

        if unresolved_second:
            targets.append({
                "target_id": "operand_2",
                "label": f"《{source_title}》中没有对应行列的第二个数值",
                "question": f"《{source_title}》",
                "type": "table",
                "source_title": source_title,
                "filters": {},
                "strict_filters": {},
                "coverage_terms": [],
                "unresolved": True,
            })

        if has_history:
            rows = [
                re.sub(r"\s+", "", row) for row, _ in pairs if row
            ]
            columns = [column for _, column in pairs if column]
            resolved = [
                f"《{source_title}》",
                section,
                period,
                "和".join(dict.fromkeys(rows)),
                "和".join(dict.fromkeys(columns)),
            ]
            self.last_contextualized_question = " ".join(
                part for part in resolved if part
            )
            # 判断调用次数记在 last_judgment_metrics，这里不重复计数
            self.last_contextualization_metrics = {
                "method": "judgment",
                "api_calls": 0,
            }
        return targets

    def _table_option_targets(self, options: dict, source_title: str,
                              candidates: dict, state: dict) -> list:
        selected = self.judge.table_option_rows(state, options, candidates)
        self._count_judgment()
        column_header = selected.get("column")
        table_name = selected.get("table_name")

        targets = []
        for option in options:
            row_label = selected.get(f"option_{option}")
            if not row_label:
                return []
            display_row = re.sub(r"\s+", "", row_label)
            strict_filters = {}
            if table_name:
                strict_filters["table_name"] = table_name
            strict_filters["row_label"] = row_label
            if column_header:
                strict_filters["column_header"] = column_header
            query_parts = [f"《{source_title}》"]
            if table_name:
                query_parts.append(f"工作表 {table_name}")
            if column_header:
                query_parts.append(column_header)
            query_parts.append(display_row)
            coverage_terms = [display_row]
            if column_header:
                coverage_terms.append(column_header)
            targets.append({
                "target_id": f"option_{option}",
                "label": f"{option}. {display_row}",
                "question": " ".join(query_parts),
                "type": "table",
                "source_title": source_title,
                "filters": {},
                "strict_filters": strict_filters,
                "coverage_terms": coverage_terms,
                "option": option,
            })
        return targets

    def _parse_options(self, question: str) -> dict:
        fullwidth = str.maketrans("ＡＢＣＤ", "ABCD")
        matches = re.findall(
            r"^\s*([A-DＡ-Ｄ])[\.．、:：\)）]\s*(.+?)\s*$",
            question,
            flags=re.MULTILINE,
        )
        return {label.translate(fullwidth): text.strip() for label, text in matches}

    def _decompose_multi_fact_options(self, question: str, query_type: str) -> list:
        stem = self._routing_text(question)
        if not re.search(r"两项表述均|均属于|均符合|两项均", stem):
            return []

        options = self._parse_options(question)
        if not options:
            return []

        title_match = re.search(r"《([^》]+)》", stem)
        source_title = title_match.group(1).strip() if title_match else ""
        memberships = {}
        for option, text in options.items():
            claims = [part.strip() for part in re.split(r"[；;]", text) if part.strip()]
            if len(claims) < 2:
                return []
            for claim in claims:
                memberships.setdefault(claim, []).append(option)

        targets = []
        title_prefix = f"《{source_title}》 " if source_title else ""
        for index, (claim, claim_options) in enumerate(memberships.items(), 1):
            targets.append({
                "target_id": f"claim_{index}",
                "label": f"选项 {'/'.join(claim_options)}：{claim}",
                "question": f"{title_prefix}{claim}",
                "type": query_type,
                "source_title": source_title,
                "filters": {},
                "strict_filters": {},
                "coverage_terms": [claim],
                "options": claim_options,
            })
        return targets

    def _decompose_option_references(self, question: str, query_type: str) -> list:
        options = self._parse_options(question)
        if not options:
            return []

        stem = self._routing_text(question)
        stem_match = re.search(r"《([^》]+)》", stem)
        stem_title = stem_match.group(1).strip() if stem_match else ""
        normalized_stem_title = self._normalize_title(stem_title)
        references = []
        seen_titles = set()
        for option, text in options.items():
            for index, title in enumerate(re.findall(r"《([^》]+)》", text), 1):
                title = title.strip()
                normalized_title = self._normalize_title(title)
                if not normalized_title or normalized_title == normalized_stem_title:
                    continue
                if normalized_title in seen_titles:
                    continue
                seen_titles.add(normalized_title)
                claim = re.sub(r"《[^》]+》", "", text).strip().rstrip("。；;")
                references.append({
                    "target_id": f"reference_{option}_{index}",
                    "label": f"选项 {option} 引用：{title}",
                    "question": text,
                    "type": query_type,
                    "source_title": title,
                    "filters": {},
                    "strict_filters": {},
                    "coverage_terms": [claim] if claim else [],
                    "option": option,
                    "full_source": True,
                })

        if not references:
            return []
        main_target = self._single_target(question, query_type)
        main_target["full_source"] = True
        return [main_target, *references]

    def _decompose_single_fact_options(self, question: str,
                                       query_type: str) -> list:
        options = self._parse_options(question)
        if not options:
            return []
        stem = self._routing_text(question)
        title_match = re.search(r"《([^》]+)》", stem)
        source_title = title_match.group(1).strip() if title_match else ""
        if not source_title:
            return []
        return [
            {
                "target_id": f"option_{option}",
                "label": f"{option}. {claim}",
                "question": f"《{source_title}》 {claim}",
                "type": query_type,
                "source_title": source_title,
                "filters": {},
                "strict_filters": {},
                "coverage_terms": [claim],
                "option": option,
            }
            for option, claim in options.items()
        ]

    def _normalize_title(self, title: str) -> str:
        return re.sub(r"[^0-9a-z一-鿿]+", "", str(title).lower())

    def _single_target(self, question: str, query_type: str) -> dict:
        stem = self._routing_text(question).strip()
        title_match = re.search(r"《([^》]+)》", stem)
        source_title = title_match.group(1).strip() if title_match else ""
        return {
            "target_id": "main",
            "label": stem,
            "question": question,
            "type": query_type,
            "source_title": source_title,
            "filters": {},
            "strict_filters": {},
            "coverage_terms": [],
        }
