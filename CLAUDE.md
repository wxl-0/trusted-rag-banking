# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

面向银行业监管制度与统计报表的可信 RAG（检索增强生成）问答系统。参赛项目：第五届中国研究生金融科技创新大赛·南京银行赛题。系统解析 Word/PDF/Excel 监管文件，将其索引至 Qdrant 向量集合，执行混合检索，并生成强制附带证据引用的有据答案。

## 常用命令

### 环境初始化（首次·本地开发）
```bash
uv sync --frozen
cp .env.example .env           # 填入 OPENAI_API_KEY 等
docker compose up qdrant -d   # 仅启动 Qdrant，监听 localhost:6333
```

### 构建知识库
```bash
# 1. 自动分类 manifest（首次或有新文件时）
uv run --frozen python scripts/classify_manifest.py        # 写入 parse_profile 字段
uv run --frozen python scripts/classify_manifest.py --dry-run  # 只打印统计，不写入

# 2. 解析原始文件 → JSONL chunks（需要 data/raw/ 下有原始文件）
uv run --frozen python scripts/ingest.py

# 3. 向量入库 + 构建 BM25（需要 Qdrant 已启动）
uv run --frozen python scripts/build_index.py
```

`build_index.py` 支持断点续传：自动检测 Qdrant `points_count`，从已有进度继续索引。中断后重新运行即可。若 chunk 内容有变更（重新切块后），需先清空集合再重建：

```bash
uv run --frozen python -c "from qdrant_client import QdrantClient; c=QdrantClient('localhost',port=6333); c.delete_collection('regulations'); c.delete_collection('tables')"
uv run --frozen python scripts/build_index.py
```

### 启动服务（本地开发）
```bash
uv run --frozen python -m uvicorn src.api.main:app --reload   # 后端 http://localhost:8000
cd src/frontend && npm run dev      # 前端开发服务器 http://localhost:5173
cd src/frontend && npm run build    # 构建前端产物至 src/frontend/dist/
```

### Docker 全栈部署
```bash
docker compose up -d              # 启动 qdrant + backend + frontend
# 前端：http://localhost  后端：http://localhost:8000  Qdrant：localhost:6333
```

`backend` 容器启动时（`entrypoint.sh`）会先运行 `scripts/build_index.py` 再启动 API 服务，因此容器镜像里已包含 `data/chunks/` 产物。容器通过 volume 挂载宿主机的 HuggingFace 模型缓存（`HF_HOME` 环境变量指定的目录），无需重复下载。

### 测试与评测
```bash
uv run --frozen python -m pytest tests/ -v                                  # 全部测试
uv run --frozen python -m pytest tests/test_parser.py -v                    # 单个测试文件
uv run --frozen python -m pytest tests/test_api.py::test_health -v          # 单个测试用例
uv run --frozen python scripts/run_eval.py                                  # 端到端评测 → data/eval/eval_report.json
uv run --frozen python scripts/run_eval.py --ids Q035,Q068 --run-name smoke # 指定题号 → data/eval/runs/smoke/
```

`run_eval.py` 支持断点续传：使用 `--run-name` 时，每题结果与报告隔离写入 `data/eval/runs/<run-name>/`（已 gitignore）；不指定时继续使用原有路径。评测模式要求模型返回结构化 `choice` 并使用确定性规则判分；无法判断时标记 `unparseable`，不调用 LLM Judge。单题异常不会中断整轮。脚本内置 `HF_HUB_OFFLINE=1`，本地模型离线加载，不受代理影响。

### 真实数据解析检查
```bash
uv run --frozen python scripts/check_chunk_quality.py --suffix .xls --limit-files 2 --sample-chunks 2
uv run --frozen python scripts/check_chunk_quality.py --suffix .doc --limit-files 2 --sample-chunks 2
uv run --frozen python scripts/check_chunk_quality.py --suffix .pdf --limit-files 2 --sample-chunks 2
```

