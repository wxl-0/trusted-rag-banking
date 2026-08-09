# AGENTS.md

本文件为 Codex (Codex.ai/code) 在此代码仓库中工作时提供指导。

## 行为准则

偏向「谨慎」而不是「快」。琐碎的小任务可以灵活处理。

### 1. 想清楚再写

- 把假设明确说出来，不确定就问。
- 有多种理解时，都摆出来，不要自己悄悄选一个。
- 有更简单的做法就直说，该反对的时候反对。
- 哪里不清楚就停下来，说清楚卡在哪，然后问。

### 2. 简单优先

- 不加没要求的功能。
- 不给一次性的任务搭通用框架。
- 不加没要求的「灵活性」或「可配置」。
- 不为不可能发生的情况提前操心。
- 交付明显比需要的多时，砍到刚好够用再交。
- 自检：一个资深的人会不会觉得这过度复杂了？会的话就简化。

### 3. 外科手术式改动

- 不去「改进」没让你碰的内容或格式。
- 不翻新没坏的东西，跟着原本的风格走。
- 看到无关的原有多余内容，提一句就行，不要删。
- 只收拾这次改动产生的多余东西，原有内容不让删就不删。
- 每一处改动都要能直接追溯到需求。

### 4. 目标驱动执行

- 先定清楚「做到什么算成功」，再对着标准执行到达标。
- 多步任务先给一个简短计划，每步对应一个验证点。
- 成功标准要足够具体，能自己对答案；标准太虚（比如「弄好就行」）就停下来问。

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
docker compose up -d                # 启动 qdrant + backend + frontend
# 前端：http://localhost  后端：http://localhost:8000  Qdrant：localhost:6333
```

`backend` 容器启动时会先运行 `scripts/build_index.py`，再启动 API 服务。容器通过 volume 挂载 `HF_HOME` 指定的宿主机 HuggingFace 模型缓存，避免重复下载模型。

### 测试与评测

```bash
uv run --frozen python -m pytest tests/ -v                                  # 全部测试
uv run --frozen python -m pytest tests/test_parser.py -v                    # 单个测试文件
uv run --frozen python -m pytest tests/test_api.py::test_health -v          # 单个测试用例
uv run --frozen python scripts/run_eval.py                                  # 端到端评测 → data/eval/eval_report.json
```

`run_eval.py` 支持断点续传：每题结果实时写入 `data/eval/eval_progress.jsonl`（已 gitignore），中断后重跑自动跳过已完成题、重试出错题；从头重跑需先删除该文件。单题异常不会中断整轮。脚本内置 `HF_HUB_OFFLINE=1`，本地模型离线加载，不受代理影响。

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

五层流水线，数据严格单向流动：

```text
Parser → Indexer → Retriever → Generator → API/Frontend
```

## 各层说明

- **`src/parser/`**：将原始文档转换为 `Chunk` 对象（见 `base.py`）。四个解析器：`WordParser`（`.doc/.docx`，含表格提取和合并单元格去重）、`PdfParser`（按字号判断标题切分段落）、`ExcelParser`（双轮提取：数值单元格 + 非数值文本单元格如脚注/指标定义，支持 `.xls/.xlsx`）、`PdfTableParser`（用 pdfplumber 提取 PDF 表格）。`chunk_processor.py` 提供按 profile 的后处理管道（子条款切分、超长切分、上下文增强）。输出写入 `data/chunks/`（JSONL 格式）。
- **`src/indexer/`**：两个并行子系统：`QdrantIndex` 对两个命名集合（`regulations` 存条款 chunk，`tables` 存表格行 chunk）执行向量检索；`BM25Index` 对全量 chunk 做关键词检索，持久化至 `data/bm25_index.pkl`。`Embedder` 使用本地 `BAAI/bge-large-zh-v1.5`（1024 维，sentence-transformers 推理）。
- **`src/retriever/`**：`QueryRouter` 单次调用 LLM，将查询分类为 `regulation | table | hybrid | out_of_scope`（`out_of_scope` 仅限与监管制度/行业统计完全无关的问题；调用失败或返回空时默认 `hybrid`）。主入口 `HybridRetriever.retrieve()`：BM25 + 向量检索 → RRF（倒数排名融合）合并 → `CrossEncoder`（`BAAI/bge-reranker-base`）精排。
- **`src/generator/`**：`QueryDecomposer` 可选地将多跳问题拆分为子问题。`AnswerBuilder.answer()` 是顶层调用：分解 → 检索（top_k=8）→ chunk 去重 → grounded-generation 系统提示 + 多轮历史调用 LLM。系统提示共 7 条规则，含拒答门槛校准（资料相关必须作答，完全无关才拒答）与比较/计算类问题的逐步推理要求。LLM 必须返回包含 `answer`、`confidence`、`evidence[]`、`refuse_reason` 的结构化 JSON。`LLMClient.chat()` 接受 `history` 参数，取最近 6 条（3 轮对话）；响应为空或调用异常时自动重试 3 次（指数退避）。
- **`src/api/`**：FastAPI 应用。主要路由为 `POST /api/ask`（支持 `history` 字段实现多轮对话）、`POST /api/ingest`、`GET /api/health`。存在前端构建产物时，后端也可在 `/` 提供页面；Docker 部署时由 nginx 反向代理 `/api/` 到 backend 容器。
- **`src/frontend/`**：React 18 + Vite，无 UI 框架（纯 CSS）。开发时 Vite 将 `/api/*` 代理至 `localhost:8000`。组件包括 `ChatInput`、`MessageList`（含空状态）、`AnswerCard`（用户消息气泡 + 助手回答卡片）、`EvidencePanel`（可折叠证据引用）。前端维护 messages 数组，每次请求携带 history 实现多轮上下文。

## Parse Profile 路由

`data/manifest.json` 每条记录可包含 `parse_profile` 字段，由 `scripts/classify_manifest.py` 自动分类：

| profile | 适用场景 | 解析策略 |
|---|---|---|
| `regulation` | 监管制度文件（Word/PDF） | 子条款切分 + 600 字上限 |
| `report` | 年报/报告类 PDF | 不切子条款 + 800 字上限 + 英文标点 |
| `data` | 统计数据 Excel | ExcelParser 单元格级 |
| `pdf_table` | 统计 PDF | PdfTableParser（pdfplumber） |
| `skip` | 计算模板/签章页等无用文件 | 跳过不解析 |

`scripts/ingest.py` 根据 profile 路由到对应解析器和后处理策略。`scripts/classify_manifest.py` 不会覆盖已有 `parse_profile` 的条目。个别文件有硬编码特例（NFRA-010 → data，NFRA-361 → regulation，NFRA-449 → skip）。

## 核心数据契约

**Chunk 结构**（定义于 `src/parser/base.py`）：所有解析器均输出 `Chunk` dataclass 实例。表格证据可包含 `table_name`、`indicator`、`period`、`unit`、`row_index`、`cell_ref`、`row_label`、`column_header`、`raw_value`；PDF/段落证据可包含 `page_no` 与 `section_path`；`parent_chunk_id` 用于子条款追溯父块。`to_dict()` 会自动忽略值为 `None` 的字段。

**`retrieve()` 签名**（`src/retriever/hybrid_retriever.py`）：

```python
def retrieve(query: str, query_type: str = None, filters: dict = None, top_k: int = 5) -> list[dict]
```

**`/api/ask` 请求**：`question`（必填）、`filters`（可选）、`history`（可选，`[{role, content}]` 数组）。

**`/api/ask` 响应**：固定返回 `answer`、`confidence`（`high/medium/low`）、`evidence[]`（含 `source_title`、`section`、`text`、`source_url`）、`refuse_reason`（null 或字符串）、`latency_ms`。

## 已确认、待实施的接口与评测决策

- 删除 `confidence` 字段。实施时必须同步修改生成提示词、后端响应模型与接口、前端展示、测试和相关文档；在整组改动完成前，上述 `/api/ask` 响应描述仍代表当前代码现状。不要用新的主观置信度字段替代它，除非另有明确设计。
- `choice` 只属于选择题评测适配层，不进入正式前端的开放问答接口。评测模式可要求模型结构化返回 `choice`（`A/B/C/D`）和 `answer`，正式 `/api/ask` 仍返回自然语言答案与证据。
- 正式选择题判分优先使用确定性规则（选项字母、规范化数值、规范化文本）；只有无法确定时才允许可选的 LLM Judge，并必须单独标记判分方法，不能把模型判分伪装成确定性结果。

## 环境变量（`.env`）

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | LLM 调用及评测 Judge 必填 |
| `OPENAI_BASE_URL` | API 基础地址，可替换为兼容代理 |
| `EMBED_MODEL` | 本地向量模型，默认 `BAAI/bge-large-zh-v1.5` |
| `LLM_MODEL` | 对话模型，默认 `gpt-4o-mini` |
| `QDRANT_HOST/PORT` | Qdrant 连接地址，默认 `localhost:6333` |
| `RERANKER_MODEL` | HuggingFace 交叉编码器，默认 `BAAI/bge-reranker-base` |
| `HF_HOME` | HuggingFace 模型缓存目录；队友需各自设置，Docker Compose 将该目录挂载到 backend 容器 |
| `HF_HUB_OFFLINE` | 设为 `1` 时只使用本地模型缓存，避免启动时联网检查 |

## 分支策略

见 `CONTRIBUTING.md`：`main` 是唯一最新基线和当前可演示版本，不再使用 `dev` 作为集成分支。每项任务从最新 `main` 新建 `feature/xxx` 或 `hotfix/xxx` 分支，验证后通过 PR 合入 `main`；禁止直接向 `main` 推送提交。

## 当前知识库规模

- 总 chunk 数：38,287（clause 8,927 + table 29,360）
- 覆盖文档：481 / 500（19 个 `skip`）
- 平均 chunk 长度：约 130 字
- 评测基线：首轮 300 题准确率 41%（拒答率 50% 为主要失分），报告见 `data/eval/eval_report.json`；生成层健壮性优化（重试/拒答校准/top_k=8）后的复测待跑
- 当前无 `<20` 字碎片；`clause_chunks.jsonl` 仍存在重复 `chunk_id` 行，需要后续修复

## 入库 Manifest

`data/manifest.json` 驱动 `scripts/ingest.py`，当前包含 500 条文件记录，覆盖 `.doc`、`.docx`、`.pdf`、`.xls`、`.xlsx`。每条记录包含 `doc_id`、`title`、`issuer`、`doc_no`、`publish_date`、`source_url`、`local_path`、`parse_profile`。脚本按 `parse_profile`（优先）和后缀名路由解析器。`data/raw/` 与 `data/converted/` 目录不提交到 Git。
