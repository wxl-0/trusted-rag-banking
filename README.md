# 可信 RAG 银行业监管问答系统

面向银行业监管制度与统计报表的检索增强生成（RAG）问答系统。
第五届中国研究生金融科技创新大赛 · 南京银行赛题

## 快速启动

### 1. 创建环境并安装锁定依赖
```powershell
uv sync --frozen
```

### 2. 配置环境变量
```powershell
Copy-Item .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等
```

### 3. 启动 Qdrant
```powershell
docker compose up -d qdrant
```

### 4. 构建知识库
```powershell
uv run --frozen python scripts/ingest.py        # 解析原始文件 → JSONL chunks
uv run --frozen python scripts/build_index.py   # 向量入库 + 构建 BM25（需 Qdrant 已启动，支持断点续传）
```

### 5. 启动服务
```powershell
uv run --frozen python -m uvicorn src.api.main:app --reload
```

### 6. 启动前端
```powershell
Set-Location src/frontend
npm install        # 首次运行时执行
npm run dev
```

浏览器访问 http://localhost:5173

### 7. 运行评测
```powershell
uv run --frozen python scripts/run_eval.py
```
评测支持断点续传：每题结果实时写入 `data/eval/eval_progress.jsonl`，中断后重跑自动续上；从头重跑需先删除该文件。结果输出至 `data/eval/eval_report.json`。

## 运行测试
```powershell
uv run --frozen python -m pytest tests/ -v
```

## 分工
| 成员 | 负责模块 |
|---|---|
| 成员 A | `src/parser/` + `scripts/ingest.py` |
| 成员 B | `src/indexer/` + `src/retriever/` |
| 成员 C | `src/generator/` + `src/api/` + `src/frontend/` + `scripts/run_eval.py` |
