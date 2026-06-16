import json
from src.generator.llm_client import LLMClient

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

    def decompose(self, question: str) -> list:
        response = self.llm.chat(
            system="你是一个问题分析助手，只输出 JSON。",
            user=DECOMPOSE_PROMPT.format(question=question),
        )
        try:
            data = json.loads(response)
            if data.get("needs_decompose") and data.get("sub_questions"):
                return data["sub_questions"]
        except (json.JSONDecodeError, KeyError):
            pass
        return [{"question": question, "type": "hybrid"}]
