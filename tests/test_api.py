import json

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


def test_ask_stream_returns_real_stages_and_final_answer():
    mock_result = {
        "answer": "资本充足率不得低于10.5%。",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 800,
    }

    def answer_with_progress(*args, progress_callback=None, **kwargs):
        for stage in ("analyzing", "retrieving", "organizing", "generating"):
            progress_callback(stage)
        return mock_result

    with patch("src.api.routes.builder.answer", side_effect=answer_with_progress):
        response = client.post(
            "/api/ask/stream",
            json={"question": "资本充足率要求是多少？"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = []
    current_event = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append((current_event, json.loads(line.removeprefix("data: "))))
    assert [(event, data.get("stage")) for event, data in events[:-1]] == [
        ("progress", "analyzing"),
        ("progress", "retrieving"),
        ("progress", "organizing"),
        ("progress", "generating"),
    ]
    assert [data["message"] for _, data in events[:-1]] == [
        "正在分析问题", "正在检索资料", "正在整理证据", "正在生成答案",
    ]
    assert events[-1] == ("answer", mock_result)


def test_ask_stream_returns_safe_error_event():
    with patch("src.api.routes.builder.answer", side_effect=RuntimeError("secret")):
        response = client.post("/api/ask/stream", json={"question": "测试问题"})

    assert response.status_code == 200
    assert "event: error" in response.text
    assert "处理失败，请稍后重试" in response.text
    assert "secret" not in response.text


def test_ask_stream_rejects_empty_question():
    response = client.post("/api/ask/stream", json={"question": "  "})

    assert response.status_code == 400
