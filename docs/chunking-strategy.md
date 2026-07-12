# 切块策略文档

> 最后更新：2026-07-12

本文档描述当前系统的文档切块（chunking）策略，涵盖四类解析器和后处理管道。

---

## 一、整体流程

```
原始文件（.docx/.doc/.pdf/.xls/.xlsx）
    ↓
解析器（WordParser / PdfParser / ExcelParser / PdfTableParser）
    ↓ 输出 Chunk 对象列表
后处理管道（chunk_processor.py，仅 clause 类型，按 profile 分策略）
    ↓
写入 JSONL（clause_chunks.jsonl / table_chunks.jsonl）
```

---

## 二、解析器

### 2.1 WordParser（`src/parser/word_parser.py`）

**切块逻辑**：
- 按 Heading 样式切分（Heading 1/2/3）
- 备用识别：`第X章`/`第X节` 开头的段落也视为标题
- Word 内嵌表格单独处理为 `table_row` 类型 chunk

**`.doc` 处理**：
- 先查 `data/converted/docx/` 是否有缓存的 `.docx` 转换结果
- 缓存存在则直接读取，否则调用 win32com 转换

**Word 表格 chunk 特点**：
- 合并单元格去重：通过 `id(cell._tc)` 追踪已处理的底层 XML 元素，避免同一合并单元格重复输出
- 跳过"附件"/"统计表"/"报告表"标题行
- text 格式：`文件《标题》表格 N 第 M 行；列头: 值；...`

### 2.2 PdfParser（`src/parser/pdf_parser.py`）

**切块逻辑**：
- 按 heading 切分，heading 判定条件：
  - 正则匹配：`第X章`/`第X节`/`（一）`/`Chapter N`
  - 字号 ≥ 16pt 且长度 ≤ 40 字且不以标点结尾
- **不按页切分** — 跨页段落保持完整，遇到下一个 heading 才 flush
- 噪声过滤：单字符和纯数字行跳过
- 记录 `page_no`（buffer 开始时的页码）

### 2.3 ExcelParser（`src/parser/excel_parser.py`）

**切块粒度**：单元格级（每个数据单元格一个 chunk）。

**解析步骤**：
1. 自动检测 header 行（通过"项目"/"指标"等关键词或下方有数字列）
2. 自动检测 label 列（指标名所在列）
3. 检测 unit（前 8 行中含"单位"的文本）
4. 检测 period（从文件名/sheet 名/标题中提取年份季度）

**双轮提取**：
- **第一轮（数值）**：遍历 header 下方数据行，提取数值单元格（`_looks_like_data_cell`），跳过空行和注释行（"注"/"备注"/"说明"开头）。同时收集所有 `row_label` 和 `header` 文本。
- **第二轮（文本）**：再次遍历所有行所有列，对非空、非数值、且不在 `all_known`（row_labels ∪ header_texts）中的单元格输出 chunk。用于捕获脚注、指标公式、机构范围定义等文本内容。

**text 格式**：
```
文件《标题》；工作表「Sheet1」；单元格 C5；行指标「不良贷款率」；列口径「2024年」；原始值为 1.56%；单位：百分比；期间：2024。
```

**Metadata 字段**：`cell_ref`、`row_label`、`column_header`、`raw_value`、`table_name`、`indicator`、`period`、`unit`、`row_index`

### 2.4 PdfTableParser（`src/parser/pdf_table_parser.py`）

**用途**：对 `parse_profile=pdf_table` 的统计 PDF 使用 pdfplumber 提取表格。

**切块逻辑**：
- 遍历页面 → `page.extract_tables()` → 逐行逐列生成 Chunk
- 跳过空值和空行
- text 格式与 ExcelParser 对齐
- chunk_id 格式：`{doc_id}#{page}T{table}R{row}C{col}`

---

## 三、后处理管道（`src/parser/chunk_processor.py`）

**仅作用于 `chunk_type="clause"` 的 chunk**，`table_row` 直接跳过。

通过 `profile` 参数控制不同策略：

| profile | 子条款切分 | 超长阈值 | 句子切分符 |
|---------|-----------|---------|-----------|
| `regulation` | 是 | 600 字 | `。；` |
| `report` | 否 | 800 字 | `。；.;` |

