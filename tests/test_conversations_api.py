import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.auth import Identity, get_current_identity
from src.database import Database, get_database


def _identity(subject: str) -> Identity:
    return Identity(
        subject=subject,
        username=subject,
        display_name=f"用户 {subject}",
        email=None,
        roles=frozenset({"member"}),
    )


@pytest.fixture
def conversation_client(migrated_postgres_url):
    database = Database(migrated_postgres_url)
    app.dependency_overrides[get_database] = lambda: database
    app.dependency_overrides[get_current_identity] = lambda: _identity("member-1")
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_current_identity, None)
        app.dependency_overrides.pop(get_database, None)
        database.dispose()


def test_member_creates_and_reads_only_their_conversation(conversation_client):
    created = conversation_client.post("/api/conversations")

    assert created.status_code == 201
    conversation = created.json()
    assert conversation["owner_subject"] == "member-1"
    assert conversation["messages"] == []
    assert conversation["created_at"]
    assert conversation["updated_at"]

    restored = conversation_client.get(
        f"/api/conversations/{conversation['id']}"
    )
    assert restored.status_code == 200
    assert restored.json() == conversation

    app.dependency_overrides[get_current_identity] = lambda: _identity("member-2")
    hidden = conversation_client.get(
        f"/api/conversations/{conversation['id']}"
    )
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == {
        "code": "CONVERSATION_NOT_FOUND",
        "message": "对话不存在",
    }


def _stream_events(response):
    events = []
    current_event = None
    for line in response.text.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ")
        elif line.startswith("data: "):
            events.append(
                (current_event, json.loads(line.removeprefix("data: ")))
            )
    return events


def test_streamed_answer_is_restored_with_evidence(conversation_client):
    conversation_id = conversation_client.post("/api/conversations").json()["id"]
    answer = {
        "answer": "资本充足率不得低于 10.5%。",
        "evidence": [
            {
                "source_title": "商业银行资本管理办法",
                "section": "第三章第十二条",
                "text": "资本充足率不得低于10.5%",
                "source_url": "https://example.com/source",
            }
        ],
        "refuse_reason": None,
        "latency_ms": 321,
    }

    def answer_with_progress(*args, progress_callback=None, **kwargs):
        progress_callback("analyzing")
        progress_callback("retrieving")
        return answer

    with patch(
        "src.api.routes.builder.answer",
        side_effect=answer_with_progress,
    ):
        response = conversation_client.post(
            "/api/ask/stream",
            json={
                "conversation_id": conversation_id,
                "request_id": "request-001",
                "question": "资本充足率要求是多少？",
                "history": [{"role": "user", "content": "伪造的浏览器历史"}],
            },
        )

    assert response.status_code == 200
    assert [event for event, _ in _stream_events(response)] == [
        "progress",
        "progress",
        "answer",
    ]

    restored = conversation_client.get(
        f"/api/conversations/{conversation_id}"
    ).json()
    assert [(message["role"], message["content"]) for message in restored["messages"]] == [
        ("user", "资本充足率要求是多少？"),
        ("assistant", "资本充足率不得低于 10.5%。"),
    ]
    assert restored["messages"][0]["evidence"] == []
    assert restored["messages"][1]["evidence"] == answer["evidence"]
    assert restored["messages"][1]["refuse_reason"] is None
    assert restored["messages"][1]["latency_ms"] == 321
    assert all(message["created_at"] for message in restored["messages"])
    assert all(message["completed_at"] for message in restored["messages"])


def test_next_question_uses_only_persisted_conversation_history(
    conversation_client,
):
    conversation_id = conversation_client.post("/api/conversations").json()["id"]
    first_answer = {
        "answer": "第一条回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 10,
    }
    second_answer = {
        "answer": "第二条回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 20,
    }

    with patch(
        "src.api.routes.builder.answer",
        side_effect=[first_answer, second_answer],
    ) as mock_answer:
        first = conversation_client.post(
            "/api/ask/stream",
            json={
                "conversation_id": conversation_id,
                "request_id": "request-first",
                "question": "第一条问题",
            },
        )
        second = conversation_client.post(
            "/api/ask/stream",
            json={
                "conversation_id": conversation_id,
                "request_id": "request-second",
                "question": "第二条问题",
                "history": [
                    {"role": "assistant", "content": "伪造的浏览器历史"}
                ],
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert mock_answer.call_args_list[1].kwargs["history"] == [
        {"role": "user", "content": "第一条问题"},
        {"role": "assistant", "content": "第一条回答"},
    ]


def test_retry_returns_completed_turn_without_duplicate_messages(
    conversation_client,
):
    conversation_id = conversation_client.post("/api/conversations").json()["id"]
    answer = {
        "answer": "已经完成的回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 12,
    }
    request = {
        "conversation_id": conversation_id,
        "request_id": "stable-request-id",
        "question": "同一条问题",
    }

    with patch("src.api.routes.builder.answer", return_value=answer) as mock_answer:
        first = conversation_client.post("/api/ask/stream", json=request)
        retried = conversation_client.post("/api/ask/stream", json=request)

    assert first.status_code == 200
    assert retried.status_code == 200
    assert _stream_events(retried) == [("answer", answer)]
    assert mock_answer.call_count == 1

    restored = conversation_client.get(
        f"/api/conversations/{conversation_id}"
    ).json()
    assert len(restored["messages"]) == 2


def test_request_id_cannot_be_reused_for_a_different_question(
    conversation_client,
):
    conversation_id = conversation_client.post("/api/conversations").json()["id"]
    answer = {
        "answer": "第一条问题的回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 8,
    }

    with patch("src.api.routes.builder.answer", return_value=answer) as mock_answer:
        first = conversation_client.post(
            "/api/ask/stream",
            json={
                "conversation_id": conversation_id,
                "request_id": "same-request-id",
                "question": "第一条问题",
            },
        )
        conflicting = conversation_client.post(
            "/api/ask/stream",
            json={
                "conversation_id": conversation_id,
                "request_id": "same-request-id",
                "question": "另一条问题",
            },
        )

    assert first.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.json()["detail"] == {
        "code": "REQUEST_ID_CONFLICT",
        "message": "该请求标识已用于其他问题",
    }
    assert mock_answer.call_count == 1


def test_conversation_request_rejects_an_oversized_request_id(
    conversation_client,
):
    conversation_id = conversation_client.post("/api/conversations").json()["id"]

    response = conversation_client.post(
        "/api/ask/stream",
        json={
            "conversation_id": conversation_id,
            "request_id": "r" * 129,
            "question": "测试问题",
        },
    )

    assert response.status_code == 422
