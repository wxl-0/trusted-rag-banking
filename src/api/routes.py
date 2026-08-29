import asyncio
import base64
import json
import logging
import subprocess
from datetime import datetime
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from urllib.parse import quote
from uuid import UUID, uuid4

from src.api.models import (
    AskRequest,
    AskResponse,
    ConversationResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    IdentityResponse,
    IngestRequest,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentSummaryResponse,
    KnowledgeDocumentUploadResponse,
    RenameConversationRequest,
)
from src.auth import Identity, get_current_identity, require_knowledge_maintainer
from src.conversations import Conversation, ConversationMessage, ConversationStore
from src.context_control import prepare_conversation_history
from src.database import Database, get_database
from src.document_uploads import (
    DocumentUploadService,
    UploadRejected,
    UploadUnavailable,
    get_ingestion_queue,
    get_object_store,
)
from src.generator.answer_builder import AnswerBuilder
from src.knowledge_documents import KnowledgeDocumentStore
from src.readiness import ReadinessChecker, get_readiness_checker

router = APIRouter()
builder = AnswerBuilder()
logger = logging.getLogger(__name__)

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
        title=conversation.title,
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


@router.get(
    "/knowledge-documents/summary",
    response_model=KnowledgeDocumentSummaryResponse,
)
def knowledge_document_summary(
    _identity: Identity = Depends(require_knowledge_maintainer),
    database: Database = Depends(get_database),
):
    return KnowledgeDocumentStore(database).summary()


def _encode_document_cursor(item: dict, offset: int) -> str:
    value = f"{item['updated_at'].isoformat()}|{item['id']}|{offset}"
    return base64.urlsafe_b64encode(value.encode()).decode()


def _decode_document_cursor(
    cursor: str | None,
) -> tuple[tuple[datetime, UUID] | None, int]:
    if not cursor:
        return None, 0
    try:
        timestamp, document_id, offset = base64.urlsafe_b64decode(
            cursor.encode()
        ).decode().rsplit("|", 2)
        return (datetime.fromisoformat(timestamp), UUID(document_id)), int(offset)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="cursor 无效")


@router.get(
    "/knowledge-documents",
    response_model=KnowledgeDocumentListResponse,
)
def list_knowledge_documents(
    search: str | None = None,
    status: str | None = Query(default=None, pattern="^(succeeded|in_progress|failed)$"),
    cursor: str | None = None,
    page: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    _identity: Identity = Depends(require_knowledge_maintainer),
    database: Database = Depends(get_database),
):
    if page is not None and cursor is not None:
        raise HTTPException(status_code=400, detail="page 与 cursor 不能同时使用")
    before, cursor_offset = _decode_document_cursor(cursor)
    offset = (page - 1) * limit if page is not None else cursor_offset
    store = KnowledgeDocumentStore(database)
    documents = store.list(
        search=search.strip() if search and search.strip() else None,
        status=status,
        before=before,
        limit=limit if page is not None else limit + 1,
        offset=offset if page is not None else 0,
    )
    has_more = page is None and len(documents) > limit
    items = documents[:limit]
    for index, item in enumerate(items, offset + 1):
        item["sequence"] = index
    return {
        "items": items,
        "total": store.count(
            search=search.strip() if search and search.strip() else None,
            status=status,
        ),
        "page": page or (offset // limit + 1),
        "page_size": limit,
        "next_cursor": (
            _encode_document_cursor(items[-1], offset + len(items))
            if has_more else None
        ),
    }


@router.get(
    "/knowledge-documents/{document_id}",
    response_model=KnowledgeDocumentDetailResponse,
)
def get_knowledge_document(
    document_id: UUID,
    _identity: Identity = Depends(require_knowledge_maintainer),
    database: Database = Depends(get_database),
):
    document = KnowledgeDocumentStore(database).get(document_id)
    if document is not None:
        return document
    raise HTTPException(
        status_code=404,
        detail={
            "code": "KNOWLEDGE_DOCUMENT_NOT_FOUND",
            "message": "知识文档不存在",
        },
    )


@router.get("/knowledge-documents/{document_id}/download")
def download_knowledge_document(
    document_id: UUID,
    _identity: Identity = Depends(require_knowledge_maintainer),
    database: Database = Depends(get_database),
    object_store=Depends(get_object_store),
):
    download = KnowledgeDocumentStore(database).get_download(document_id)
    if download is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "KNOWLEDGE_DOCUMENT_NOT_FOUND",
                "message": "知识文档不存在",
            },
        )
    if not download["object_key"]:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "KNOWLEDGE_DOCUMENT_ORIGINAL_NOT_FOUND",
                "message": "知识文档原件不存在",
            },
        )
    try:
        source = object_store.open_download(download["object_key"])
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "KNOWLEDGE_DOCUMENT_ORIGINAL_NOT_FOUND",
                "message": "知识文档原件不存在",
            },
        )
    except Exception:
        logger.exception("Unable to open original for document %s", document_id)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "KNOWLEDGE_DOCUMENT_DOWNLOAD_UNAVAILABLE",
                "message": "知识文档暂时无法下载，请稍后重试",
            },
        )

    def stream_original():
        try:
            while chunk := source.read(1024 * 1024):
                yield chunk
        finally:
            source.close()
            release = getattr(source, "release_conn", None)
            if release is not None:
                release()

    filename = quote(download["original_filename"], safe="")
    return StreamingResponse(
        stream_original(),
        media_type=download["content_type"] or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
            "Content-Length": str(download["size_bytes"]),
        },
    )


