from types import SimpleNamespace
from unittest.mock import patch

from src.generator.llm_client import LLMClient


class FakeCompletions:
    def __init__(self):
        self.arguments = None

    def create(self, **kwargs):
        self.arguments = kwargs
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=None,
        )


def test_llm_client_uses_deepseek_default_and_budgeted_complete_history(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("CONTEXT_OUTPUT_RESERVE_TOKENS", "12288")
    completions = FakeCompletions()
    fake_openai = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )
    history = [
        {"role": "user", "content": f"history-{index}"}
        for index in range(8)
    ]

    with patch("src.generator.llm_client.OpenAI", return_value=fake_openai):
        client = LLMClient()
        result = client.chat("system", "question", history=history)

    assert result == "ok"
    assert client.model == "deepseek-v4-flash"
    assert completions.arguments["model"] == "deepseek-v4-flash"
    assert completions.arguments["max_tokens"] == 12_288
    assert completions.arguments["messages"][1:-1] == history
