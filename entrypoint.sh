#!/bin/bash
set -e

echo "[启动] 执行数据库迁移..."
uv run --frozen --no-dev alembic upgrade head

echo "[启动] 构建向量索引 + BM25..."
uv run --frozen --no-dev python scripts/build_index.py

echo "[启动] 启动 API 服务..."
exec uv run --frozen --no-dev python -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
