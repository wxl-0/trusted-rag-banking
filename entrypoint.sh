#!/bin/bash
set -e

echo "[启动] 构建向量索引 + BM25..."
python scripts/build_index.py

echo "[启动] 启动 API 服务..."
exec uvicorn src.api.main:app --host 0.0.0.0 --port 8000
