# 可信 RAG 银行业监管问答系统

面向银行业监管制度与统计报表的检索增强生成（RAG）问答系统。
第五届中国研究生金融科技创新大赛 · 南京银行赛题

检索编排由项目自身的 Python 模块实现，未引入 LangChain/LangGraph。系统先用确定性规则拆分检索目标，也会识别选项中明确引用的其他文件；短文件直接取全量 chunk，长文件再按章节检索。证据覆盖分为 `supported | not_supported | missing`，仅对 `missing` 目标补搜一次。

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
# 指定题号并把本轮结果保存到独立目录
uv run --frozen python scripts/run_eval.py --ids Q035,Q068,Q101,Q103,Q201,Q202,Q203 --run-name diverse-baseline-v1
```
评测支持断点续传。使用 `--run-name` 时，进度和报告分别写入 `data/eval/runs/<run-name>/progress.jsonl` 与 `report.json`；不指定时继续使用原来的 `data/eval/eval_progress.jsonl` 与 `eval_report.json`。每题会记录各检索目标、标题匹配、候选数量、阶段耗时、覆盖结果和补搜次数。评测模式要求模型结构化返回 `choice`，并用确定性规则判分，不调用 LLM Judge。

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
