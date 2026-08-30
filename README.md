# 可信 RAG 银行业监管问答系统

面向银行业监管制度与统计报表的可信检索增强生成（RAG）问答系统，参赛项目为“第五届中国研究生金融科技创新大赛·南京银行赛题”。

系统将 Word、PDF、Excel 资料解析为带来源信息的结构化 Chunk，通过 BM25、向量检索、RRF 融合与交叉编码器精排定位证据，再生成附带原文引用的答案。项目也可以替换为使用者自己的制度、合规和统计资料，重新构建专属知识库。

## 项目演示

视频演示知识库管理、监管问答、连续追问与原文证据查看流程。

https://github.com/user-attachments/assets/e1274fa6-9592-4c04-b64f-13e6ba042471

## 当前实现状态

本仓库同时包含当前可运行系统、下一阶段静态原型和已确认的企业化演进方案。三者边界如下：

| 状态 | 当前范围 |
|---|---|
| 已实现并可运行 | 文档解析、混合检索、证据回答、FastAPI REST/SSE、React 问答、Keycloak 登录与访问控制、PostgreSQL 对话历史与滚动摘要、维护者知识库管理，以及前端批量上传编排、活动文档同名拒绝、在线上传、受鉴权的原件流式下载、MinIO 版本工件、Redis 单文档 Worker、Qdrant/BM25 索引、当前版本过滤、并发安全发布、幂等重投递、过期任务恢复、候选清理、五项就绪检查和安全逻辑撤回 |
| 静态原型已完成 | 普通成员/知识库维护者角色视图、知识库管理、上传与异步入库状态；登录、账户区、问答、个人历史侧栏、维护者知识库页和上传弹窗已接入正式 React，完整原型位于 [`prototype/`](prototype/) |
| 已确认但尚未开发 | 维护者手工重试和永久物理清理 |

生成层使用 OpenAI 兼容接口，通过 `OPENAI_BASE_URL` 和 `LLM_MODEL` 配置供应商与模型，默认目标为 `deepseek-v4-flash`。服务端保留完整对话原文，模型调用则按 64K/128K/200K 分层预算选取证据、滚动摘要和最新消息，并预留 8K–16K 输出空间。

## 当前具备的能力

- **多格式解析**：支持 `.docx`、`.pdf`、`.xls`、`.xlsx`；旧版 `.doc` 需要可用的 Word 转换环境，建议预先转换为 `.docx`。
- **按资料类型切块**：区分制度文件、报告、Excel 数据和 PDF 表格，保留标题层级、页码、行列口径、单位、单元格位置等元数据。
- **混合检索与精排**：组合 BM25 关键词检索、BGE 向量检索、独立通道 RRF 融合和 CrossEncoder 精排；混合问题复用一次查询向量，多个独立检索目标默认最多 2 个并发执行，并支持按来源标题、章节和资料类型限定范围。
- **表格取数与计算**：根据指标、期间、单位和表格区块筛选结构化单元格；只有取得全部操作数后才执行确定性计算。
- **多目标问题分解**：识别跨文件、多事实、选项比较和季度计算问题；证据缺失时最多补搜一次。
- **有据回答与拒答**：模型只选择本次参考资料的证据 ID，后端从原始 Chunk 构造正式证据；未知证据 ID、无法核验的数值/日期、资料不足、超出知识库范围或缺少必要操作数时拒答或说明缺失信息。
- **个人对话历史**：服务端保存问题、完成回答、证据和时间，并按登录身份隔离；正式 React 可在原型侧栏中新建、搜索、恢复、原位重命名和逻辑删除自己的对话。
- **受控长对话**：旧消息超过近期历史预算时在 PostgreSQL 更新滚动摘要；表格短追问及“两个地区”类指代在历史证据唯一时先做规则消解，歧义场景再调用上下文化改写；原始消息仍完整保留。
- **维护者知识库**：知识库维护者可以查看成功/进行中/失败摘要，按文件名搜索、按状态筛选，以每页 10 篇的完整页码翻页，并下载列表中最新上传的私有原件；进行中和失败文档同样允许下载，已撤回文档返回 404。维护者可单批选择最多 10 个 DOC、DOCX、PDF、XLS 或 XLSX 文件（单文件最多 50 MiB、总计最多 200 MiB），前端以固定 3 个并发请求复用单文件接口，并逐文件显示已受理、校验失败或提交失败；单个失败不阻断其他文件。活动知识库中已有同名文件时后端拒绝上传，不覆盖既有文档。后台继续按单文档完成解析、版本 Chunk 保存、Qdrant/BM25 索引和成功发布。任务重复投递只推进同一版本，Worker 重启会恢复排队或租约过期任务，候选清理失败则保留旧活动版本并等待同一任务重试。维护者二次确认后可以逻辑撤回文档，使其立即退出后续检索并留下关联请求的审计记录；普通成员调用管理接口会被后端拒绝。同文档替换上传、版本浏览、维护者手工重试和永久物理清理不在本阶段范围内。
- **处理进度展示**：通过 SSE 展示“分析问题、检索资料、整理证据、生成答案”等阶段和已处理时间。
- **企业登录与问答保护**：React 使用 OIDC Authorization Code Flow with PKCE 跳转 Keycloak；FastAPI 校验令牌签名、issuer、audience、有效期与 `member` / `knowledge_maintainer` 业务角色后才允许问答。
- **可复现评测**：选择题使用确定性规则判分，记录检索目标、候选数量、阶段耗时、覆盖状态和补搜次数，不使用 LLM Judge 代替正式判分。