@router.delete("/knowledge-documents/{document_id}", status_code=204)
def withdraw_knowledge_document(
    document_id: UUID,
    x_request_id: str | None = Header(
        default=None,
        alias="X-Request-ID",
        max_length=128,
    ),
    identity: Identity = Depends(require_knowledge_maintainer),
    database: Database = Depends(get_database),
):
    result = KnowledgeDocumentStore(database).withdraw(
        document_id,
        actor_subject=identity.subject,
        request_id=x_request_id or str(uuid4()),
    )
    if result == "not_found":
        raise HTTPException(
            status_code=404,
            detail={
                "code": "KNOWLEDGE_DOCUMENT_NOT_FOUND",
                "message": "知识文档不存在",
            },
        )
    return Response(status_code=204)


@router.post(
    "/knowledge-documents",
    response_model=KnowledgeDocumentUploadResponse,
    status_code=202,
)
async def upload_knowledge_document(
    file: list[UploadFile] = File(...),
    identity: Identity = Depends(require_knowledge_maintainer),
    database: Database = Depends(get_database),
    object_store=Depends(get_object_store),
    ingestion_queue=Depends(get_ingestion_queue),
):
    if len(file) != 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UPLOAD_FILE_COUNT",
                "message": "每次只能上传一个知识文档",
            },
        )
    try:
        return await DocumentUploadService(
            database,
            object_store,
            ingestion_queue,
        ).accept(file[0], identity)
    except UploadRejected as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": exc.code, "message": exc.message},
        )
    except UploadUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "UPLOAD_UNAVAILABLE", "message": str(exc)},
        )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    conversation = ConversationStore(database).create(identity.subject)
    return _conversation_response(conversation)


def _encode_cursor(conversation: Conversation) -> str:
    value = f"{conversation.updated_at.isoformat()}|{conversation.id}"
    return base64.urlsafe_b64encode(value.encode()).decode()


def _decode_cursor(cursor: str | None) -> tuple[datetime, UUID] | None:
    if not cursor:
        return None
    try:
        timestamp, conversation_id = base64.urlsafe_b64decode(
            cursor.encode()
        ).decode().rsplit("|", 1)
        return datetime.fromisoformat(timestamp), UUID(conversation_id)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="cursor 无效")


@router.get("/conversations", response_model=ConversationListResponse)
def list_conversations(
    search: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    conversations = ConversationStore(database).list_owned(
        identity.subject,
        search=search.strip() if search and search.strip() else None,
        before=_decode_cursor(cursor),
        limit=limit + 1,
    )
    has_more = len(conversations) > limit
    items = conversations[:limit]
    return {
        "items": items,
        "next_cursor": _encode_cursor(items[-1]) if has_more else None,
    }


@router.patch(
    "/conversations/{conversation_id}",
    response_model=ConversationSummaryResponse,
)
def rename_conversation(
    conversation_id: UUID,
    request: RenameConversationRequest,
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    conversation = ConversationStore(database).rename_owned(
        conversation_id,
        identity.subject,
        request.title,
    )
    if conversation is None:
        raise _conversation_not_found()
    return conversation


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(
    conversation_id: UUID,
    identity: Identity = Depends(get_current_identity),
    database: Database = Depends(get_database),
):
    deleted = ConversationStore(database).delete_owned(
        conversation_id,
        identity.subject,
    )
    if not deleted:
        raise _conversation_not_found()
    return Response(status_code=204)


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
        history = prepare_conversation_history(
            store,
            req.conversation_id,
            req.request_id,
        )
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
def ready(checker: ReadinessChecker = Depends(get_readiness_checker)):
    checks = checker.check()
    status = (
        "ready"
        if all(value == "available" for value in checks.values())
        else "not_ready"
    )
    content = {"status": status, "checks": checks}
    if status == "not_ready":
        return JSONResponse(status_code=503, content=content)
    return content


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