处理顺序：
```
子条款切分（可选）→ 超长切分 + overlap → 上下文增强 → 最小长度过滤
```

### 3.1 子条款切分（`split_sub_clauses`）

仅 `regulation` profile 启用。按编号模式在一个 chunk 内部做二次切分：
- `（一）`/`（二）`... — 中文圆括号编号
- `(一)`/`(二)`... — 英文圆括号编号
- `1.`/`2.`/`1、`/`2、` — 阿拉伯数字编号（需前置换行/句号/分号）

切分后子块 chunk_id 加 `#K{n}` 后缀，`parent_chunk_id` 指向原块。

### 3.2 超长切分（`split_by_max_length`）

- regulation 阈值：**600 字**，report 阈值：**800 字**
- 按句子级切分（切分符由 profile 决定）
- 相邻切片重叠 **80 字**（`OVERLAP_CHARS`）
- 子块 chunk_id 加 `#S{n}` 后缀

### 3.3 上下文增强（`enrich_context`）

在每个切片的 text 开头拼接前缀：
```
《源文件标题》章节 > 路径：
原始文本...
```

**放在超长切分之后**，确保每个分片都有完整的上下文前缀。

### 3.4 最小长度过滤（`filter_min_length`）

丢弃 text 长度 < 10 字的 chunk（`MIN_CHUNK_CHARS`），以及以噪声前缀开头的 chunk（"本页无正文"/"目录"/"附件清单"等）。

---

## 四、chunk_id 命名规则

| 来源 | 格式示例 |
|------|---------|
| Word/PDF 条款 | `NFRA-390#第三章#第十二条` |
| 子条款切分 | `NFRA-390#第三章#第十二条#K1` |
| 超长切分 | `NFRA-390#第三章#第十二条#S1` |
| 子条款+超长 | `NFRA-390#第三章#第十二条#K2#S1` |
| Excel 单元格 | `NFRA-001#Sheet1#C5` |
| Word 内嵌表格 | `NFRA-390#table1#R3` |
| PDF 段落 | `NFRA-415#P3#7`（第3页第7个chunk） |
| PDF 表格 | `NFRA-361#P1T1R3C2` |

---

## 五、关键参数

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| regulation max_chars | 600 | `chunk_processor.py` PROFILE_CONFIG | 监管文件超长阈值 |
| report max_chars | 800 | `chunk_processor.py` PROFILE_CONFIG | 年报类超长阈值 |
| `OVERLAP_CHARS` | 80 | `chunk_processor.py` | 相邻切片重叠字数 |
| `MIN_CHUNK_CHARS` | 10 | `chunk_processor.py` | 低于此长度的 chunk 丢弃 |
| `HEADING_THRESHOLD` | 16pt | `pdf_parser.py` | PDF 字号 heading 判定 |

---

## 六、输出文件

| 文件 | 内容 | 写入方式 |
|------|------|---------|
| `data/chunks/clause_chunks.jsonl` | Word/PDF 条款 chunk（含 Word 内嵌表格） | 清空重写 |
| `data/chunks/table_chunks.jsonl` | Excel + PdfTable chunk | 清空重写 |

每次 `ingest.py` 运行会清空并重新生成这两个文件。写入时自动去重（`seen_texts` 集合）。

---

## 七、当前知识库规模

- 总 chunk 数：38,287
- 覆盖文档：481 / 500（19 个 skip）
- 平均长度：129 字
- 零重复，零碎片

---

## 八、已知限制与后续优化方向

| 问题 | 影响 | 优化时机 |
|------|------|---------|
| 英文年报 chunk 超长（800+字） | report profile 以"。；.;"切分仍有少数超长 | 评测发现英文年报题目检索差时 |
| Excel 脚注单元格可能超长（1000+字） | 单个注释说明不切分 | 评测发现注释类检索精度低时 |
| Word 表格 chunk 缺少 `cell_ref`/`raw_value` | Word 内嵌表格证据定位不如 Excel 精确 | 评测发现该类题目准确率低时 |
| PDF `HEADING_THRESHOLD` 固定 16pt | 部分 PDF 标题字号较小会被漏判 | 抽样检查 PDF chunk 质量时 |