## 系统流程

```mermaid
flowchart LR
    A[Word / PDF / Excel] --> B[Parser]
    B --> C[结构化 Chunk]
    C --> D[Qdrant 向量索引]
    C --> E[BM25 索引]
    F[用户问题] --> G[问题分析与分解]
    G --> H[混合检索与精排]
    D --> H
    E --> H
    H --> I[证据覆盖检查]
    I --> J[答案生成或拒答]
    J --> K[API / React 前端]
```

检索编排由项目自身的 Python 模块实现，未引入 LangChain 或 LangGraph。证据覆盖状态分为 `supported | not_supported | missing`，仅对 `missing` 的检索目标补搜一次。

## 已验证结果

- 299 道非歧义正式评测题答对 291 题，准确率 97.32%；
- 制度事实类准确率 96.50%，表格题总体准确率 98.99%；
- 证据引用命中率 99.00%；
- 100 道开放式专项评测答对 90 题，关键实体错误率 4.92%，库外处理正确率 93.33%。

评测方法、汇总结果与运行边界见[技术文档](docs/技术文档.md)。比赛 Manifest、题集、逐题报告和 Bad Case 回归明细只在本地私有环境保留，不进入 Git。

## 使用自己的资料

本项目可以复用为相似的制度、合规和统计资料问答系统。网页上传会创建不可变文档版本和入库任务，后台 Worker 复用现有解析与切块规则，只有版本 Chunk、Qdrant 和 BM25 全部校验成功后才发布为当前可检索版本。原有“文件目录 + Manifest + 命令行建库”仍用于初始整库构建。

### 1. 放置资料

将资料放入 `data/raw/` 下，例如：

```text
data/raw/my_documents/
├─ 管理办法.docx
├─ 统计报告.pdf
└─ 季度数据.xlsx
```

### 2. 登记 Manifest

在 `data/manifest.json` 中为每份资料添加记录。`doc_id` 必须唯一，`local_path` 使用相对于项目根目录的路径：

```json
[
  {
    "doc_id": "CUSTOM-001",
    "title": "示例管理办法",
    "issuer": "示例机构",
    "doc_no": "",
    "publish_date": "2026-01-01",
    "source_url": "",
    "local_path": "data/raw/my_documents/示例管理办法.docx"
  }
]
```

### 3. 分类、切块并建立索引

```bash
# 为没有 parse_profile 的记录判断解析类型
uv run --frozen python scripts/classify_manifest.py --dry-run
uv run --frozen python scripts/classify_manifest.py

# 解析全部 Manifest 资料并生成 Chunk JSONL
uv run --frozen python scripts/ingest.py

# 写入 Qdrant 并构建 BM25 索引
uv run --frozen python scripts/build_index.py
```

`scripts/ingest.py` 会重新生成两套 Chunk JSONL，适用于首次建库或确认进行全量重建的场景。已有知识库的单文档更新应使用带预览、备份和回滚的 `scripts/update_documents.py`，不要直接用全量解析替代线上增量更新。

银行业之外的资料可以复用解析、索引、检索和证据链路，但通常还需要调整问题分类规则、提示词、表格口径和评测题库。

## GitHub 仓库边界

为保护比赛与企业数据，GitHub 源码不包含以下数据资产：

- 比赛原始资料 `data/raw/`；
- `.doc` 转换产物 `data/converted/`；
- 比赛 Manifest、评测题集、逐题报告与 Bad Case 回归明细；
- 完整 Chunk JSONL、BM25 索引和 Qdrant 数据；
- Hugging Face Embedding 与 Reranker 模型缓存；
- 真实 API Key。

因此，公开仓库用于审查源码、评测方法和汇总结果，并可使用自有资料重新建库；它不是克隆后无需数据即可直接问答的在线 Demo。

## 本地运行

### 1. 安装依赖

