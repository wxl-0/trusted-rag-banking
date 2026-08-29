import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

QUERY_TYPES = ["regulation", "table", "hybrid", "out_of_scope"]

ROUTER_PROMPT = """你是银行业监管问答系统的查询分类器。
根据用户问题，判断应该查询哪类知识库。

返回以下之一（只返回英文标签，不要解释）：
- regulation  （制度条款、流程、定义、阈值、禁止事项）
- table       （统计数据、指标数值、报表取数、数值比较或计算）
- hybrid      （需要同时查制度和统计数据，或跨文件、跨条目判断）
- out_of_scope（与银行/保险监管制度、行业统计报表完全无关的问题，如闲聊、编程、其他行业话题）

注意：知识库覆盖银行保险监管制度文件和行业统计报表。只要问题涉及监管规定或行业统计数据，就不要返回 out_of_scope；拿不准时返回 hybrid。

问题：{question}"""


class QueryRouter:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

    def route(self, question: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": ROUTER_PROMPT.format(question=question)}],
                temperature=0,
                max_tokens=20,
            )
            content = response.choices[0].message.content
        except Exception:
            return "hybrid"
        if not content:
            # 中转平台偶发返回空 content，默认走混合检索
            return "hybrid"
        label = content.strip().lower()
        return label if label in QUERY_TYPES else "hybrid"
