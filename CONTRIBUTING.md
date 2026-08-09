# 贡献指南

本文档面向项目所有开发成员，规定分支策略、提交规范、协作流程和接口变更规则。**所有成员在开始开发前必须阅读本文档。**

---

## 一、分支策略

```
main          ← 唯一最新基线、默认开发分支和当前可演示版本
```

**规则：**
- `main` 是唯一最新基线，不再使用 `dev` 作为集成分支
- 日常开发直接在最新 `main` 上修改、验证和提交，不默认创建功能分支
- 提交时只暂存本次任务文件，不得把无关的本地文件带入提交
- 只有用户或团队明确要求隔离开发或代码评审时，才创建临时分支并通过 Pull Request 合入 `main`

---

## 二、Commit 规范

格式：`<type>: <简短描述>`

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `docs` | 文档变更 |
| `refactor` | 重构（不改变行为） |
| `test` | 增加或修改测试 |
| `chore` | 依赖更新、配置变更 |

---

## 三、直接 main 流程

1. 开始开发前确认当前分支为 `main`，并同步远程最新状态
2. 本地开发完毕，执行与改动风险相匹配的验证
3. 只暂存本次任务涉及的文件，检查 staged diff 后提交
4. 如新增依赖，使用 `uv add 包名` 更新 `pyproject.toml` 和 `uv.lock`
5. 需要同步远程时，将本地 `main` 推送到 `origin/main`

只有明确要求使用 PR 时，才从最新 `main` 创建临时分支，验证后向 `main` 发起 PR。

**提交前检查清单：**
- [ ] 当前分支是 `main`
- [ ] 本地运行无报错
- [ ] 暂存区只包含本次任务文件
- [ ] 新增依赖已通过 `uv add` 写入 `pyproject.toml` 和 `uv.lock`
- [ ] 若修改了接口，已更新 `docs/interface.md`
- [ ] 无调试用的 `print` 或硬编码路径

---

## 四、接口契约

### 接口 1：Chunk 数据结构（成员 A → 成员 B/C）

```json
{
  "doc_id": "string",
  "chunk_id": "string",
  "text": "string",
  "chunk_type": "clause | table_row",
  "source_title": "string",
  "issuer": "string",
  "doc_no": "string",
  "publish_date": "YYYY-MM-DD",
  "section_path": ["string"],
  "source_url": "string",
  "local_path": "string"
}
```

表格类型额外字段：`table_name`, `indicator`, `period`, `unit`, `row_index`

### 接口 2：retrieve 函数签名（成员 B → 成员 C）

```python
def retrieve(
    query: str,
    query_type: str,          # "regulation" | "table" | "hybrid"
    filters: dict = None,
    top_k: int = 5
) -> list[dict]
```

---

## 五、开发环境

```bash
git clone https://github.com/wxl-0/trusted-rag-banking.git
cd trusted-rag-banking
uv sync --frozen
docker compose up -d qdrant
uv run --frozen python -m uvicorn src.api.main:app --reload
```

---

## 六、里程碑计划

| 时间 | 目标 |
|---|---|
| 第 1 周 | 接口契约锁定，各人完成模块骨架 |
| 第 2 周 | 成员 A 完成解析入库；B 完成检索接口；C 完成基础问答 |
| 第 3 周 | 前端联调；端到端测试 |
| 第 4 周 | 评测报告；优化；交付材料 |

---

## 七、联系与协调

- 接口变更：先在群里说明，验证后提交到 `main`
- 阻塞问题：当天告知队长，不要卡着不说
- 紧急 bug：直接在最新 `main` 修复并验证；只有明确要求隔离时才使用临时分支