需要 Python 3.11、[uv](https://docs.astral.sh/uv/)、Node.js 和 Docker Desktop。

```bash
uv sync --frozen
```

### 2. 配置环境变量

```bash
cp .env.example .env
${EDITOR:-vi} .env
```

至少配置：

```dotenv
OPENAI_API_KEY=填写自己的API密钥
OPENAI_BASE_URL=填写对应的OpenAI兼容接口地址
LLM_MODEL=填写接口实际支持的模型名称
HF_HOME=填写HuggingFace模型缓存目录
DATABASE_URL=填写本地PostgreSQL连接地址
INGESTION_TASK_LEASE_SECONDS=900
INGESTION_WORKER_HEARTBEAT_TTL_SECONDS=15
MINIO_ACCESS_KEY=填写本地MinIO访问账号
MINIO_SECRET_KEY=替换本地MinIO占位密码
KEYCLOAK_ADMIN_PASSWORD=替换本地Keycloak管理员占位密码
KEYCLOAK_ISSUER=http://localhost:8080/realms/trusted-rag
KEYCLOAK_AUDIENCE=trusted-rag-api
VITE_KEYCLOAK_AUTHORITY=http://localhost:8080/realms/trusted-rag
VITE_KEYCLOAK_CLIENT_ID=trusted-rag-web
```

首次下载 BGE 模型时设置 `HF_HUB_OFFLINE=0`；模型下载完成且缓存完整后可以设置为 `1`。不要提交填写后的 `.env`。

### 3. 完整 Docker 演示（推荐）

一次启动 PostgreSQL、Keycloak、Redis、MinIO、Qdrant、API、入库 Worker 和正式前端：

```bash
docker compose up -d --build --wait
curl http://localhost:8000/api/ready
```

Compose 会等待 PostgreSQL、Keycloak、Redis、MinIO、Qdrant、Worker 和 API 就绪后再启动正式前端。PostgreSQL、Redis、MinIO 和 Qdrant 使用命名卷；Keycloak 业务数据保存在 PostgreSQL 的独立 schema，在线 BM25 代际与命令行数据使用本地 `data/` 挂载。浏览器访问 <http://localhost>。

容器后端启动只执行数据库迁移，不会隐式重建整套索引。首次可直接由知识库维护者在网页上传合法资料；已有“目录 + Manifest”的资料库则继续按“使用自己的资料”运行命令行分类、解析与建索引流程。

停止服务但保留上述持久数据：

```bash
docker compose stop
```

### 4. 可选：分层本地开发

先启动 PostgreSQL、Keycloak、Qdrant、Redis 与 MinIO：

```bash
docker compose up -d postgres keycloak qdrant redis minio
uv run --frozen alembic upgrade head
```

Keycloak 首次启动会导入 `keycloak/realm-export.json`。管理员密码仍是必须在本地替换的 `CHANGE_ME`；以下账号是有意公开、仅供本地复现角色流程的演示凭证：

| 业务角色 | 用户名 | 密码 |
|---|---|---|
| 企业成员 | `admin01` | `12301` |
| 知识库维护者 | `admin02` | `12302` |

不要把这些公开演示密码复用到任何真实环境。首次使用还需要按照“使用自己的资料”完成解析和索引。

然后启动后端：

```bash
uv run --frozen python -m uvicorn src.api.main:app --reload
```

后端地址：<http://localhost:8000>

另开终端启动入库 Worker；未启动或心跳过期时 `/api/ready` 会返回 503：

```bash
uv run --frozen python -m scripts.run_ingestion_worker
```

最后启动前端。`npm run dev` 已封装根目录 `.env` 的读取，不需要在前端目录复制配置文件：

```bash
cd src/frontend
npm ci
npm run dev
```

浏览器访问：<http://localhost:5173>

## 运行评测

```bash
# 运行默认评测
uv run --frozen python scripts/run_eval.py

# 运行指定题目，并将结果写入独立目录
uv run --frozen python scripts/run_eval.py --ids Q001,Q002 --run-name smoke
```

使用 `--run-name` 时，进度和报告写入 `data/eval/runs/<run-name>/`。评测支持断点续传，单题异常不会中断整轮。

## 运行测试

```bash
uv run --frozen python -m pytest tests/ -v

# 包含真实 PostgreSQL 迁移与 API 就绪验收
docker compose --profile test up -d --wait postgres-test
TRUSTED_RAG_TEST_DATABASE_URL=postgresql+psycopg://trusted_rag_test:trusted_rag_test@localhost:5433/trusted_rag_test \
  uv run --frozen python -m pytest tests/ -v
docker compose --profile test stop postgres-test
docker compose --profile test rm -f postgres-test
```

## 目录结构

公开仓库保留下面这些核心目录和文件，便于快速定位实现、评测代码和说明文档：

```text
trusted-rag-banking/
├── src/                    核心源码：解析、索引、检索、生成、API 和前端
├── scripts/                建库、定向更新、评测与质量检查脚本
├── tests/                  单元测试与回归测试
├── prototype/              下一阶段企业知识库静态交互原型
├── data/                  仅保留空目录占位；真实数据不进入 Git
├── docs/
│   ├── 技术文档.md         架构、实现、评测与项目边界
│   └── assets/             技术文档和 README 使用的界面截图
├── CONTEXT.md              已确认决策、实施状态与待确认事项
├── docker-compose.yml      本地与容器化服务编排
├── pyproject.toml          Python 项目与依赖配置
└── README.md               项目入口说明
```

## 进一步阅读

- [技术文档](docs/技术文档.md)
- [下一阶段静态原型](prototype/index.html)
- [产品与技术决策记录](CONTEXT.md)
