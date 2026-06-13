# 贡献指南

本文档面向项目所有开发成员，规定分支策略、提交规范、PR 流程和接口变更规则。**所有成员在开始开发前必须阅读本文档。**

---

## 一、分支策略

```
main          ← 保护分支，只接受来自 dev 的 PR，代表可演示版本
  └── dev     ← 集成分支，功能开发完成后合入此处
        ├── feature/parser       ← 成员 A 负责
        ├── feature/retriever    ← 成员 B 负责
        └── feature/generator    ← 成员 C 负责（含前端）
```

**规则：**
- 禁止直接向 `main` 或 `dev` 推送提交
- 所有代码必须通过 Pull Request 合入 `dev`
- `main` 只由队长在里程碑节点从 `dev` 合入

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
2. 更新 `requirements.txt`（如新增依赖）
3. 向 `dev` 分支发起 PR，标题格式同 commit 规范
4. PR 描述中说明：做了什么、如何测试、是否影响接口
5. 等待队长 review，resolve 所有 comment 后合并

**PR 合并前检查清单：**
- [ ] 本地运行无报错
- [ ] 新增依赖已写入 `requirements.txt`
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
pip install -r requirements.txt
docker compose up -d
uvicorn src.api.main:app --reload
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
- 紧急 bug：直接在 `dev` 开 `hotfix/xxx` 分支，快速合入
