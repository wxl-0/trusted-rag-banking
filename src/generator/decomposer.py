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
            return [{"question": question, "type": rule_route}]

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
        return [{"question": question, "type": "hybrid"}]

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
