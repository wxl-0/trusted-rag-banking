import json
import re
from src.generator.llm_client import LLMClient


TABLE_CUES = (
    "excel", "工作表", "取数", "数值", "计算", "合计", "变化", "余额",
    "收入", "最高", "最低", "增长", "增加", "减少", "上升", "下降",
    "占比", "金额", "统计数据", "指标", "季度", "总资产", "总负债",
)
REGULATION_CUES = (
    "办法", "规定", "指引", "监管规则", "应当", "不得", "定义", "表述",
    "材料内容", "名单", "制度", "监管", "询证函", "函证",
)

DECOMPOSE_PROMPT = """判断下面的问题是否需要分步查询。

如果需要分步，将其拆分为子问题列表，每个子问题标注类型（regulation 或 table）。
表格跨期变化、增减、增长或比较问题必须把两个时期分别拆成独立的 table
取数子问题，并在每个子问题中保留区块、指标和对应时期。即使问题没有文件名、
没有引号，也不能把两个时期合并为一次检索。
如果不需要分步，返回原问题。

输出 JSON 格式：
{{
  "needs_decompose": true 或 false,
  "sub_questions": [
    {{"question": "子问题1", "type": "regulation"}},
    {{"question": "子问题2", "type": "table"}}
  ]
}}

问题：{question}"""

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
    def __init__(self, include_single_fact_options: bool = False):
        self.llm = LLMClient()
        self.include_single_fact_options = include_single_fact_options
        self.last_decision_method = None
        self.last_route = None
        self.last_contextualized_question = None
        self.last_contextualization_metrics = {}

    def decompose(self, question: str, history: list = None) -> list:
        self.last_contextualized_question = None
        self.last_contextualization_metrics = {}
        if history and self._needs_history_context(question):
            question = self._contextualize(question, history)
            self.last_contextualized_question = question
        return self._decompose(question)

    def _decompose(self, question: str) -> list:
        rule_route = self._rule_route(self._routing_text(question))
        if rule_route:
            self.last_decision_method = "rule"
            self.last_route = rule_route
            if rule_route == "table":
                table_targets = self._decompose_table_change(question)
                if table_targets:
                    return table_targets
                comparison_targets = self._decompose_table_comparison(question)
                if comparison_targets:
                    return comparison_targets
            if rule_route in {"regulation", "hybrid"}:
                claim_targets = self._decompose_multi_fact_options(question, rule_route)
                if claim_targets:
                    return claim_targets
                if self.include_single_fact_options:
                    option_targets = self._decompose_single_fact_options(
                        question, rule_route
                    )
                    if option_targets:
                        return option_targets
                reference_targets = self._decompose_option_references(question, rule_route)
                if reference_targets:
                    return reference_targets
            return [self._single_target(question, rule_route)]

        self.last_decision_method = "model"
        response = self.llm.chat(
            system="你是一个问题分析助手，只输出 JSON。",
            user=DECOMPOSE_PROMPT.format(question=question),
        )
        try:
            data = json.loads(response)
            if data.get("needs_decompose") and data.get("sub_questions"):
                self.last_route = "decomposed"
                return data["sub_questions"]
        except (json.JSONDecodeError, KeyError):
            pass
        self.last_route = "hybrid"
        return [self._single_target(question, "hybrid")]

    def _needs_history_context(self, question: str) -> bool:
        text = question.strip()
        if re.match(
            r"^(?:那|那么)(?:一|每|各|任一)(?:份|个|家|项|类|种|条|笔|张)",
            text,
        ):
            return False
        return bool(re.search(
            r"^(?:那|那么|它|其|该|这个|这项|这些|上述|前述|其中|前者|后者|"
            r"具体|还有|另外)|(?:该|上述|前述|这个|这些|其)"
            r"(?:规定|文件|公司|机构|指标|数值|要求|情况)|(?:呢|又如何)[？?]?$",
            text,
        ))

    def _contextualize(self, question: str, history: list) -> str:
        messages = [
            message for message in history
            if message.get("role") in {"user", "assistant"}
            and str(message.get("content", "")).strip()
        ][-6:]
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

    def _rule_route(self, question: str) -> str | None:
        normalized = question.lower()
        has_table_cue = any(cue in normalized for cue in TABLE_CUES)
        has_regulation_cue = any(cue in normalized for cue in REGULATION_CUES)
        if has_table_cue and has_regulation_cue:
            return "hybrid"
        if has_table_cue:
            return "table"
        if has_regulation_cue:
            return "regulation"
        return None

    def _routing_text(self, question: str) -> str:
        return re.split(r"\n\s*[AＡ][\.．、:：\)）]\s*", question, maxsplit=1)[0]

    def _decompose_table_change(self, question: str) -> list:
        title_match = re.search(r"《([^》]+)》", question)
        change_match = re.search(
            r"[“\"]([^”\"]+)[”\"]\s*从[“\"]([^”\"]+)[”\"]\s*到[“\"]([^”\"]+)[”\"]",
            question,
        )
        section_path = ""
        if change_match:
            row_label, first_column, second_column = change_match.groups()
        else:
            period = r"(?:第?[一二三四1234]季度|期初|期末|年初|年末|上年末|本期|上期)"
            natural_match = re.search(
                rf"([^，。；？！]+?)从[“\"]?({period})[”\"]?\s*到[“\"]?({period})[”\"]?",
                question,
            )
            if not natural_match:
                return []
            subject, first_column, second_column = natural_match.groups()
            subject = re.sub(r"^.*?\b\d{4}年", "", subject).strip(" ，,：:")
            subject = subject.replace("“", "").replace("”", "").strip()
            if "的" in subject:
                section_path, row_label = (
                    part.strip() for part in subject.rsplit("的", 1)
                )
            else:
                row_label = subject
        source_title = title_match.group(1).strip() if title_match else ""
        if not section_path:
            section_match = re.search(
                r"(?:在|于)\s*[“\"]?([^”\"，,]+?)[”\"]?\s*"
                r"(?:区块|板块|部分)(?:中|内)?",
                question,
            )
            section_path = section_match.group(1).strip() if section_match else ""
        if not section_path:
            possessive_match = re.search(
                rf"(?:^|[，,])(?:\d{{4}}年)?[“\"]?([^”\"，,]+?)[”\"]?"
                rf"的[“\"]?{re.escape(row_label)}[”\"]?\s*从",
                question,
            )
            if possessive_match:
                section_path = possessive_match.group(1).strip()
        title_prefix = f"《{source_title}》 " if source_title else ""
        targets = []
        for index, column_header in enumerate((first_column, second_column), 1):
            query_parts = [title_prefix.strip(), section_path, row_label, column_header]
            strict_filters = {
                "row_label": row_label,
                "column_header": column_header,
            }
            coverage_terms = [row_label, column_header]
            if section_path:
                strict_filters["section_path"] = section_path
                coverage_terms.append(section_path)
            targets.append({
                "target_id": f"operand_{index}",
                "label": f"{row_label} / {column_header}",
                "question": " ".join(part for part in query_parts if part),
                "type": "table",
                "source_title": source_title,
                "filters": {},
                "strict_filters": strict_filters,
                "coverage_terms": coverage_terms,
            })
        return targets

    def _decompose_table_comparison(self, question: str) -> list:
        stem = self._routing_text(question)
        if not re.search(r"最高|最低|最大|最小", stem):
            return []

        options = self._parse_options(question)
        if not options:
            return []

        title_match = re.search(r"《([^》]+)》", stem)
        sheet_match = re.search(
            r"工作表\s*[：:]\s*(.+?)(?=[）)]\s*[，,])",
            stem,
        )
        if not sheet_match:
            sheet_match = re.search(r"工作表\s*[：:]\s*([^）)\n]+)", stem)
        column_match = re.search(r"在[“\"]([^”\"]+)[”\"]口径", stem)
        source_title = title_match.group(1).strip() if title_match else ""
        table_name = sheet_match.group(1).strip() if sheet_match else ""
        column_header = column_match.group(1).strip() if column_match else ""

        targets = []
        for option, indicator in options.items():
            parts = []
            if source_title:
                parts.append(f"《{source_title}》")
            if table_name:
                parts.append(f"工作表 {table_name}")
            if column_header:
                parts.append(column_header)
            parts.append(indicator)

            strict_filters = {}
            if table_name:
                strict_filters["table_name"] = table_name
            strict_filters["indicator"] = indicator
            if column_header:
                strict_filters["column_header"] = column_header

            coverage_terms = [indicator]
            if column_header:
                coverage_terms.append(column_header)
            targets.append({
                "target_id": f"option_{option}",
                "label": f"{option}. {indicator}",
                "question": " ".join(parts),
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
        return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(title).lower())

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
