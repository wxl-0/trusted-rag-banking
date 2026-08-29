# AGENTS.md

本文件只记录进入本仓库后必须遵守的协作规则。产品决策看 `CONTEXT.md`，运行说明看 `README.md`，架构与评测细节看 `docs/技术文档.md`。

## 开始工作前

- 本仓库是唯一允许维护的公开展示项目。未经用户重新授权，不读取、不复制、不修改同级比赛交付包、归档目录或其内容，包括 `trusted-rag-banking-delivery-without-models`。
- 设计、拆票或开发前完整读取 `CONTEXT.md`；存在相关 `docs/adr/` 时一并读取。已确认决策是边界，尚未确认事项不得自行定案。
- 功能工作先读取对应 GitHub Issue 的正文、标签和依赖关系；需求入口与操作约定见 `docs/agents/issue-tracker.md`，领域文档约定见 `docs/agents/domain.md`。
- 缺少必要材料时直接说明并询问用户，不去范围外目录补找。

## 当前实现边界

- 正式代码已包含 Manifest/命令行建库、FastAPI/React 问答、Keycloak OIDC 登录与访问控制、PostgreSQL 个人对话/消息持久化、滚动摘要与分层上下文预算。
- `prototype/` 是正式 React 后续页面的视觉与交互基准。登录、账户区、问答、个人历史侧栏，以及维护者只读知识库页面已接入正式前端；上传与异步入库仍是静态原型。
- 对话历史管理，以及知识文档/版本/任务表和维护者只读概览、搜索、筛选、分页、详情已实现；审计表、Redis、MinIO、在线上传、后台入库、重试和删除尚未实现。
- 文档和代码说明必须区分“已实现”“静态原型”“已确认但尚未实现”，不得把发布评测快照描述成干净克隆可实时复核的运行结果。

## 不可破坏的产品与技术约束

- 系统只服务一个企业和一套企业共享知识库，不扩展为多租户或个人知识库。
- 业务角色只有 `member` 和 `knowledge_maintainer`；Keycloak 系统管理员不等于知识库维护者。授权只相信后端验证后的令牌身份，请求正文自报角色和前端隐藏按钮都不能代替后端鉴权。
- PostgreSQL 保存业务事实，MinIO 保存原始文件及版本，Redis 负责异步任务协调，Qdrant 保存向量索引，BM25 保存关键词索引；不要让其中一个组件越权承担其他组件职责。
- 正式问答 API 不返回 `confidence`。`choice` 只属于选择题评测适配层，不进入开放问答接口；无法确定选项时标记 `unparseable`，不使用 LLM Judge 代替正式判分。
- 原型已经确认的页面按原型实现；确有技术冲突时先说明，不静默重新设计。
- 不提交 `.env`、真实密码、令牌、客户端密钥、模型缓存、原始资料、Chunk、BM25 文件或 Qdrant 数据。`keycloak/realm-export.json` 中明确标注的本地公开演示凭证是唯一例外，不得复用到真实环境。

## 修改与验证规则

- 开始改动前明确目标、范围和可验证的完成标准；会实质影响结果的歧义必须先说明或询问。
- 只做当前 Issue 直接要求的改动，不顺手重构、格式化或清理无关内容。
- working tree 可能包含用户或其他任务的未提交改动。修改前先检查差异，保留来源不明的内容；提交时只选择性暂存本工单文件。
- 优先通过公开接口验证行为。后端主要测试缝隙是 FastAPI HTTP API + TestClient；身份、Keycloak、Redis、MinIO、Qdrant 和模型通过可控依赖或适配器隔离。
- 数据库集成测试使用真实 PostgreSQL，并只允许连接名称以 `_test` 结尾的可丢弃数据库；不得把开发库或展示数据当测试库。
- 前端至少运行自动化测试和生产构建；涉及已确认页面时，再按 `prototype/` 人工核对关键视觉与交互。
- 明确区分单元/模拟测试、真实依赖集成、浏览器验证和外部业务验收。健康检查成功不等于端到端问答可用。
- 改变当前能力边界时，同步更新 `CONTEXT.md`、`README.md` 和 `docs/技术文档.md` 中直接受影响的状态说明。

## 常用入口

完整命令和数据准备步骤以 `README.md` 为准。日常开发常用：

```bash
uv sync --frozen
test -f .env || cp .env.example .env
docker compose up -d postgres keycloak qdrant
uv run --frozen alembic upgrade head

uv run --frozen python -m uvicorn src.api.main:app --reload
uv run --frozen python -m pytest tests/ -v

cd src/frontend
npm ci
npm test
npm run build
```

真实 PostgreSQL 集成测试：

```bash
docker compose --profile test up -d --wait postgres-test
TRUSTED_RAG_TEST_DATABASE_URL=postgresql+psycopg://trusted_rag_test:trusted_rag_test@localhost:5433/trusted_rag_test \
  uv run --frozen python -m pytest tests/ -v
docker compose --profile test stop postgres-test
docker compose --profile test rm -f postgres-test
```

单文档数据修复必须使用 `scripts/update_documents.py`：默认先预览，确认后再传 `--apply`。不得用会重建全量 Chunk 的 `scripts/ingest.py` 代替单文档更新。

## Git 约定

- `main` 是唯一最新基线和默认开发分支；只有用户明确要求隔离开发或评审时才创建功能分支。
- 提交前检查 staged diff、验证结果和 Author/Committer；不要把无关 dirty work 混入提交。
- 推送、创建 PR、关闭 Issue 或发布外部结果必须符合用户当前授权和对应流程，不能从“实现完成”自行推断。
