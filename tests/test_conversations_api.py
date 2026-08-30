import json
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.auth import Identity, get_current_identity
from src.database import Database, get_database
from src.conversations import ConversationStore


def _identity(subject: str, role: str = "member") -> Identity:
    return Identity(
        subject=subject,
        username=subject,
        display_name=f"用户 {subject}",
        email=None,
        roles=frozenset({role}),
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

    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "maintainer-2",
        "knowledge_maintainer",
    )
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
        "evidence": [{
            "source_title": "第一份资料",
            "section": "第一节",
            "text": "第一条原文证据",
            "source_url": "",
        }],
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
        {
            "role": "assistant",
            "content": "第一条回答",
            "evidence": first_answer["evidence"],
        },
    ]


def test_long_history_is_summarized_while_original_messages_remain(
    conversation_client,
    monkeypatch,
):
    monkeypatch.setenv("CONTEXT_RECENT_HISTORY_TOKENS", "80")
    conversation_id = conversation_client.post("/api/conversations").json()["id"]
    for index in range(1, 4):
        _complete_question(
            conversation_client,
            conversation_id,
            f"request-{index}",
            f"第{index}轮问题-" + "监管制度" * 12,
        )

    answer = {
        "answer": "第四轮回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 1,
    }
    with patch("src.api.routes.builder.answer", return_value=answer) as mock_answer:
        response = conversation_client.post("/api/ask/stream", json={
            "conversation_id": conversation_id,
            "request_id": "request-4",
            "question": "第四轮问题",
        })

    assert response.status_code == 200
    model_history = mock_answer.call_args.kwargs["history"]
    assert model_history[0]["role"] == "system"
    assert model_history[0]["content"].startswith("【历史对话摘要】")
    recent_history = model_history[1:]
    assert any("第3轮问题" in item["content"] for item in recent_history)
    assert all("第1轮问题" not in item["content"] for item in recent_history)

    restored = conversation_client.get(
        f"/api/conversations/{conversation_id}"
    ).json()
    assert len(restored["messages"]) == 8
    assert any("第1轮问题" in item["content"] for item in restored["messages"])
    database = app.dependency_overrides[get_database]()
    summary, summarized_count = ConversationStore(database).context_state(
        UUID(conversation_id)
    )
    assert summary.startswith("【历史对话摘要】")
    assert summarized_count > 0


def test_context_never_includes_another_conversation(
    conversation_client,
    monkeypatch,
):
    monkeypatch.setenv("CONTEXT_RECENT_HISTORY_TOKENS", "80")
    owned_id = conversation_client.post("/api/conversations").json()["id"]
    app.dependency_overrides[get_current_identity] = lambda: _identity("member-2")
    other_id = conversation_client.post("/api/conversations").json()["id"]
    for index in range(3):
        _complete_question(
            conversation_client,
            other_id,
            f"other-{index}",
            f"OTHER-{index}-" + "机密" * 16,
        )
    app.dependency_overrides[get_current_identity] = lambda: _identity("member-1")
    for index in range(3):
        _complete_question(
            conversation_client,
            owned_id,
            f"owned-{index}",
            f"OWNED-{index}-" + "监管" * 16,
        )

    answer = {
        "answer": "回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 1,
    }
    with patch("src.api.routes.builder.answer", return_value=answer) as mock_answer:
        response = conversation_client.post("/api/ask/stream", json={
            "conversation_id": owned_id,
            "request_id": "owned-final",
            "question": "继续问",
        })

    assert response.status_code == 200
    model_history = mock_answer.call_args.kwargs["history"]
    assert "OWNED-" in json.dumps(model_history, ensure_ascii=False)
    assert "OTHER-" not in json.dumps(model_history, ensure_ascii=False)


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


def _complete_question(client, conversation_id, request_id, question):
    answer = {
        "answer": f"{question}的回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 1,
    }
    with patch("src.api.routes.builder.answer", return_value=answer):
        response = client.post("/api/ask/stream", json={
            "conversation_id": conversation_id,
            "request_id": request_id,
            "question": question,
        })
    assert response.status_code == 200


def test_member_lists_searches_and_pages_only_their_titled_conversations(
    conversation_client,
):
    first_id = conversation_client.post("/api/conversations").json()["id"]
    _complete_question(conversation_client, first_id, "first", "资本充足率要求")
    second_id = conversation_client.post("/api/conversations").json()["id"]
    _complete_question(conversation_client, second_id, "second", "不良贷款分类标准")

    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "maintainer-2",
        "knowledge_maintainer",
    )
    other_id = conversation_client.post("/api/conversations").json()["id"]
    _complete_question(conversation_client, other_id, "other", "不应看见的对话")
    app.dependency_overrides[get_current_identity] = lambda: _identity("member-1")

    first_page = conversation_client.get("/api/conversations", params={"limit": 1})
    assert first_page.status_code == 200
    assert [(item["id"], item["title"]) for item in first_page.json()["items"]] == [
        (second_id, "不良贷款分类标准"),
    ]
    assert first_page.json()["next_cursor"]

    second_page = conversation_client.get("/api/conversations", params={
        "limit": 1,
        "cursor": first_page.json()["next_cursor"],
    })
    assert [(item["id"], item["title"]) for item in second_page.json()["items"]] == [
        (first_id, "资本充足率要求"),
    ]
    assert second_page.json()["next_cursor"] is None

    searched = conversation_client.get("/api/conversations", params={
        "search": "贷款",
    })
    assert [item["id"] for item in searched.json()["items"]] == [second_id]


def test_member_renames_and_logically_deletes_only_their_conversation(
    conversation_client,
):
    conversation_id = conversation_client.post("/api/conversations").json()["id"]
    _complete_question(conversation_client, conversation_id, "owned", "原始标题")

    app.dependency_overrides[get_current_identity] = lambda: _identity("member-2")
    assert conversation_client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "越权修改"},
    ).status_code == 404
    assert conversation_client.delete(
        f"/api/conversations/{conversation_id}"
    ).status_code == 404

    app.dependency_overrides[get_current_identity] = lambda: _identity("member-1")
    renamed = conversation_client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "资本管理重点"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "资本管理重点"

    deleted = conversation_client.delete(f"/api/conversations/{conversation_id}")
    assert deleted.status_code == 204
    assert conversation_client.get(
        f"/api/conversations/{conversation_id}"
    ).status_code == 404
    assert conversation_client.get("/api/conversations").json()["items"] == []
