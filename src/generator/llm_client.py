import os
import time
from openai import OpenAI
from dotenv import load_dotenv

from src.context_control import ContextSettings

load_dotenv()

_MAX_ATTEMPTS = 3


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("LLM_MODEL", "deepseek-v4-flash")
        self.last_call_metrics = {}

    def chat(self, system: str, user: str, temperature: float = 0, history: list = None) -> str:
        messages = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})

        started_at = time.perf_counter()
        metrics = {
            "api_calls": 0,
            "retries": 0,
            "latency_ms": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "provider_reported_cost": None,
        }
        last_error = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                metrics["api_calls"] += 1
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=ContextSettings.from_env().output_reserve_tokens,
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        value = getattr(usage, field, None)
                        if value is not None:
                            metrics[field] = (metrics[field] or 0) + value
                    cost = getattr(usage, "cost", None)
                    if cost is not None:
                        metrics["provider_reported_cost"] = (
                            (metrics["provider_reported_cost"] or 0) + float(cost)
                        )
                content = response.choices[0].message.content
                if content:
                    metrics["retries"] = max(metrics["api_calls"] - 1, 0)
                    metrics["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
                    self.last_call_metrics = metrics
                    return content
                # 中转平台偶发返回空 content，退避后重试
            except Exception as e:
                last_error = e
            time.sleep(2 ** attempt)

        metrics["retries"] = max(metrics["api_calls"] - 1, 0)
        metrics["latency_ms"] = int((time.perf_counter() - started_at) * 1000)
        self.last_call_metrics = metrics
        if last_error is not None:
            raise last_error
        return ""
