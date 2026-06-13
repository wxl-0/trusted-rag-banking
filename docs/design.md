# 面向银行业监管制度与统计报表的可信 RAG 问答系统 — 设计文档

**项目**：第五届中国研究生金融科技创新大赛 · 南京银行赛题  
**日期**：2026-06-13  
**技术栈**：Python · FastAPI · Qdrant · 商业 LLM API · React  
**优先级**：系统完整性（所有功能可运行，指标全面达标）

---

## 一、整体架构

系统分为 5 层：

```
解析层 → 索引层 → 检索层 → 生成层 → 服务层
```

**核心设计决策：**
- 制度文本与统计表格使用两个独立 Qdrant Collection
- 查询路由在检索前判断问题类型，决定走哪条索引
- 生成层强制 Grounded Generation：答案只能来自检索证据，无依据则拒答

---

## 二、解析层

### 2.1 Word/PDF 解析链

- 工具：`python-docx`（docx）、`pymupdf`（pdf）
- 保留章节编号、条款层级、发文机关、文号、发布日期

Chunk 数据结构：

```json
{
  "doc_id": "NFRA-2024-001",
  "chunk_id": "NFRA-2024-001#第三章#第十二条",
  "text": "...",
  "source_title": "商业银行资本管理办法",
  "issuer": "国家金融监督管理总局",
  "doc_no": "银监发ゔ2024ゕX号",
  "publish_date": "2024-01-01",
  "section_path": ["第三章 资本充足率", "第十二条"],
  "chunk_type": "clause",
  "source_url": "https://...",
  "local_path": "data/NFRA-2024-001.pdf"
}
```

### 2.2 Excel 解析链

- 工具：`openpyxl`
- 每行生成一条自然语言化 Chunk，保留表头语义和维度信息

```json
{
  "doc_id": "STAT-2024-Q3-001",
  "chunk_id": "STAT-2024-Q3-001#Sheet1#R15",
  "text": "2024年三季度末，不良贷款率为1.56%",
  "table_name": "G11《资产质量情况表》",
  "indicator": "不良贷款率",
  "period": "2024Q3",
  "unit": "%",
  "chunk_type": "table_row"
}
```

---

## 三、索引与检索层

### 3.1 索引结构

| 索引 | 内容 | 检索强项 |
|---|---|---|
| `collection_regulations` | 条款/段落 Chunk | 语义相似、制度理解 |
| `collection_tables` | 表格行记录 Chunk | 指标查询、数值取数 |
| BM25（rank_bm25） | 全部文本 | 文号精确匹配、指标名称 |

Embedding 模型：`text-embedding-3-small`（OpenAI）

### 3.2 查询路由

```
用户问题 → LLM 单次分类
  ├── 制度事实/条款阈值/流程要求  →  collection_regulations
  ├── 统计取数/指标口径            →  collection_tables
  ├── 跨类问题（场景判断/多跳）       →  两路同时召回
  └── 超出范围                       →  直接拒答
```

### 3.3 混合检索流程

```
BM25 召回（Top-20）+ 向量召回（Top-20）+ 元数据过滤
  ↓
RRF 融合排序
  ↓
Cross-Encoder Reranker 精排（bge-reranker-base）
  ↓
Top-5 Chunks → 生成层
```

---

## 四、生成层

### 4.1 Prompt 设计（强约束 Grounded Generation）

```
规则：
1. 只能使用【参考资料】中的内容作答，禁止引入外部知识
2. 涉及金额、比例、日期、机构名称、文号必须原文引用
3. 区分“应当/必须”“可以”“不得”“原则上”等规范强度词
4. 参考资料不足时拒答并说明原因
```

输出结构：

```json
{
  "answer": "...",
  "confidence": "high/medium/low",
  "evidence": [{"source_title": "...", "section": "...", "text": "...", "source_url": "..."}],
  "refuse_reason": null
}
```

### 4.2 多跳查询分解

跨类问题拆分为子问题，分别检索制度和统计数据，合并生成最终答案。

---

## 五、服务层 API

```
POST /api/ask       # 主问答接口
POST /api/ingest    # 文档入库
GET  /api/health    # 健康检查
```

---

## 六、前端

React + Vite，打包后由 FastAPI 托管。

页面：对话式问答 + 置信度标签 + 证据来源折叠卡片。

---

## 七、三人分工

| 成员 | 模块 | 接口契约 |
|---|---|---|
| 成员 A | `src/parser/` + `scripts/ingest.py` | 输出标准 Chunk JSONL |
| 成员 B | `src/indexer/` + `src/retriever/` | 暂露 `retrieve(query, query_type, filters, top_k) -> list[dict]` |
| 成员 C | `src/generator/` + `src/api/` + `src/frontend/` + `run_eval.py` | 输出标准响应结构 |

---

## 八、量化指标对照

| 赛题要求 | 系统设计对应点 |
|---|---|
| 制度事实准确率 ≥ 85% | Grounded Generation + Reranker 精排 |
| 表格取数准确率 ≥ 80% | 独立 Table Collection + 行语义化 |
| 证据引用命中率 ≥ 90% | 强制 evidence 字段 + 条款级定位 |
| 关键字段错误率 ≤ 5% | Prompt 规则 + 数字核验机制 |
| 拒答率 ≥ 80% | 查询路由拒答分支 + refuse_reason |
