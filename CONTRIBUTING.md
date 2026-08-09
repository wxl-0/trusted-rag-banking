# 贡献指南

本文档面向项目所有开发成员，规定分支策略、提交规范、PR 流程和接口变更规则。**所有成员在开始开发前必须阅读本文档。**

---

## 一、分支策略

```
main          ← 唯一最新基线，代表当前可演示版本
  ├── feature/parser-*       ← 解析模块任务分支
  ├── feature/retriever-*    ← 检索模块任务分支
  └── feature/generator-*    ← 生成、评测或前端任务分支
```

**规则：**
- `main` 是唯一最新基线，不再使用 `dev` 作为集成分支
- 每项开发任务从最新 `main` 新建 `feature/xxx` 或 `hotfix/xxx` 分支
- 禁止直接向 `main` 推送提交，所有代码必须通过 Pull Request 合入 `main`

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

## 三、Pull Request 流程

1. 本地开发完毕，确保代码能运行
2. 如新增依赖，使用 `uv add 包名` 更新 `pyproject.toml` 和 `uv.lock`
3. 向 `main` 分支发起 PR，标题格式同 commit 规范
4. PR 描述中说明：做了什么、如何测试、是否影响接口
5. 等待队长 review，resolve 所有 comment 后合并

**PR 合并前检查清单：**
- [ ] 本地运行无报错
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

- 接口变更：先在群里说明，再发 PR
- 阻塞问题：当天告知队长，不要卡着不说
- 紧急 bug：从最新 `main` 新建 `hotfix/xxx` 分支，验证后通过 PR 合入 `main`
