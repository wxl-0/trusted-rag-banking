# 切块策略说明与注意事项

> 面向成员 A（解析层负责人）及全体成员，在拿到真实数据集后必读。

---

## 一、当前切块策略

### WordParser（`src/parser/word_parser.py`）

- **切块逻辑**：遇到 `Heading` 样式段落就将缓冲区内容 flush 为一个 chunk，两个相邻标题之间的全部正文拼接成一条记录。
- **section_path**：记录标题层级路径，例如 `["第三章 资本充足率", "第十二条"]`。
- **前提假设**：Word 文件使用了标准的 Heading 1/2/3 段落样式。

### PdfParser（`src/parser/pdf_parser.py`）

- **切块逻辑**：字体大小 ≥ 14pt 的文字识别为标题，触发 flush。
- **前提假设**：标题字号明显大于正文，且没有双栏排版、页眉页脚混入正文等情况。

### ExcelParser（`src/parser/excel_parser.py`）

- **切块逻辑**：每行数据生成一个 chunk，转换为自然语言句子，例如：`"2024Q3，不良贷款率为1.56%"`。
- **前提假设**：第一行是表头，第一列是指标名，第二列是数值，第三列是单位；表为竖表（指标按行排列）。

---

## 二、拿到真实文件后最可能遇到的问题

| # | 问题 | 影响的解析器 | 后果 |
|---|---|---|---|
| 1 | Word 文件用手动加粗/字号而非 Heading 样式 | Word | 所有正文被当成一个超大 chunk，无法按条款检索 |
| 2 | 监管文档以 `第X条`/`第X章` 作为段落开头而非 Heading | Word | 解析器无法识别条款边界，切块粒度过粗 |
| 3 | 一个 Heading 下正文很长（超过 ~400 token） | Word / PDF | Embedding 模型截断，检索质量下降 |
| 4 | PDF 页眉/页脚文字混入正文 | PDF | chunk 中含页码、文件编号等噪声 |
| 5 | PDF 多栏排版（如双栏条文） | PDF | pymupdf 按坐标顺序提取，左右栏文字交错，语义混乱 |
| 6 | Excel 表头为多行合并单元格 | Excel | 表头识别失败，indicator 字段提取为空 |
| 7 | Excel 为横表（指标按列排列） | Excel | 当前逻辑按行切，会切出无意义的 chunk |
| 8 | Excel 含合计行、备注行 | Excel | 被当成正常数据行索引，干扰检索 |

---

## 三、验证方法（拿到文件后第一件事）

各取 1-2 份代表性文件，运行以下命令，肉眼检查前 5 条 chunk 是否合理：

**Word 文件：**
```bash
python -c "
from src.parser.word_parser import WordParser
p = WordParser(doc_id='test', source_title='test', issuer='', doc_no='', publish_date='', source_url='', local_path='data/raw/某文件.docx')
for c in p.parse()[:5]:
    print(c.section_path, '|', c.text[:100])
    print('---')
"
```

**PDF 文件：**
```bash
python -c "
from src.parser.pdf_parser import PdfParser
p = PdfParser(doc_id='test', source_title='test', issuer='', doc_no='', publish_date='', source_url='', local_path='data/raw/某文件.pdf')
for c in p.parse()[:5]:
    print(c.section_path, '|', c.text[:100])
    print('---')
"
```

**Excel 文件：**
```bash
python -c "
from src.parser.excel_parser import ExcelParser
p = ExcelParser(doc_id='test', source_title='test', issuer='', publish_date='', source_url='', local_path='data/raw/某文件.xlsx')
for c in p.parse()[:5]:
    print(c.indicator, c.period, '|', c.text)
    print('---')
"
```

**判断标准：**
- chunk 数量是否合理（一份 20 页制度文件大约应切出 30-80 条）
- section_path 是否正确反映了章节位置
- text 内容是否干净，无页眉页脚噪声
- Excel 的 indicator 字段是否正确提取了指标名

---

## 四、可能需要的改动方向

### Word 解析器
- 加正则识别 `第[一二三四五六七八九十百]+条` 作为备用切块边界（兜底无 Heading 样式的文件）
- 加最大 token 长度限制（建议 400 token），超长则按句号二次切分

### PDF 解析器
- 加页眉页脚过滤：按坐标过滤掉页面顶部 50pt 和底部 50pt 范围内的文字
- 遇到双栏 PDF 可切换为按块（block）而非按行（line）拼接

### Excel 解析器
- 支持多行合并表头：向上找非空单元格作为列名
- 加跳过逻辑：跳过全行为"合计"、"小计"、"备注"等关键词的行
- 支持横表检测：若第一行非字符串表头，尝试转置后再解析

### 通用
- 所有解析器加 `min_text_length` 过滤（建议 10 字），过滤空行、单字符行
- 入库前统计 chunk 的 token 分布，发现异常大的 chunk 及时处理

---

## 五、分工建议

| 成员 | 行动项 |
|---|---|
| 成员 A | 拿到文件后先跑验证命令，发现问题后修改对应解析器，保证 chunk 质量 |
| 成员 B | 入库前检查 `clause_chunks.jsonl` 和 `table_chunks.jsonl` 的条数和内容，反馈给成员 A |
| 全体 | 如发现某类文件结构特殊，在群里说明，成员 A 统一处理后重新 ingest |
