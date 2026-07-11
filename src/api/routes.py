import subprocess
from fastapi import APIRouter, HTTPException
from src.api.models import AskRequest, AskResponse, IngestRequest
from src.generator.answer_builder import AnswerBuilder

router = APIRouter()
builder = AnswerBuilder()


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
    result = builder.answer(req.question, filters=req.filters, history=history)
    return AskResponse(**result)


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
