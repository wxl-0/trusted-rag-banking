# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在此代码仓库中工作时提供指导。

## 项目概述

面向银行业监管制度与统计报表的可信 RAG（检索增强生成）问答系统。参赛项目：第五届中国研究生金融科技创新大赛·南京银行赛题。系统解析 Word/PDF/Excel 监管文件，将其索引至 Qdrant 向量集合，执行混合检索，并生成强制附带证据引用的有据答案。

## 常用命令

### 环境初始化（首次）
```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -r requirements.txt
cp .env.example .env           # 填入 OPENAI_API_KEY 等
docker compose up -d           # 启动 Qdrant，监听 localhost:6333
```

### 构建知识库
```bash
# 1. 解析原始文件 → JSONL chunks
python scripts/ingest.py

# 2. 向量入库 + 构建 BM25
python -c "
from src.indexer.qdrant_index import QdrantIndex
idx = QdrantIndex()
idx.create_collections()
idx.index_chunks('data/chunks/clause_chunks.jsonl', 'regulations')
idx.index_chunks('data/chunks/table_chunks.jsonl', 'tables')
from src.indexer.bm25_index import BM25Index
bm25 = BM25Index()
bm25.build(['data/chunks/clause_chunks.jsonl', 'data/chunks/table_chunks.jsonl'])
"
```

### 启动服务
```bash
uvicorn src.api.main:app --reload   # 后端 http://localhost:8000
cd src/frontend && npm run dev      # 前端开发服务器 http://localhost:5173
cd src/frontend && npm run build    # 构建前端产物至 src/frontend/dist/
```

### 测试与评测
```bash
pytest tests/ -v                                  # 全部测试
pytest tests/test_parser.py -v                    # 单个测试文件
pytest tests/test_api.py::test_health -v          # 单个测试用例
python scripts/run_eval.py                        # 端到端评测 → data/eval/eval_report.json
```

## 系统架构

五层流水线——数据严格单向流动：

```
Parser → Indexer → Retriever → Generator → API/Frontend
```

**各层说明：**

- **`src/parser/`** — 将原始文档转换为 `Chunk` 对象（见 `base.py`）。三个解析器：`WordParser`（python-docx，保留 Heading 层级）、`PdfParser`（pymupdf，字体大小 ≥ 14pt 推断为标题）、`ExcelParser`（openpyxl，将每行数据序列化为自然语言文本）。输出写入 `data/chunks/`（JSONL 格式）。

- **`src/indexer/`** — 两个并行子系统：`QdrantIndex` 对两个命名集合（`regulations` 存条款 chunk，`tables` 存表格行 chunk）执行向量检索；`BM25Index` 对全量 chunk 做关键词检索，持久化至 `data/bm25_index.pkl`。`Embedder` 调用 OpenAI `text-embedding-3-small`（1536 维）。

- **`src/retriever/`** — `QueryRouter` 单次调用 LLM，将查询分类为 `regulation | table | hybrid | out_of_scope`。生成层的主入口是 `HybridRetriever.retrieve()`：依次执行 BM25 + 向量检索，用 RRF（倒数排名融合）合并结果，再用 `CrossEncoder`（`BAAI/bge-reranker-base`）精排。

- **`src/generator/`** — `QueryDecomposer` 可选地将多跳问题拆分为子问题。`AnswerBuilder.answer()` 是顶层调用：分解→检索→chunk 去重→以强约束 grounded-generation 系统提示调用 LLM。LLM 必须返回包含 `answer`、`confidence`、`evidence[]`、`refuse_reason` 的结构化 JSON。`PromptBuilder` 根据 chunk 列表组装用户消息。

- **`src/api/`** — FastAPI 应用。三个路由：`POST /api/ask`、`POST /api/ingest`、`GET /api/health`。生产模式下，`main.py` 挂载 `src/frontend/dist/` 的 React 构建产物，并在 `/` 路由提供 `index.html`。

- **`src/frontend/`** — React 18 + Vite。开发时 Vite 将 `/api/*` 代理至 `localhost:8000`。组件：`ChatInput`、`MessageList`、`AnswerCard`（显示置信度标签）、`EvidencePanel`（可折叠的来源引用）。

## 核心数据契约

**Chunk 结构**（定义于 `src/parser/base.py`）：所有解析器均输出 `Chunk` dataclass 实例。`table_name`、`indicator`、`period`、`unit`、`row_index` 字段仅在 `chunk_type="table_row"` 时存在；`to_dict()` 会自动忽略值为 `None` 的字段。

**`retrieve()` 签名**（`src/retriever/hybrid_retriever.py`）：
```python
def retrieve(query: str, query_type: str = None, filters: dict = None, top_k: int = 5) -> list[dict]
```

**`/api/ask` 响应**：固定返回 `answer`、`confidence`（`high/medium/low`）、`evidence[]`、`refuse_reason`（null 或字符串）、`latency_ms`。

## 环境变量（`.env`）

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | Embedding、LLM 调用及评测 Judge 必填 |
| `OPENAI_BASE_URL` | API 基础地址（可替换为兼容代理） |
| `EMBED_MODEL` | 向量模型（默认 `text-embedding-3-small`） |
| `LLM_MODEL` | 对话模型（默认 `gpt-4o-mini`） |
| `QDRANT_HOST/PORT` | Qdrant 连接地址（默认 `localhost:6333`） |
| `RERANKER_MODEL` | HuggingFace 交叉编码器（默认 `BAAI/bge-reranker-base`） |

## 分支策略

见 `CONTRIBUTING.md`：`main` 为保护分支（可演示版本），`dev` 为集成分支。功能分支：`feature/parser`（成员 A）、`feature/retriever`（成员 B）、`feature/generator`（成员 C）。所有代码必须通过 PR 合入 `dev`；`main` 仅由队长在里程碑节点从 `dev` 合入。禁止直接向 `main` 或 `dev` 推送提交。

## 入库 Manifest

`data/manifest.json` 驱动 `scripts/ingest.py`。每条记录包含 `doc_id`、`title`、`issuer`、`doc_no`、`publish_date`、`source_url`、`local_path`。脚本按扩展名路由：`.docx/.doc` → `WordParser`，`.pdf` → `PdfParser`，`.xlsx/.xls` → `ExcelParser`。`data/raw/` 目录已加入 `.gitignore`。
