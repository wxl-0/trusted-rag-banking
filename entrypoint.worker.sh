#!/bin/bash
set -e

echo "[启动] 执行数据库迁移..."
uv run --frozen --no-dev alembic upgrade head

echo "[启动] 启动单文档入库 Worker..."
exec uv run --frozen --no-dev python scripts/run_ingestion_worker.py
