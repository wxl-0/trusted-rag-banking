# 切块策略文档

> 最后更新：2026-07-09

本文档描述当前系统的文档切块（chunking）策略，涵盖三类解析器和后处理管道。

---

## 一、整体流程

```
原始文件（.docx/.doc/.pdf/.xls/.xlsx）
    ↓
解析器（WordEnhancedParser / PdfEnhancedParser / ExcelCellParser）
    ↓ 输出 Chunk 对象列表
后处理管道（chunk_processor.py，仅 clause 类型）
    ↓
写入 JSONL（clause_chunks.jsonl / table_chunks.jsonl）
```

---

## 二、解析器

### 2.1 WordEnhancedParser（`src/parser/word_enhanced_parser.py`）

**入口**：`ingest.py` 通过 `word_parser.py` 末尾的别名导入。

**切块逻辑**：
- 按 Heading 样式切分（Heading 1/2/3）
- 备用识别：`第X章`/`第X节`/`第X条` 开头的段落也视为标题
- Word 内嵌表格单独处理为 `table_row` 类型 chunk

**`.doc` 处理**：
- 先查 `data/converted/docx/` 是否有缓存的 `.docx` 转换结果
- 缓存存在则直接读取，否则调用 LibreOffice/COM 转换

**Word 表格 chunk 特点**：
- 合并单元格去重（`_unique_texts`）
- 跳过"附件"/"统计表"/"报告表"标题行
- text 格式：`文件《标题》表格 N 第 M 行；列头: 值；...`

### 2.2 PdfEnhancedParser（`src/parser/pdf_enhanced_parser.py`）

**入口**：`ingest.py` 通过 `pdf_parser.py` 末尾的别名导入。

**切块逻辑**：
- 按 heading 切分，heading 判定条件：
  - 正则匹配：`第X章`/`第X节`/`（一）`/`Chapter N`
  - 字号 ≥ 16pt 且长度 ≤ 40 字且不以标点结尾
- **不按页切分** — 跨页段落保持完整，遇到下一个 heading 才 flush
- 噪声过滤：单字符和纯数字行跳过
- 记录 `page_no`（buffer 开始时的页码）

### 2.3 ExcelCellParser（`src/parser/excel_cell_parser.py`）

**入口**：`ingest.py` 通过 `excel_parser.py` 末尾的别名导入。

**切块粒度**：单元格级（每个数据单元格一个 chunk）。

**解析步骤**：
1. 自动检测 header 行（通过"项目"/"指标"等关键词或下方有数字列）
2. 自动检测 label 列（指标名所在列）
3. 检测 unit（前 8 行中含"单位"的文本）
4. 检测 period（从文件名/sheet 名/标题中提取年份季度）
5. 跳过空行、注释行（"注"/"备注"/"说明"开头）

**text 格式**：
```
文件《标题》；工作表「Sheet1」；单元格 C5；行指标「不良贷款率」；列口径「2024年」；原始值为 1.56%；单位：百分比；期间：2024。
```

**Metadata 字段**：`cell_ref`、`row_label`、`column_header`、`raw_value`、`table_name`、`indicator`、`period`、`unit`、`row_index`

---

## 三、后处理管道（`src/parser/chunk_processor.py`）

**仅作用于 `chunk_type="clause"` 的 chunk**，Excel 的 `table_row` 直接跳过。

处理顺序：
```
子条款切分 → 超长切分 + overlap → 上下文增强 → 最小长度过滤
```

### 3.1 子条款切分（`split_sub_clauses`）

按编号模式在一个 chunk 内部做二次切分：
- `（一）`/`（二）`... — 中文圆括号编号
- `(一)`/`(二)`... — 英文圆括号编号
- `1.`/`2.`/`1、`/`2、` — 阿拉伯数字编号

切分后子块 chunk_id 加 `#K{n}` 后缀，`parent_chunk_id` 指向原块。

### 3.2 超长切分（`split_by_max_length`）

- 阈值：**600 字**（`MAX_CHUNK_CHARS`）
- 按句号 `。` 和分号 `；` 做句子级切分
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

丢弃 text 长度 < 10 字的 chunk（`MIN_CHUNK_CHARS`）。

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

---

## 五、关键参数

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| `MAX_CHUNK_CHARS` | 600 | `chunk_processor.py` | 超过此长度触发切分 |
| `OVERLAP_CHARS` | 80 | `chunk_processor.py` | 相邻切片重叠字数 |
| `MIN_CHUNK_CHARS` | 10 | `chunk_processor.py` | 低于此长度的 chunk 丢弃 |
| `HEADING_THRESHOLD` | 16pt | `pdf_enhanced_parser.py` | PDF 字号 heading 判定 |

---

## 六、输出文件

| 文件 | 内容 | 写入方式 |
|------|------|---------|
| `data/chunks/clause_chunks.jsonl` | Word/PDF 条款 chunk | 追加写入 |
| `data/chunks/table_chunks.jsonl` | Excel + Word 内嵌表格 chunk | 追加写入 |

每次 `ingest.py` 运行会清空并重新生成这两个文件。

---

## 七、已知限制与后续优化方向

| 问题 | 影响 | 优化时机 |
|------|------|---------|
| Word 表格 chunk 缺少 `cell_ref`/`raw_value` | Word 内嵌表格证据定位不如 Excel 精确 | 评测发现该类题目准确率低时 |
| chunk_id 可能冲突（同文档相同标题） | 极端情况下后者覆盖前者 | 入库时发现重复 ID 报错时 |
| PDF `HEADING_THRESHOLD` 固定 16pt | 部分 PDF 标题字号较小会被漏判 | 抽样检查 PDF chunk 质量时 |
| 百分比格式化需要 unit 中含 `%` | 部分表格 unit 列为空但实际是百分比 | 评测发现数值格式错误时 |

以上限制均可在跑完评测、看到具体错误后针对性修复。
