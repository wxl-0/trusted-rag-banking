import json
import re
from src.generator.llm_client import LLMClient


TABLE_CUES = (
    "excel", "工作表", "取数", "数值", "计算", "合计", "变化", "余额",
    "收入", "最高", "最低", "增长", "占比", "金额", "统计数据", "指标",
)
REGULATION_CUES = (
    "办法", "规定", "指引", "监管规则", "应当", "不得", "定义", "表述",
    "材料内容", "名单", "制度", "监管",
)

DECOMPOSE_PROMPT = """判断下面的问题是否需要分步查询（先查制度，再查统计数据）。

如果需要分步，将其拆分为子问题列表，每个子问题标注类型（regulation 或 table）。
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


class QueryDecomposer:
    def __init__(self):
        self.llm = LLMClient()
        self.last_decision_method = None
        self.last_route = None

    def decompose(self, question: str) -> list:
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
        if not change_match:
            return []

        row_label, first_column, second_column = change_match.groups()
        source_title = title_match.group(1).strip() if title_match else ""
        title_prefix = f"《{source_title}》 " if source_title else ""
        targets = []
        for index, column_header in enumerate((first_column, second_column), 1):
            targets.append({
                "target_id": f"operand_{index}",
                "label": f"{row_label} / {column_header}",
                "question": f"{title_prefix}{row_label} {column_header}",
                "type": "table",
                "source_title": source_title,
                "filters": {},
                "strict_filters": {
                    "row_label": row_label,
                    "column_header": column_header,
                },
                "coverage_terms": [row_label, column_header],
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
