import asyncio
import json
import subprocess
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from src.api.models import AskRequest, AskResponse, IngestRequest
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


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    result = builder.answer(req.question, filters=req.filters, history=history)
    return AskResponse(**result)


@router.post("/ask/stream")
async def ask_stream(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
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
