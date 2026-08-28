import asyncio
import json
import subprocess
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from uuid import UUID

from src.api.models import (
    AskRequest,
    AskResponse,
    ConversationResponse,
    IdentityResponse,
    IngestRequest,
)
from src.auth import Identity, get_current_identity
from src.conversations import Conversation, ConversationMessage, ConversationStore
from src.database import Database, get_database
from src.generator.answer_builder import AnswerBuilder

router = APIRouter()
builder = AnswerBuilder()

STAGE_MESSAGES = {
    "analyzing": "正在分析问题",
    "retrieving": "正在检索资料",
    "organizing": "正在整理证据",
    "generating": "正在生成答案",
}


def _sse_event(event: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def _message_response(message: ConversationMessage) -> dict:
    return {
        "id": message.id,
        "request_id": message.request_id,
        "role": message.role,
        "content": message.content,
        "evidence": message.evidence,
        "refuse_reason": message.refuse_reason,
        "latency_ms": message.latency_ms,
        "created_at": message.created_at,
        "completed_at": message.completed_at,
    }


def _answer_payload(message: ConversationMessage) -> dict:
    return {
        "answer": message.content,
        "evidence": message.evidence,
        "refuse_reason": message.refuse_reason,
        "latency_ms": message.latency_ms,
    }


def _conversation_response(
    conversation: Conversation,
    messages: list[ConversationMessage] | None = None,
) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        owner_subject=conversation.owner_subject,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_message_response(message) for message in (messages or [])],
    )


def _conversation_not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "CONVERSATION_NOT_FOUND",
            "message": "对话不存在",
        },
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    conversation = ConversationStore(database).create(identity.subject)
    return _conversation_response(conversation)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    conversation = ConversationStore(database).get_owned(
        conversation_id,
        identity.subject,
    )
    if conversation is None:
        raise _conversation_not_found()
    messages = ConversationStore(database).list_messages(conversation.id)
    return _conversation_response(conversation, messages)


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest, _identity: Identity = Depends(get_current_identity)):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    result = builder.answer(req.question, filters=req.filters, history=history)
    return AskResponse(**result)


@router.post("/ask/stream")
async def ask_stream(
    req: AskRequest,
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    if req.conversation_id is not None:
        store = ConversationStore(database)
        conversation = store.get_owned(req.conversation_id, identity.subject)
        if conversation is None:
            raise _conversation_not_found()
        stored_question = store.start_turn(
            req.conversation_id,
            req.request_id,
            req.question,
        )
        if stored_question != req.question:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REQUEST_ID_CONFLICT",
                    "message": "该请求标识已用于其他问题",
                },
            )
        completed_answer = store.completed_answer(
            req.conversation_id,
            req.request_id,
        )
        if completed_answer is not None:
            async def completed_stream():
                yield _sse_event("answer", _answer_payload(completed_answer))

            return StreamingResponse(
                completed_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        history = store.history_for_turn(req.conversation_id, req.request_id)
    else:
        store = None
        history = [{"role": m.role, "content": m.content} for m in (req.history or [])]

    async def event_stream():
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue()

        def enqueue(event: str, payload: dict):
            loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

        def report_progress(stage: str):
            message = STAGE_MESSAGES.get(stage)
            if message:
                enqueue("progress", {"stage": stage, "message": message})

        def run_answer():
            try:
                result = builder.answer(
                    req.question,
                    filters=req.filters,
                    history=history,
                    progress_callback=report_progress,
                )
                answer = AskResponse(**result).model_dump(mode="json")
                if store is not None:
                    persisted = store.complete_turn(
                        req.conversation_id,
                        req.request_id,
                        answer,
                    )
                    answer = _answer_payload(persisted)
                enqueue("answer", answer)
            except Exception:
                enqueue("error", {"message": "处理失败，请稍后重试"})

        worker = asyncio.create_task(asyncio.to_thread(run_answer))
        while True:
            event, payload = await queue.get()
            yield _sse_event(event, payload)
            if event in {"answer", "error"}:
                break
        await worker

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/ingest")
async def ingest(req: IngestRequest):
    result = subprocess.run(
        ["python", "scripts/ingest.py"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)
    return {"status": "ok", "output": result.stdout}


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/ready")
def ready(database: Database = Depends(get_database)):
    try:
        database.ping()
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "checks": {"postgresql": "unavailable"},
            },
        )

    return {
        "status": "ready",
        "checks": {"postgresql": "available"},
    }


@router.get("/auth/me", response_model=IdentityResponse)
def current_identity(identity: Identity = Depends(get_current_identity)):
    return IdentityResponse(
        subject=identity.subject,
        username=identity.username,
        display_name=identity.display_name,
        email=identity.email,
        business_role=identity.business_role,
        roles=sorted(identity.roles),
    )
