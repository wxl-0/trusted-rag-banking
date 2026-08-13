import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ask_empty_question():
    response = client.post("/api/ask", json={"question": ""})
    assert response.status_code == 400


def test_ask_returns_structured_response():
    mock_result = {
        "answer": "资本充足率不得低于10.5%。",
        "evidence": [
            {
                "source_title": "商业银行资本管理办法",
                "section": "第三章第十二条",
                "text": "资本充足率不得低于10.5%",
                "source_url": "https://example.com",
            }
        ],
        "refuse_reason": None,
        "latency_ms": 800,
    }
    with patch("src.api.routes.builder.answer", return_value=mock_result):
        response = client.post("/api/ask", json={"question": "资本充足率要求是多少？"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "资本充足率不得低于10.5%。"
    assert "confidence" not in data
    assert len(data["evidence"]) == 1
