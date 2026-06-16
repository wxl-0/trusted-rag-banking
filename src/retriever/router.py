import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

QUERY_TYPES = ["regulation", "table", "hybrid", "out_of_scope"]

ROUTER_PROMPT = """你是银行业监管问答系统的查询分类器。
根据用户问题，判断应该查询哪类知识库。

返回以下之一（只返回英文标签，不要解释）：
- regulation  （制度条款、流程、定义、阈值、禁止事项）
- table       （统计数据、指标数值、报表取数）
- hybrid      （需要同时查制度和统计数据，或跨文件判断）
- out_of_scope（问题与银行业监管无关）

问题：{question}"""


class QueryRouter:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    def route(self, question: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": ROUTER_PROMPT.format(question=question)}],
            temperature=0,
            max_tokens=20,
        )
        label = response.choices[0].message.content.strip().lower()
        return label if label in QUERY_TYPES else "hybrid"
