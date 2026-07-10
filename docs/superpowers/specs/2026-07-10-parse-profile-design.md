# Parse Profile 分类解析系统设计

## 背景

500 个监管文件内容差异极大，用同一套切分规则导致严重质量问题：
- 数字 pattern `\d+[\.、]` 在统计 PDF 中过度切分（56% clause chunk 内容 ≤5 字）
- NFRA-461 计算模板产出 34 万 chunk，90% 是 raw_value=0
- 英文年报 PDF 无中文标点切分点，产生 9000+ 字超长 chunk

## 决策

| 决策点 | 选择 |
|--------|------|
| 统计 PDF（NFRA-362~370） | PDF 表格提取器（pdfplumber） |
| 年报 PDF（NFRA-373/374 等） | 段落级切分，不做子条款切分 |
| Excel 模板（NFRA-461 等） | 文件级 skip，不入库 |
| 正常 Excel | 保留所有值（包括 0） |
| 路由方式 | manifest.json 驱动 |
| 0 值处理 | 按文件级判断，不按值过滤 |

## Profile 定义

| profile | 适用文件 | 解析器 | 后处理 |
|---------|----------|--------|--------|
| `regulation` | Word/PDF 监管文件 | WordParser / PdfEnhancedParser | 子条款切分 + 超长切分 + enrich + 过滤 |
| `report` | 年报/长篇报告 PDF | PdfEnhancedParser | 不做子条款切分，超长切分(800字) + enrich + 过滤 |
| `pdf_table` | 统计类 PDF（表格为主） | PdfTableParser（新建） | 输出 table_row chunk，不走 chunk_processor |
| `data` | 正常 Excel 数据表 | ExcelCellParser | 不变，保留所有值 |
| `skip` | 空模板/无价值文件 | 不解析 | — |

## 架构

```
manifest.json (parse_profile 字段)
    ↓
ingest.py (路由层)
    ├── skip        → 跳过
    ├── regulation  → PdfParser/WordParser → process_chunks(profile="regulation")
    ├── report      → PdfEnhancedParser → process_chunks(profile="report")
    ├── pdf_table   → PdfTableParser → table_chunks.jsonl
    └── data        → ExcelCellParser → table_chunks.jsonl
```

## chunk_processor 改造

`process_chunks(chunks, profile="regulation")` 根据 profile 配置走不同管道：

```python
PROFILE_CONFIG = {
    "regulation": {
        "sub_clause_split": True,
        "max_chars": 600,
        "sentence_split_chars": "。；",
    },
    "report": {
        "sub_clause_split": False,
        "max_chars": 800,
        "sentence_split_chars": "。；.;",
    },
}
```

数字 pattern 修复：只在 regulation profile 下生效，且要求前面是换行/句末标点：
```python
# 旧：r'(?=\d+[\.、])'
# 新：r'(?<=[\n。；])(?=\d+[\.、])'
```

## PdfTableParser（新建）

使用 pdfplumber 提取表格，输出与 ExcelCellParser 一致的 table_row chunk。

text 格式：
```
文件《21家国内主要银行绿色信贷统计》；页码 P3；行指标「节能环保」；列口径「贷款余额」；原始值为 12,345.67。
```

## Manifest 自动分类

`scripts/classify_manifest.py` 根据文件名/后缀/关键词自动填充 parse_profile：

- `.xls/.xlsx` + 标题含"模板/计算模板" → `skip`
- `.xls/.xlsx` 其余 → `data`
- `.pdf` + 标题含"统计/汇总表/数据汇总" → `pdf_table`
- `.pdf` + 标题含"年报/报告/annual" → `report`
- `.pdf` 其余 → `regulation`
- `.doc/.docx` → `regulation`

不覆盖已有 parse_profile 字段，允许手动修正。

## 改动清单

**新建（2）**：
- `src/parser/pdf_table_parser.py`
- `scripts/classify_manifest.py`

**修改（4）**：
- `src/parser/chunk_processor.py` — PROFILE_CONFIG + profile 参数 + 数字 pattern 修复
- `scripts/ingest.py` — 读取 parse_profile 做路由
- `data/manifest.json` — 加 parse_profile 字段
- `requirements.txt` — 加 pdfplumber

**不动**：
- 三个现有解析器（word_parser, pdf_enhanced_parser, excel_cell_parser）
- 索引层、检索层、生成层、API 层
- Dockerfile、docker-compose

## 预期效果

| 指标 | 修改前 | 修改后（预估） |
|------|--------|----------------|
| clause_chunks | 24,760（56% 垃圾） | ~8,000（质量正常） |
| table_chunks | 389,099（含 340K 零值） | ~50,000 |
| 新增 pdf_table chunks | 0 | ~2,000-5,000 |

## 验证

```bash
python scripts/classify_manifest.py
python scripts/ingest.py
python scripts/check_chunk_quality.py --suffix .pdf --limit-files 3 --sample-chunks 3
```
