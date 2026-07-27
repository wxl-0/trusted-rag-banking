import os
import time
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

_MAX_ATTEMPTS = 3


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    def chat(self, system: str, user: str, temperature: float = 0, history: list = None) -> str:
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history[-6:])
        messages.append({"role": "user", "content": user})

        last_error = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )
                content = response.choices[0].message.content
                if content:
                    return content
                # 中转平台偶发返回空 content，退避后重试
            except Exception as e:
                last_error = e
            time.sleep(2 ** attempt)

        if last_error is not None:
            raise last_error
        return ""