### `.doc` 转 `.docx`
```bash
uv run --frozen python scripts/convert_doc_with_libreoffice.py --soffice "C:\Program Files\LibreOffice\program\soffice.exe" --force --timeout-seconds 60
```

转换产物写入 `data/converted/docx/`，该目录不提交到 Git。

## 系统架构

五层流水线——数据严格单向流动：

```
Parser → Indexer → Retriever → Generator → API/Frontend
```

**各层说明：**

- **`src/parser/`** — 将原始文档转换为 `Chunk` 对象（见 `base.py`）。四个解析器：`WordParser`（.doc/.docx，含表格提取，合并单元格去重）、`PdfParser`（按字号判断标题切分段落）、`ExcelParser`（双轮提取：数值单元格 + 非数值文本单元格如脚注/指标定义，支持 .xls 和 .xlsx）、`PdfTableParser`（用 pdfplumber 提取 PDF 表格）。`chunk_processor.py` 提供按 profile 的后处理管道（子条款切分、超长切分、上下文增强）。输出写入 `data/chunks/`（JSONL 格式）。

- **`src/indexer/`** — 两个并行子系统：`QdrantIndex` 对两个命名集合（`regulations` 存条款 chunk，`tables` 存表格行 chunk）执行向量检索；`BM25Index` 对全量 chunk 做关键词检索，持久化至 `data/bm25_index.pkl`。`Embedder` 使用本地 `BAAI/bge-large-zh-v1.5`（1024 维，sentence-transformers 推理）。

- **`src/retriever/`** — `QueryRouter` 仅在调用方未提供 `query_type` 时调用 LLM 分类；正常 `AnswerBuilder` 流程由前置问题分析直接提供类型。主入口 `HybridRetriever.retrieve()`：明确来源且不超过 20 个 chunk 时可返回全量；否则标题精确命中时限定来源，近似命中时保留全库候选并追加标题候选，再经 BM25、向量检索、RRF 和 `CrossEncoder` 精排。制度类结果会补充同章节或同父块上下文，并记录各阶段诊断。

- **`src/generator/`** — `QueryDecomposer` 先用确定性规则判断类型并拆分表格双指标、选项比较、多事实陈述和选项中的明确文件引用，只有无法明确判断时才调用 LLM，失败回退 `hybrid`。`AnswerBuilder.answer()` 使用 `supported | not_supported | missing` 三态覆盖检查，可合并相邻上下文，且仅对 `missing` 补搜一次，再轮询合并、去重并生成答案。正式 LLM 输出仍包含 `answer`、`confidence`、`evidence[]`、`refuse_reason`；响应为空或调用异常时自动重试 3 次（指数退避）。

- **`src/api/`** — FastAPI 应用。三个路由：`POST /api/ask`（支持 `history` 字段实现多轮对话）、`POST /api/ingest`、`GET /api/health`。生产模式下挂载 `src/frontend/dist/` 静态文件。Docker 部署时由 nginx 反向代理 `/api/` 到 backend 容器。

- **`src/frontend/`** — React 18 + Vite，无 UI 框架（纯 CSS）。开发时 Vite 将 `/api/*` 代理至 `localhost:8000`。组件：`ChatInput`、`MessageList`（含空状态）、`AnswerCard`（用户消息气泡 + 助手回答卡片）、`EvidencePanel`（可折叠证据引用）。前端维护 messages 数组，每次请求携带 history 实现多轮上下文。

## Parse Profile 路由

`data/manifest.json` 每条记录可包含 `parse_profile` 字段，由 `scripts/classify_manifest.py` 自动分类：

| profile | 适用场景 | 解析策略 |
|---------|---------|---------|
| `regulation` | 监管制度文件（Word/PDF） | 子条款切分 + 600 字上限 |
| `report` | 年报/报告类 PDF | 不切子条款 + 800 字上限 + 英文标点 |
| `data` | 统计数据 Excel | ExcelParser 单元格级 |
| `pdf_table` | 统计 PDF | PdfTableParser（pdfplumber） |
| `skip` | 计算模板/签章页等无用文件 | 跳过不解析 |

