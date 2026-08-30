#!/bin/bash
set -e

echo "[启动] 执行数据库迁移..."
uv run --frozen --no-dev alembic upgrade head

echo "[启动] 配置 Qdrant 索引..."
uv run --frozen --no-dev python -m scripts.configure_qdrant

echo "[启动] 启动单文档入库 Worker..."
exec uv run --frozen --no-dev python -m scripts.run_ingestion_worker
