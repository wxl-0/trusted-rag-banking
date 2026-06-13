# 实施计划摘要

完整实施计划包含所有模块的具体代码和测试用例，详见队长共享的完整版本。

## 分工总表

| Task | 内容 | 负责人 |
|---|---|---|
| Task 0 | 项目初始化（环境、Docker、依赖） | 全员 |
| Task 1 | Chunk 数据模型（接口契约核心） | 成员 A |
| Task 2 | Word/PDF 解析器 | 成员 A |
| Task 3 | Excel 解析器 | 成员 A |
| Task 4 | 批量入库脚本 | 成员 A |
| Task 5 | Embedding 客户端 | 成员 B |
| Task 6 | Qdrant 索引器 | 成员 B |
| Task 7 | BM25 索引 | 成员 B |
| Task 8 | 查询路由 + 混合检索 + Reranker | 成员 B |
| Task 9 | LLM 客户端 + Prompt 构建 | 成员 C |
| Task 10 | 查询分解器 + 答案构建器 | 成员 C |
| Task 11 | FastAPI 服务 | 成员 C |
| Task 12 | React 前端 | 成员 C |
| Task 13 | 评测脚本 | 成员 C |
| Task 14 | README + 集成验证 | 队长 + 全员 |

## 里程碑

| 时间 | 目标 |
|---|---|
| 第 1 周末 | Task 0–1 完成，接口契约锁定 |
| 第 2 周末 | Task 2–8 完成，三路检索可返回结果 |
| 第 3 周末 | Task 9–12 完成，端到端联调运行 |
| 第 4 周末 | Task 13–14 完成，评测报告 + 交付材料 |

## 关键技术要点

- 每个 Task 有完整可运行的测试代码（TDD 模式）
- 每个 Step 包含完整 Python/JS 代码，可直接复制使用
- 每个 Task 结束后 commit
- 接口变更必须所有人知情并更新 `docs/interface.md`