`scripts/ingest.py` 根据 profile 路由到对应解析器和后处理策略。

`scripts/classify_manifest.py` 不会覆盖已有 `parse_profile` 的条目。个别文件有硬编码特例（NFRA-010 → data，NFRA-361 → regulation，NFRA-449 → skip）。

## 核心数据契约

**Chunk 结构**（定义于 `src/parser/base.py`）：所有解析器均输出 `Chunk` dataclass 实例。表格证据可包含 `table_name`、`indicator`、`period`、`unit`、`row_index`、`cell_ref`、`row_label`、`column_header`、`raw_value`；PDF/段落证据可包含 `page_no` 与 `section_path`。`parent_chunk_id` 用于子条款追溯父块。`to_dict()` 会自动忽略值为 `None` 的字段。

**`retrieve()` 签名**（`src/retriever/hybrid_retriever.py`）：

```python
def retrieve(query: str, query_type: str = None, filters: dict = None,
             top_k: int = 5, title_hint: str = None,
             full_source: bool = False) -> list[dict]
```

**`/api/ask` 请求**：`question`（必填）、`filters`（可选）、`history`（可选，`[{role, content}]` 数组）。

**`/api/ask` 响应**：固定返回 `answer`、`confidence`（`high/medium/low`）、`evidence[]`（含 `source_title`、`section`、`text`、`source_url`）、`refuse_reason`（null 或字符串）、`latency_ms`。

## 环境变量（`.env`）

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | 回答生成及选择题评测必填 |
| `OPENAI_BASE_URL` | API 基础地址（可替换为兼容代理） |
| `EMBED_MODEL` | 向量模型（默认 `BAAI/bge-large-zh-v1.5`，本地推理） |
| `LLM_MODEL` | 对话模型（默认 `gpt-4o-mini`） |
| `QDRANT_HOST/PORT` | Qdrant 连接地址（默认 `localhost:6333`） |
| `RERANKER_MODEL` | HuggingFace 交叉编码器（默认 `BAAI/bge-reranker-base`） |
| `HF_HOME` | HuggingFace 模型缓存目录（开发者需自行设置，容器内自动挂载） |
| `HF_HUB_OFFLINE` | 设为 `1` 时只使用本地模型缓存，避免启动时联网检查 |

## 分支策略

`main` 是唯一最新基线、默认开发分支和当前可演示版本，不再使用 `dev` 作为集成分支。日常修改直接在最新 `main` 上开发和提交；提交前必须选择性暂存并完成相应验证。只有用户或维护者明确要求隔离开发或代码评审时，才临时创建功能分支并使用 PR。

## 当前知识库规模

- 总 chunk 数：38,287（clause 8,927 + table 29,360）
- 覆盖文档：481 / 500（19 个 skip）
- 平均 chunk 长度：129 字
- 评测基线：首轮 300 题准确率 41%（拒答率 50% 为主要失分），报告见 `data/eval/eval_report.json`；生成层健壮性优化（重试/拒答校准/top_k=8）后的复测待跑
- 零碎片（<20字）
- 已知问题：`clause_chunks.jsonl` 中存在 343 条重复 `chunk_id`（源于子条款/超长切分命名规则在个别边界情况下产生冲突），尚未修复

## 入库 Manifest

`data/manifest.json` 驱动 `scripts/ingest.py`，当前包含 500 条文件记录。每条记录包含 `doc_id`、`title`、`issuer`、`doc_no`、`publish_date`、`source_url`、`local_path`、`parse_profile`。脚本按 `parse_profile`（优先）和后缀名路由解析器。`data/raw/` 与 `data/converted/` 目录不提交到 Git。
