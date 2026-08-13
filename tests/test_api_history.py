"""测试 /api/ask 的 history 多轮对话参数传递。"""
import sys
import importlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _mock_heavy_deps():
    """Pre-mock heavy deps so the entire import chain resolves."""
    mods_to_mock = [
        "sentence_transformers",
        "torch",
        "transformers",
        "qdrant_client",
        "qdrant_client.models",
        "rank_bm25",
        "openai",
        "dotenv",
    ]
    originals = {}
    for mod in mods_to_mock:
        if mod not in sys.modules:
            mock = MagicMock()
            sys.modules[mod] = mock
            originals[mod] = None
        else:
            originals[mod] = sys.modules[mod]

    yield

    for mod, orig in originals.items():
        if orig is None:
            sys.modules.pop(mod, None)


@pytest.fixture
def client():
    # Force reimport of the app with mocked deps
    # Mock AnswerBuilder.__init__ so it doesn't create real objects
    with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
        from src.api.main import app
        from fastapi.testclient import TestClient
        return TestClient(app)


def test_ask_with_history_passes_to_builder(client):
    mock_result = {
        "answer": "追问的回答。",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 200,
    }

    from src.api import routes as routes_mod
    with patch.object(routes_mod.builder, "answer", return_value=mock_result) as mock_answer:
        response = client.post("/api/ask", json={
            "question": "具体是哪一条？",
            "history": [
                {"role": "user", "content": "资本充足率要求是多少？"},
                {"role": "assistant", "content": "不得低于10.5%。"},
            ],
        })

    assert response.status_code == 200
    mock_answer.assert_called_once()
    _, kwargs = mock_answer.call_args
    assert len(kwargs["history"]) == 2
    assert kwargs["history"][0]["role"] == "user"
    assert kwargs["history"][1]["role"] == "assistant"


def test_ask_without_history_works(client):
    mock_result = {
        "answer": "回答内容。",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 100,
    }

    from src.api import routes as routes_mod
    with patch.object(routes_mod.builder, "answer", return_value=mock_result) as mock_answer:
        response = client.post("/api/ask", json={"question": "什么是拨备覆盖率？"})

    assert response.status_code == 200
    _, kwargs = mock_answer.call_args
    assert kwargs["history"] == []


def test_ask_history_empty_list(client):
    mock_result = {
        "answer": "回答。",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 50,
    }

    from src.api import routes as routes_mod
    with patch.object(routes_mod.builder, "answer", return_value=mock_result) as mock_answer:
        response = client.post("/api/ask", json={
            "question": "问题",
            "history": [],
        })

    assert response.status_code == 200
    _, kwargs = mock_answer.call_args
    assert kwargs["history"] == []
