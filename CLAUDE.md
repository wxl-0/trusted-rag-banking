# Claude Code 项目说明

本仓库的协作规则、命令、模块职责和实现边界以 [`AGENTS.md`](AGENTS.md) 为唯一维护入口。开始设计或开发前还必须阅读 [`CONTEXT.md`](CONTEXT.md)，确认哪些能力已经实现、哪些只有静态原型、哪些仍是下一阶段方案。

特别注意：

- 只维护当前公开展示仓库，不读取同级比赛交付包或归档目录。
- 当前正式代码是 Manifest/命令行建库 + FastAPI/React 问答系统，并已接入 PostgreSQL 基线与 Keycloak 问答身份认证。
- `prototype/` 中的登录与账户区已经进入正式 React；角色工作区、历史对话、知识库管理和上传流程仍是静态原型，不代表 PostgreSQL 业务表、Redis、MinIO、在线异步入库和持久化会话已经实现。
- 对外项目说明以 [`README.md`](README.md) 和 [`docs/技术文档.md`](docs/技术文档.md) 为准；发现文档与代码不一致时，先核对当前源码，再同步这些文档和 `CONTEXT.md`。
