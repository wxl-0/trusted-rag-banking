from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from src.api.routes import router

app = FastAPI(title="可信 RAG 银行业监管问答系统")
app.include_router(router, prefix="/api")

static_dir = Path("src/frontend/dist")
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(static_dir / "index.html"))
