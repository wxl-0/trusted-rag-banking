# 可信 RAG 银行业监管问答系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建面向银行业监管制度与统计报表的可信 RAG 问答系统，支持 Word/PDF/Excel 解析、混合检索、可溯源生成和对话式前端。

**Architecture:** 五层架构（解析→索引→检索→生成→服务），制度文本与统计表格使用独立 Qdrant Collection，查询路由决定检索路径，Grounded Generation 强制答案来自检索证据。

**Tech Stack:** Python 3.11 · python-docx · pymupdf · openpyxl · qdrant-client · rank_bm25 · sentence-transformers · openai · fastapi · uvicorn · React 18 · Vite · Docker

**分工：**

- 成员 A → Task 0（共同）+ Task 1–4（解析层）
- 成员 B → Task 0（共同）+ Task 5–8（索引+检索层）
- 成员 C → Task 0（共同）+ Task 9–14（生成+服务+前端+评测）

---

## 文件结构总览

```
project/
├── .env.example
├── docker-compose.yml
├── requirements.txt
├── README.md
├── CONTRIBUTING.md
├── data/
│   ├── raw/                         # 原始文件（不提交到 git）
│   ├── chunks/
│   │   ├── clause_chunks.jsonl      # 成员 A 输出
│   │   └── table_chunks.jsonl       # 成员 A 输出
│   └── eval/
│       ├── qa_seed.jsonl
│       └── eval_report.json
├── src/
│   ├── __init__.py
│   ├── parser/
│   │   ├── __init__.py
│   │   ├── base.py                  # Chunk dataclass（接口契约）
│   │   ├── word_parser.py
│   │   ├── pdf_parser.py
│   │   └── excel_parser.py
│   ├── indexer/
│   │   ├── __init__.py
│   │   ├── embedder.py
│   │   ├── qdrant_index.py
│   │   └── bm25_index.py
│   ├── retriever/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── hybrid_retriever.py
│   │   └── reranker.py
│   ├── generator/
│   │   ├── __init__.py
│   │   ├── llm_client.py
│   │   ├── prompt_builder.py
│   │   ├── decomposer.py
│   │   └── answer_builder.py
│   └── api/
│       ├── __init__.py
│       ├── main.py
│       ├── routes.py
│       └── models.py
├── src/frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.jsx
│       ├── components/
│       │   ├── ChatInput.jsx
│       │   ├── MessageList.jsx
│       │   ├── AnswerCard.jsx
│       │   └── EvidencePanel.jsx
│       └── api/
│           └── client.js
├── scripts/
│   ├── ingest.py
│   └── run_eval.py
└── tests/
    ├── test_parser.py
    ├── test_retriever.py
    └── test_api.py
```

---

## Task 0：项目初始化（成员 A/B/C 共同完成，第一天）

**Files:**

- Create: `requirements.txt`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `src/__init__.py`

- [ ] **Step 1: 创建 requirements.txt**

```
python-docx==1.1.2
pymupdf==1.24.5
openpyxl==3.1.5
qdrant-client==1.9.1
rank-bm25==0.2.2
sentence-transformers==3.0.1
openai==1.35.3
fastapi==0.111.0
uvicorn==0.30.1
python-dotenv==1.0.1
pytest==8.2.2
httpx==0.27.0
```

- [ ] **Step 2: 安装依赖**

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

- [ ] **Step 3: 创建 docker-compose.yml**

```yaml
services:
  qdrant:
    image: qdrant/qdrant:v1.9.4
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage

volumes:
  qdrant_data:
```

- [ ] **Step 4: 创建 .env.example**

```
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1
EMBED_MODEL=text-embedding-3-small
LLM_MODEL=gpt-4o-mini
QDRANT_HOST=localhost
QDRANT_PORT=6333
RERANKER_MODEL=BAAI/bge-reranker-base
```

复制为 `.env` 并填入真实 key：

```bash
cp .env.example .env
```

- [ ] **Step 5: 启动 Qdrant**

```bash
docker compose up -d
# 验证：浏览器打开 http://localhost:6333/dashboard
```

- [ ] **Step 6: 创建空 __init__.py**

```bash
# Windows PowerShell:
New-Item -ItemType File src/__init__.py
New-Item -ItemType Directory src/parser, src/indexer, src/retriever, src/generator, src/api, tests
New-Item -ItemType File src/parser/__init__.py
New-Item -ItemType File src/indexer/__init__.py
New-Item -ItemType File src/retriever/__init__.py
New-Item -ItemType File src/generator/__init__.py
New-Item -ItemType File src/api/__init__.py
```

- [ ] **Step 7: Commit**

```bash
git add requirements.txt docker-compose.yml .env.example src/
git commit -m "chore: project scaffold and dependencies"
```

---

## Task 1：Chunk 数据模型（成员 A，接口契约核心）

**Files:**

- Create: `src/parser/base.py`
- Create: `tests/test_parser.py`（第一个测试）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_parser.py`：

```python
import pytest
from src.parser.base import Chunk

def test_chunk_to_dict_clause():
    chunk = Chunk(
        doc_id="NFRA-001",
        chunk_id="NFRA-001#第三章#第十二条",
        text="商业银行资本充足率不得低于10.5%。",
        chunk_type="clause",
        source_title="商业银行资本管理办法",
        issuer="国家金融监督管理总局",
        doc_no="银监发〔2023〕1号",
        publish_date="2023-11-01",
        section_path=["第三章 资本充足率", "第十二条"],
        source_url="https://www.nfra.gov.cn/xxx",
        local_path="data/raw/NFRA-001.pdf",
    )
    d = chunk.to_dict()
    assert d["doc_id"] == "NFRA-001"
    assert d["chunk_type"] == "clause"
    assert "table_name" not in d  # 非表格字段不出现

def test_chunk_to_dict_table_row():
    chunk = Chunk(
        doc_id="STAT-001",
        chunk_id="STAT-001#Sheet1#R5",
        text="2024年三季度末，不良贷款率为1.56%。",
        chunk_type="table_row",
        source_title="G11资产质量情况表",
        issuer="国家金融监督管理总局",
        doc_no="",
        publish_date="2024-09-30",
        section_path=[],
        source_url="https://www.nfra.gov.cn/yyy",
        local_path="data/raw/STAT-001.xlsx",
        table_name="G11《资产质量情况表》",
        indicator="不良贷款率",
        period="2024Q3",
        unit="%",
        row_index=5,
    )
    d = chunk.to_dict()
    assert d["chunk_type"] == "table_row"
    assert d["indicator"] == "不良贷款率"
    assert d["period"] == "2024Q3"
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/test_parser.py -v
# 预期：ImportError: cannot import name 'Chunk'
```

- [ ] **Step 3: 实现 src/parser/base.py**

```python
from dataclasses import dataclass, field
from typing import Optional, List
import json


@dataclass
class Chunk:
    doc_id: str
    chunk_id: str
    text: str
    chunk_type: str          # "clause" | "table_row"
    source_title: str
    issuer: str
    doc_no: str
    publish_date: str        # "YYYY-MM-DD"
    section_path: List[str]
    source_url: str
    local_path: str
    # 表格专用字段（可选）
    table_name: Optional[str] = None
    indicator: Optional[str] = None
    period: Optional[str] = None
    unit: Optional[str] = None
    row_index: Optional[int] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(**d)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
pytest tests/test_parser.py -v
# 预期：2 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/parser/base.py tests/test_parser.py
git commit -m "feat: add Chunk dataclass (interface contract)"
```

---

## Task 2：Word/PDF 解析器（成员 A）

**Files:**

- Create: `src/parser/word_parser.py`
- Create: `src/parser/pdf_parser.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: 写 Word 解析器失败测试**

在 `tests/test_parser.py` 末尾追加：

```python
import os
from src.parser.word_parser import WordParser

def test_word_parser_returns_chunks(tmp_path):
    # 用 python-docx 创建一个测试文档
    from docx import Document
    doc = Document()
    doc.add_heading("第一章 总则", level=1)
    doc.add_heading("第一条", level=2)
    doc.add_paragraph("本办法适用于在中华人民共和国境内依法设立的商业银行。")
    test_file = tmp_path / "test.docx"
    doc.save(str(test_file))

    parser = WordParser(
        doc_id="TEST-001",
        source_title="测试办法",
        issuer="测试机构",
        doc_no="测试〔2024〕1号",
        publish_date="2024-01-01",
        source_url="https://example.com",
        local_path=str(test_file),
    )
    chunks = parser.parse()
    assert len(chunks) >= 1
    assert all(c.chunk_type == "clause" for c in chunks)
    assert all(c.doc_id == "TEST-001" for c in chunks)
    assert any("商业银行" in c.text for c in chunks)
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/test_parser.py::test_word_parser_returns_chunks -v
# 预期：ImportError
```

- [ ] **Step 3: 实现 src/parser/word_parser.py**

```python
from docx import Document
from docx.oxml.ns import qn
from typing import List
from src.parser.base import Chunk


class WordParser:
    def __init__(self, doc_id: str, source_title: str, issuer: str,
                 doc_no: str, publish_date: str, source_url: str, local_path: str):
        self.doc_id = doc_id
        self.source_title = source_title
        self.issuer = issuer
        self.doc_no = doc_no
        self.publish_date = publish_date
        self.source_url = source_url
        self.local_path = local_path

    def parse(self) -> List[Chunk]:
        doc = Document(self.local_path)
        chunks = []
        current_path = []
        buffer_text = []
        buffer_path = []

        def flush_buffer():
            if buffer_text:
                text = " ".join(buffer_text).strip()
                if text:
                    chunk_id = f"{self.doc_id}#{'#'.join(buffer_path) if buffer_path else 'body'}"
                    chunks.append(Chunk(
                        doc_id=self.doc_id,
                        chunk_id=chunk_id,
                        text=text,
                        chunk_type="clause",
                        source_title=self.source_title,
                        issuer=self.issuer,
                        doc_no=self.doc_no,
                        publish_date=self.publish_date,
                        section_path=list(buffer_path),
                        source_url=self.source_url,
                        local_path=self.local_path,
                    ))
                buffer_text.clear()

        for para in doc.paragraphs:
            style_name = para.style.name
            text = para.text.strip()
            if not text:
                continue
            if style_name.startswith("Heading"):
                flush_buffer()
                try:
                    level = int(style_name.split()[-1])
                except ValueError:
                    level = 1
                current_path = current_path[:level - 1] + [text]
                buffer_path.clear()
                buffer_path.extend(current_path)
            else:
                buffer_text.append(text)

        flush_buffer()
        return chunks
```

- [ ] **Step 4: 写 PDF 解析器失败测试**

在 `tests/test_parser.py` 末尾追加：

```python
from src.parser.pdf_parser import PdfParser

def test_pdf_parser_returns_chunks(tmp_path):
    # 创建一个最简单的 PDF 用于测试
    import fitz  # pymupdf
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "第一章 总则", fontsize=16)
    page.insert_text((50, 100), "第一条 本办法适用于商业银行。", fontsize=12)
    doc.save(str(pdf_path))
    doc.close()

    parser = PdfParser(
        doc_id="TEST-002",
        source_title="测试PDF",
        issuer="测试机构",
        doc_no="",
        publish_date="2024-01-01",
        source_url="https://example.com",
        local_path=str(pdf_path),
    )
    chunks = parser.parse()
    assert len(chunks) >= 1
    assert all(c.chunk_type == "clause" for c in chunks)
```

- [ ] **Step 5: 实现 src/parser/pdf_parser.py**

```python
import fitz  # pymupdf
from typing import List
from src.parser.base import Chunk


class PdfParser:
    HEADING_THRESHOLD = 14  # 字体大小超过此值视为标题

    def __init__(self, doc_id: str, source_title: str, issuer: str,
                 doc_no: str, publish_date: str, source_url: str, local_path: str):
        self.doc_id = doc_id
        self.source_title = source_title
        self.issuer = issuer
        self.doc_no = doc_no
        self.publish_date = publish_date
        self.source_url = source_url
        self.local_path = local_path

    def parse(self) -> List[Chunk]:
        doc = fitz.open(self.local_path)
        chunks = []
        current_path = []
        buffer_lines = []

        def flush_buffer():
            if buffer_lines:
                text = " ".join(buffer_lines).strip()
                if text:
                    chunk_id = f"{self.doc_id}#{'#'.join(current_path) if current_path else 'body'}"
                    chunks.append(Chunk(
                        doc_id=self.doc_id,
                        chunk_id=chunk_id,
                        text=text,
                        chunk_type="clause",
                        source_title=self.source_title,
                        issuer=self.issuer,
                        doc_no=self.doc_no,
                        publish_date=self.publish_date,
                        section_path=list(current_path),
                        source_url=self.source_url,
                        local_path=self.local_path,
                    ))
                buffer_lines.clear()

        for page in doc:
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if not text:
                            continue
                        if span["size"] >= self.HEADING_THRESHOLD:
                            flush_buffer()
                            current_path = [text]
                        else:
                            buffer_lines.append(text)

        flush_buffer()
        doc.close()
        return chunks
```

- [ ] **Step 6: 运行所有解析器测试**

```bash
pytest tests/test_parser.py -v
# 预期：4 passed
```

- [ ] **Step 7: Commit**

```bash
git add src/parser/word_parser.py src/parser/pdf_parser.py tests/test_parser.py
git commit -m "feat: implement Word and PDF parsers"
```

---

## Task 3：Excel 解析器（成员 A）

**Files:**

- Create: `src/parser/excel_parser.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_parser.py` 末尾追加：

```python
from src.parser.excel_parser import ExcelParser

def test_excel_parser_returns_table_chunks(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "G11资产质量"
    ws.append(["指标名称", "2024Q3", "单位"])
    ws.append(["不良贷款率", 1.56, "%"])
    ws.append(["关注类贷款率", 2.34, "%"])
    xlsx_path = tmp_path / "test.xlsx"
    wb.save(str(xlsx_path))

    parser = ExcelParser(
        doc_id="STAT-001",
        source_title="G11资产质量情况表",
        issuer="国家金融监督管理总局",
        publish_date="2024-09-30",
        source_url="https://example.com",
        local_path=str(xlsx_path),
    )
    chunks = parser.parse()
    assert len(chunks) == 2
    assert all(c.chunk_type == "table_row" for c in chunks)
    assert chunks[0].indicator == "不良贷款率"
    assert "1.56" in chunks[0].text
    assert chunks[0].period == "2024Q3"
```

- [ ] **Step 2: 运行，确认失败**

```bash
pytest tests/test_parser.py::test_excel_parser_returns_table_chunks -v
# 预期：ImportError
```

- [ ] **Step 3: 实现 src/parser/excel_parser.py**

```python
import openpyxl
from typing import List
from src.parser.base import Chunk


class ExcelParser:
    def __init__(self, doc_id: str, source_title: str, issuer: str,
                 publish_date: str, source_url: str, local_path: str):
        self.doc_id = doc_id
        self.source_title = source_title
        self.issuer = issuer
        self.publish_date = publish_date
        self.source_url = source_url
        self.local_path = local_path

    def parse(self) -> List[Chunk]:
        wb = openpyxl.load_workbook(self.local_path, data_only=True)
        chunks = []
        for sheet in wb.worksheets:
            rows = list(sheet.iter_rows(values_only=True))
            if len(rows) < 2:
                continue
            headers = [str(h).strip() if h is not None else "" for h in rows[0]]
            period = self._detect_period(headers)
            for row_idx, row in enumerate(rows[1:], start=1):
                if not any(cell for cell in row):
                    continue
                indicator = str(row[0]).strip() if row[0] else ""
                value = row[1] if len(row) > 1 else None
                unit = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                text = self._build_text(indicator, value, unit, period)
                chunk_id = f"{self.doc_id}#{sheet.title}#R{row_idx}"
                chunks.append(Chunk(
                    doc_id=self.doc_id,
                    chunk_id=chunk_id,
                    text=text,
                    chunk_type="table_row",
                    source_title=self.source_title,
                    issuer=self.issuer,
                    doc_no="",
                    publish_date=self.publish_date,
                    section_path=[],
                    source_url=self.source_url,
                    local_path=self.local_path,
                    table_name=f"{sheet.title}",
                    indicator=indicator,
                    period=period,
                    unit=unit,
                    row_index=row_idx,
                ))
        return chunks

    def _detect_period(self, headers: list) -> str:
        import re
        for h in headers:
            m = re.search(r"(20\d{2})(Q[1-4]|年[0-9]{1,2}月)", h)
            if m:
                return m.group(0)
            m = re.search(r"20\d{2}Q[1-4]", h)
            if m:
                return m.group(0)
        return ""

    def _build_text(self, indicator: str, value, unit: str, period: str) -> str:
        if value is None:
            return f"{indicator}：数据缺失"
        period_str = f"{period}，" if period else ""
        return f"{period_str}{indicator}为{value}{unit}"
```

- [ ] **Step 4: 运行全部解析测试**

```bash
pytest tests/test_parser.py -v
# 预期：5 passed
```

- [ ] **Step 5: Commit**

```bash
git add src/parser/excel_parser.py tests/test_parser.py
git commit -m "feat: implement Excel table row parser"
```

---

## Task 4：批量入库脚本（成员 A）

**Files:**

- Create: `scripts/ingest.py`
- Create: `data/chunks/.gitkeep`

- [ ] **Step 1: 创建 data 目录占位文件**

```bash
mkdir -p data/chunks data/raw data/eval
touch data/chunks/.gitkeep data/eval/.gitkeep
```

- [ ] **Step 2: 实现 scripts/ingest.py**

```python
#!/usr/bin/env python
"""
将 data/raw/ 下所有文件解析为 Chunk 并写入 data/chunks/。
用法：python scripts/ingest.py
"""
import os
import json
from pathlib import Path
from src.parser.word_parser import WordParser
from src.parser.pdf_parser import PdfParser
from src.parser.excel_parser import ExcelParser

RAW_DIR = Path("data/raw")
CHUNKS_DIR = Path("data/chunks")
MANIFEST_PATH = Path("data/manifest.json")


def load_manifest() -> list[dict]:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return []


def save_chunks(chunks: list, output_path: Path):
    with open(output_path, "a", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")


def main():
    manifest = load_manifest()
    clause_path = CHUNKS_DIR / "clause_chunks.jsonl"
    table_path = CHUNKS_DIR / "table_chunks.jsonl"
    # 清空旧文件
    clause_path.write_text("")
    table_path.write_text("")

    for entry in manifest:
        local_path = Path(entry["local_path"])
        if not local_path.exists():
            print(f"[跳过] 文件不存在: {local_path}")
            continue

        suffix = local_path.suffix.lower()
        print(f"[解析] {local_path.name}")

        common = dict(
            doc_id=entry["doc_id"],
            source_title=entry["title"],
            issuer=entry.get("issuer", ""),
            source_url=entry.get("source_url", ""),
            local_path=str(local_path),
        )

        if suffix in (".docx", ".doc"):
            parser = WordParser(
                **common,
                doc_no=entry.get("doc_no", ""),
                publish_date=entry.get("publish_date", ""),
            )
            chunks = parser.parse()
            save_chunks(chunks, clause_path)
        elif suffix == ".pdf":
            parser = PdfParser(
                **common,
                doc_no=entry.get("doc_no", ""),
                publish_date=entry.get("publish_date", ""),
            )
            chunks = parser.parse()
            save_chunks(chunks, clause_path)
        elif suffix in (".xlsx", ".xls"):
            parser = ExcelParser(
                **common,
                publish_date=entry.get("publish_date", ""),
            )
            chunks = parser.parse()
            save_chunks(chunks, table_path)
        else:
            print(f"[跳过] 不支持的格式: {suffix}")

    print(f"\n完成。clause_chunks: {clause_path}, table_chunks: {table_path}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 创建示例 manifest.json**

新建 `data/manifest.json`（仅示例，真实入库时替换为实际文件信息）：

```json
[
  {
    "doc_id": "NFRA-2023-001",
    "title": "商业银行资本管理办法",
    "issuer": "国家金融监督管理总局",
    "doc_no": "银监发〔2023〕4号",
    "publish_date": "2023-11-01",
    "source_url": "https://www.nfra.gov.cn/xxx",
    "local_path": "data/raw/商业银行资本管理办法.pdf"
  }
]
```

- [ ] **Step 4: 测试脚本可运行（用空 manifest）**

```bash
echo "[]" > data/manifest.json
python scripts/ingest.py
# 预期：完成。clause_chunks 和 table_chunks 存在但为空
```

- [ ] **Step 5: Commit**

```bash
git add scripts/ingest.py data/manifest.json data/chunks/.gitkeep data/eval/.gitkeep
git commit -m "feat: add batch ingest script and manifest"
```

---

## Task 5：Embedding 客户端（成员 B）

**Files:**

- Create: `src/indexer/embedder.py`

- [ ] **Step 1: 实现 src/indexer/embedder.py**

```python
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class Embedder:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("EMBED_MODEL", "text-embedding-3-small")

    def embed(self, text: str) -> list[float]:
        response = self.client.embeddings.create(input=text, model=self.model)
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(input=texts, model=self.model)
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
```

- [ ] **Step 2: 验证连接（需要真实 API Key）**

```bash
python -c "
from src.indexer.embedder import Embedder
e = Embedder()
vec = e.embed('商业银行不良贷款率')
print(f'向量维度: {len(vec)}')
# 预期：向量维度: 1536
"
```

- [ ] **Step 3: Commit**

```bash
git add src/indexer/embedder.py
git commit -m "feat: add OpenAI embedding client"
```

---

## Task 6：Qdrant 索引器（成员 B）

**Files:**

- Create: `src/indexer/qdrant_index.py`

- [ ] **Step 1: 实现 src/indexer/qdrant_index.py**

```python
import os
import json
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct, Filter,
    FieldCondition, MatchValue, MatchAny
)
from dotenv import load_dotenv
from src.indexer.embedder import Embedder

load_dotenv()

COLLECTION_REGULATIONS = "regulations"
COLLECTION_TABLES = "tables"
VECTOR_SIZE = 1536  # text-embedding-3-small


class QdrantIndex:
    def __init__(self):
        self.client = QdrantClient(
            host=os.environ.get("QDRANT_HOST", "localhost"),
            port=int(os.environ.get("QDRANT_PORT", 6333)),
        )
        self.embedder = Embedder()

    def create_collections(self):
        for name in [COLLECTION_REGULATIONS, COLLECTION_TABLES]:
            if not self.client.collection_exists(name):
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                )
                print(f"[创建] Collection: {name}")

    def index_chunks(self, jsonl_path: str, collection_name: str, batch_size: int = 50):
        chunks = []
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    chunks.append(json.loads(line))

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c["text"] for c in batch]
            vectors = self.embedder.embed_batch(texts)
            points = [
                PointStruct(id=idx + i, vector=vec, payload=chunk)
                for idx, (vec, chunk) in enumerate(zip(vectors, batch))
            ]
            self.client.upsert(collection_name=collection_name, points=points)
            print(f"[索引] {collection_name}: {i + len(batch)}/{len(chunks)}")

    def search(self, query: str, collection_name: str,
               filters: dict = None, top_k: int = 20) -> list[dict]:
        query_vec = self.embedder.embed(query)
        qdrant_filter = self._build_filter(filters) if filters else None
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_vec,
            query_filter=qdrant_filter,
            limit=top_k,
        )
        return [{"score": r.score, **r.payload} for r in results]

    def _build_filter(self, filters: dict) -> Filter:
        conditions = []
        for key, value in filters.items():
            if value:
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
        return Filter(must=conditions) if conditions else None
```

- [ ] **Step 2: 验证创建 Collections**

```bash
python -c "
from src.indexer.qdrant_index import QdrantIndex
idx = QdrantIndex()
idx.create_collections()
print('Collections 创建成功')
"
```

- [ ] **Step 3: Commit**

```bash
git add src/indexer/qdrant_index.py
git commit -m "feat: implement Qdrant indexer with vector search"
```

---

## Task 7：BM25 索引（成员 B）

**Files:**

- Create: `src/indexer/bm25_index.py`

- [ ] **Step 1: 实现 src/indexer/bm25_index.py**

```python
import json
import pickle
from pathlib import Path
from rank_bm25 import BM25Okapi


class BM25Index:
    def __init__(self, index_path: str = "data/bm25_index.pkl"):
        self.index_path = Path(index_path)
        self.bm25 = None
        self.chunks = []

    def build(self, jsonl_paths: list[str]):
        self.chunks = []
        for path in jsonl_paths:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.chunks.append(json.loads(line))
        tokenized = [self._tokenize(c["text"]) for c in self.chunks]
        self.bm25 = BM25Okapi(tokenized)
        self._save()
        print(f"[BM25] 构建完成，共 {len(self.chunks)} 条")

    def load(self):
        with open(self.index_path, "rb") as f:
            data = pickle.load(f)
        self.bm25 = data["bm25"]
        self.chunks = data["chunks"]

    def search(self, query: str, top_k: int = 20) -> list[dict]:
        if self.bm25 is None:
            self.load()
        tokens = self._tokenize(query)
        scores = self.bm25.get_scores(tokens)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [{"score": float(scores[i]), **self.chunks[i]} for i in top_indices if scores[i] > 0]

    def _tokenize(self, text: str) -> list[str]:
        # 中文按字切分，英文/数字按空格切分
        tokens = []
        for char in text:
            if '一' <= char <= '鿿':
                tokens.append(char)
            elif char.strip():
                tokens.append(char)
        return tokens

    def _save(self):
        self.index_path.parent.mkdir(exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump({"bm25": self.bm25, "chunks": self.chunks}, f)
```

- [ ] **Step 2: Commit**

```bash
git add src/indexer/bm25_index.py
git commit -m "feat: implement BM25 keyword index"
```

---

## Task 8：查询路由 + 混合检索 + Reranker（成员 B）

**Files:**

- Create: `src/retriever/router.py`
- Create: `src/retriever/hybrid_retriever.py`
- Create: `src/retriever/reranker.py`
- Create: `tests/test_retriever.py`

- [ ] **Step 1: 实现 src/retriever/router.py**

```python
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

QUERY_TYPES = ["regulation", "table", "hybrid", "out_of_scope"]

ROUTER_PROMPT = """你是银行业监管问答系统的查询分类器。
根据用户问题，判断应该查询哪类知识库。

返回以下之一（只返回英文标签，不要解释）：
- regulation  （制度条款、流程、定义、阈值、禁止事项）
- table       （统计数据、指标数值、报表取数）
- hybrid      （需要同时查制度和统计数据，或跨文件判断）
- out_of_scope（问题与银行业监管无关）

问题：{question}"""


class QueryRouter:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    def route(self, question: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": ROUTER_PROMPT.format(question=question)}],
            temperature=0,
            max_tokens=20,
        )
        label = response.choices[0].message.content.strip().lower()
        return label if label in QUERY_TYPES else "hybrid"
```

- [ ] **Step 2: 实现 src/retriever/reranker.py**

```python
from sentence_transformers import CrossEncoder
import os
from dotenv import load_dotenv

load_dotenv()


class Reranker:
    def __init__(self):
        model_name = os.environ.get("RERANKER_MODEL", "BAAI/bge-reranker-base")
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, chunks: list[dict], top_k: int = 5) -> list[dict]:
        if not chunks:
            return []
        pairs = [(query, c["text"]) for c in chunks]
        scores = self.model.predict(pairs)
        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in ranked[:top_k]]
```

- [ ] **Step 3: 实现 src/retriever/hybrid_retriever.py**

```python
from src.indexer.qdrant_index import QdrantIndex, COLLECTION_REGULATIONS, COLLECTION_TABLES
from src.indexer.bm25_index import BM25Index
from src.retriever.router import QueryRouter
from src.retriever.reranker import Reranker


class HybridRetriever:
    def __init__(self):
        self.qdrant = QdrantIndex()
        self.bm25 = BM25Index()
        self.router = QueryRouter()
        self.reranker = Reranker()

    def retrieve(self, query: str, query_type: str = None,
                 filters: dict = None, top_k: int = 5) -> list[dict]:
        if query_type is None:
            query_type = self.router.route(query)

        if query_type == "out_of_scope":
            return []

        # 根据类型决定搜索哪个 Collection
        if query_type == "regulation":
            collections = [COLLECTION_REGULATIONS]
        elif query_type == "table":
            collections = [COLLECTION_TABLES]
        else:  # hybrid
            collections = [COLLECTION_REGULATIONS, COLLECTION_TABLES]

        # 向量召回
        vector_results = []
        for col in collections:
            vector_results += self.qdrant.search(query, col, filters=filters, top_k=20)

        # BM25 召回
        bm25_results = self.bm25.search(query, top_k=20)

        # RRF 融合
        merged = self._rrf_merge(vector_results, bm25_results)

        # Reranker 精排
        return self.reranker.rerank(query, merged, top_k=top_k)

    def _rrf_merge(self, list_a: list[dict], list_b: list[dict], k: int = 60) -> list[dict]:
        scores = {}
        seen = {}
        for rank, item in enumerate(list_a):
            cid = item.get("chunk_id", str(rank))
            scores[cid] = scores.get(cid, 0) + 1 / (k + rank + 1)
            seen[cid] = item
        for rank, item in enumerate(list_b):
            cid = item.get("chunk_id", str(rank))
            scores[cid] = scores.get(cid, 0) + 1 / (k + rank + 1)
            seen[cid] = item
        sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)
        return [seen[cid] for cid in sorted_ids]
```

- [ ] **Step 4: 写检索器测试（用 mock 避免真实 API 调用）**

新建 `tests/test_retriever.py`：

```python
from unittest.mock import MagicMock, patch
from src.retriever.hybrid_retriever import HybridRetriever


def test_rrf_merge_combines_results():
    retriever = HybridRetriever.__new__(HybridRetriever)  # 不调用 __init__
    list_a = [
        {"chunk_id": "A", "text": "制度文本A"},
        {"chunk_id": "B", "text": "制度文本B"},
    ]
    list_b = [
        {"chunk_id": "B", "text": "制度文本B"},
        {"chunk_id": "C", "text": "表格数据C"},
    ]
    merged = retriever._rrf_merge(list_a, list_b)
    ids = [m["chunk_id"] for m in merged]
    assert "B" in ids
    assert ids.index("B") == 0  # B 在两个列表都有，RRF 分数最高


def test_retrieve_out_of_scope_returns_empty():
    retriever = HybridRetriever.__new__(HybridRetriever)
    retriever.router = MagicMock()
    retriever.router.route.return_value = "out_of_scope"
    result = retriever.retrieve("今天天气怎么样")
    assert result == []
```

- [ ] **Step 5: 运行测试**

```bash
pytest tests/test_retriever.py -v
# 预期：2 passed
```

- [ ] **Step 6: Commit**

```bash
git add src/retriever/ tests/test_retriever.py
git commit -m "feat: implement query router, hybrid retriever, reranker"
```

---

## Task 9：LLM 客户端 + Prompt 构建（成员 C）

**Files:**

- Create: `src/generator/llm_client.py`
- Create: `src/generator/prompt_builder.py`

- [ ] **Step 1: 实现 src/generator/llm_client.py**

```python
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")

    def chat(self, system: str, user: str, temperature: float = 0) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content
```

- [ ] **Step 2: 实现 src/generator/prompt_builder.py**

```python
import json

SYSTEM_PROMPT = """你是银行业监管制度问答助手。请严格依据下方提供的监管文件原文回答问题。

规则：
1. 只能使用【参考资料】中的内容作答，禁止引入外部知识
2. 涉及金额、比例、日期、机构名称、文号必须原文引用，不得改写
3. 注意区分"应当/必须""可以""不得""原则上"等规范强度词
4. 若参考资料不足以回答问题，在 refuse_reason 中说明原因，answer 留空
5. 严格按照 JSON 格式输出，不要输出其他内容

输出格式（JSON）：
{
  "answer": "答案文本，若拒答则为空字符串",
  "confidence": "high 或 medium 或 low",
  "evidence": [
    {
      "source_title": "文件名称",
      "section": "章节位置",
      "text": "原文片段",
      "source_url": "来源URL"
    }
  ],
  "refuse_reason": null
}"""


def build_user_prompt(question: str, chunks: list[dict]) -> str:
    refs = []
    for i, chunk in enumerate(chunks, 1):
        section = "·".join(chunk.get("section_path", [])) or chunk.get("table_name", "")
        refs.append(
            f"[{i}] 《{chunk.get('source_title', '')}》{section}\n"
            f"来源：{chunk.get('source_url', '')}\n"
            f"内容：{chunk.get('text', '')}"
        )
    refs_text = "\n\n".join(refs)
    return f"【参考资料】\n{refs_text}\n\n【问题】\n{question}"
```

- [ ] **Step 3: Commit**

```bash
git add src/generator/llm_client.py src/generator/prompt_builder.py
git commit -m "feat: add LLM client and prompt builder"
```

---

## Task 10：查询分解器 + 答案构建器（成员 C）

**Files:**

- Create: `src/generator/decomposer.py`
- Create: `src/generator/answer_builder.py`

- [ ] **Step 1: 实现 src/generator/decomposer.py**

```python
import json
from src.generator.llm_client import LLMClient

DECOMPOSE_PROMPT = """判断下面的问题是否需要分步查询（先查制度，再查统计数据）。

如果需要分步，将其拆分为子问题列表，每个子问题标注类型（regulation 或 table）。
如果不需要分步，返回原问题。

输出 JSON 格式：
{
  "needs_decompose": true 或 false,
  "sub_questions": [
    {"question": "子问题1", "type": "regulation"},
    {"question": "子问题2", "type": "table"}
  ]
}

问题：{question}"""


class QueryDecomposer:
    def __init__(self):
        self.llm = LLMClient()

    def decompose(self, question: str) -> list[dict]:
        response = self.llm.chat(
            system="你是一个问题分析助手，只输出 JSON。",
            user=DECOMPOSE_PROMPT.format(question=question),
        )
        try:
            data = json.loads(response)
            if data.get("needs_decompose") and data.get("sub_questions"):
                return data["sub_questions"]
        except (json.JSONDecodeError, KeyError):
            pass
        return [{"question": question, "type": "hybrid"}]
```

- [ ] **Step 2: 实现 src/generator/answer_builder.py**

```python
import json
import time
from src.generator.llm_client import LLMClient
from src.generator.prompt_builder import SYSTEM_PROMPT, build_user_prompt
from src.generator.decomposer import QueryDecomposer
from src.retriever.hybrid_retriever import HybridRetriever


class AnswerBuilder:
    def __init__(self):
        self.llm = LLMClient()
        self.retriever = HybridRetriever()
        self.decomposer = QueryDecomposer()

    def answer(self, question: str, filters: dict = None) -> dict:
        start = time.time()

        # 查询分解
        sub_questions = self.decomposer.decompose(question)

        # 逐子问题检索，合并证据
        all_chunks = []
        for sq in sub_questions:
            chunks = self.retriever.retrieve(
                query=sq["question"],
                query_type=sq.get("type"),
                filters=filters,
                top_k=5,
            )
            all_chunks.extend(chunks)

        # 去重（按 chunk_id）
        seen = set()
        unique_chunks = []
        for c in all_chunks:
            cid = c.get("chunk_id", "")
            if cid not in seen:
                seen.add(cid)
                unique_chunks.append(c)

        # 若无检索结果，直接拒答
        if not unique_chunks:
            return {
                "answer": "",
                "confidence": "low",
                "evidence": [],
                "refuse_reason": "知识库中未检索到与该问题相关的监管依据",
                "latency_ms": int((time.time() - start) * 1000),
            }

        # LLM 生成
        user_msg = build_user_prompt(question, unique_chunks[:5])
        raw = self.llm.chat(SYSTEM_PROMPT, user_msg)

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            result = {
                "answer": raw,
                "confidence": "low",
                "evidence": [],
                "refuse_reason": None,
            }

        result["latency_ms"] = int((time.time() - start) * 1000)
        return result
```

- [ ] **Step 3: Commit**

```bash
git add src/generator/decomposer.py src/generator/answer_builder.py
git commit -m "feat: add query decomposer and answer builder"
```

---

## Task 11：FastAPI 服务（成员 C）

**Files:**

- Create: `src/api/models.py`
- Create: `src/api/routes.py`
- Create: `src/api/main.py`
- Create: `tests/test_api.py`

- [ ] **Step 1: 实现 src/api/models.py**

```python
from pydantic import BaseModel
from typing import Optional, List


class AskRequest(BaseModel):
    question: str
    filters: Optional[dict] = None


class EvidenceItem(BaseModel):
    source_title: str
    section: str
    text: str
    source_url: str


class AskResponse(BaseModel):
    answer: str
    confidence: str
    evidence: List[EvidenceItem]
    refuse_reason: Optional[str] = None
    latency_ms: int


class IngestRequest(BaseModel):
    manifest_path: str = "data/manifest.json"
```

- [ ] **Step 2: 实现 src/api/routes.py**

```python
import subprocess
from fastapi import APIRouter, HTTPException
from src.api.models import AskRequest, AskResponse, IngestRequest
from src.generator.answer_builder import AnswerBuilder

router = APIRouter()
builder = AnswerBuilder()


@router.post("/ask", response_model=AskResponse)
async def ask(req: AskRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question 不能为空")
    result = builder.answer(req.question, filters=req.filters)
    return AskResponse(**result)


@router.post("/ingest")
async def ingest(req: IngestRequest):
    result = subprocess.run(
        ["python", "scripts/ingest.py"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr)
    return {"status": "ok", "output": result.stdout}


@router.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 3: 实现 src/api/main.py**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from src.api.routes import router

app = FastAPI(title="可信 RAG 银行业监管问答系统")
app.include_router(router, prefix="/api")

# 前端静态文件（build 后）
static_dir = Path("src/frontend/dist")
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    @app.get("/")
    async def serve_frontend():
        return FileResponse(str(static_dir / "index.html"))
```

- [ ] **Step 4: 写 API 测试**

新建 `tests/test_api.py`：

```python
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ask_empty_question():
    response = client.post("/api/ask", json={"question": ""})
    assert response.status_code == 400


def test_ask_returns_structured_response():
    mock_result = {
        "answer": "资本充足率不得低于10.5%。",
        "confidence": "high",
        "evidence": [
            {
                "source_title": "商业银行资本管理办法",
                "section": "第三章第十二条",
                "text": "资本充足率不得低于10.5%",
                "source_url": "https://example.com",
            }
        ],
        "refuse_reason": None,
        "latency_ms": 800,
    }
    with patch("src.api.routes.builder.answer", return_value=mock_result):
        response = client.post("/api/ask", json={"question": "资本充足率要求是多少？"})
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "资本充足率不得低于10.5%。"
    assert data["confidence"] == "high"
    assert len(data["evidence"]) == 1
```

- [ ] **Step 5: 运行 API 测试**

```bash
pytest tests/test_api.py -v
# 预期：3 passed
```

- [ ] **Step 6: 手动启动验证**

```bash
uvicorn src.api.main:app --reload
# 浏览器打开 http://localhost:8000/api/health
# 预期：{"status":"ok"}
```

- [ ] **Step 7: Commit**

```bash
git add src/api/ tests/test_api.py
git commit -m "feat: add FastAPI service with ask/ingest/health routes"
```

---

## Task 12：React 前端（成员 C）

**Files:**

- Create: `src/frontend/package.json`
- Create: `src/frontend/vite.config.js`
- Create: `src/frontend/index.html`
- Create: `src/frontend/src/App.jsx`
- Create: `src/frontend/src/api/client.js`
- Create: `src/frontend/src/components/ChatInput.jsx`
- Create: `src/frontend/src/components/MessageList.jsx`
- Create: `src/frontend/src/components/AnswerCard.jsx`
- Create: `src/frontend/src/components/EvidencePanel.jsx`

- [ ] **Step 1: 初始化前端项目**

```bash
cd src/frontend
npm create vite@latest . -- --template react
npm install
```

- [ ] **Step 2: 配置 vite.config.js（代理 API）**

```js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

- [ ] **Step 3: 实现 src/frontend/src/api/client.js**

```js
export async function askQuestion(question, filters = null) {
  const response = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, filters }),
  })
  if (!response.ok) {
    const err = await response.json()
    throw new Error(err.detail || '请求失败')
  }
  return response.json()
}
```

- [ ] **Step 4: 实现 EvidencePanel.jsx**

```jsx
import { useState } from 'react'

export default function EvidencePanel({ evidence }) {
  const [open, setOpen] = useState(false)
  if (!evidence || evidence.length === 0) return null
  return (
    <div style={{ marginTop: 8 }}>
      <button onClick={() => setOpen(!open)} style={{ cursor: 'pointer', background: 'none', border: '1px solid #ccc', borderRadius: 4, padding: '2px 8px', fontSize: 12 }}>
        {open ? '▲' : '▼'} 证据来源 ({evidence.length})
      </button>
      {open && (
        <div style={{ marginTop: 6, paddingLeft: 12, borderLeft: '3px solid #1890ff' }}>
          {evidence.map((e, i) => (
            <div key={i} style={{ marginBottom: 10, fontSize: 13 }}>
              <div><strong>《{e.source_title}》</strong> · {e.section}</div>
              <div style={{ color: '#555', margin: '2px 0' }}>"{e.text}"</div>
              <a href={e.source_url} target="_blank" rel="noreferrer" style={{ color: '#1890ff', fontSize: 12 }}>查看原文</a>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 5: 实现 AnswerCard.jsx**

```jsx
import EvidencePanel from './EvidencePanel'

const confidenceColor = { high: '#52c41a', medium: '#faad14', low: '#ff4d4f' }
const confidenceLabel = { high: '高', medium: '中', low: '低' }

export default function AnswerCard({ message }) {
  if (message.role === 'user') {
    return (
      <div style={{ textAlign: 'right', margin: '8px 0' }}>
        <span style={{ background: '#1890ff', color: '#fff', borderRadius: 12, padding: '6px 14px', display: 'inline-block', maxWidth: '70%' }}>
          {message.content}
        </span>
      </div>
    )
  }
  const { answer, confidence, evidence, refuse_reason } = message.content
  return (
    <div style={{ margin: '8px 0', padding: 12, background: '#f5f5f5', borderRadius: 8, maxWidth: '80%' }}>
      {refuse_reason ? (
        <div style={{ color: '#ff4d4f' }}>⚠️ {refuse_reason}</div>
      ) : (
        <>
          <div style={{ marginBottom: 6 }}>
            <span style={{ background: confidenceColor[confidence], color: '#fff', borderRadius: 4, padding: '1px 6px', fontSize: 11, marginRight: 6 }}>
              置信度·{confidenceLabel[confidence]}
            </span>
          </div>
          <div style={{ lineHeight: 1.7 }}>{answer}</div>
          <EvidencePanel evidence={evidence} />
        </>
      )}
    </div>
  )
}
```

- [ ] **Step 6: 实现 ChatInput.jsx**

```jsx
import { useState } from 'react'

export default function ChatInput({ onSend, loading }) {
  const [value, setValue] = useState('')
  const submit = () => {
    if (!value.trim() || loading) return
    onSend(value.trim())
    setValue('')
  }
  return (
    <div style={{ display: 'flex', gap: 8, padding: 12, borderTop: '1px solid #eee' }}>
      <input
        value={value}
        onChange={e => setValue(e.target.value)}
        onKeyDown={e => e.key === 'Enter' && submit()}
        placeholder="输入监管制度问题，按 Enter 发送..."
        style={{ flex: 1, padding: '8px 12px', borderRadius: 6, border: '1px solid #d9d9d9', fontSize: 14 }}
        disabled={loading}
      />
      <button onClick={submit} disabled={loading || !value.trim()} style={{ padding: '8px 20px', borderRadius: 6, background: '#1890ff', color: '#fff', border: 'none', cursor: 'pointer' }}>
        {loading ? '...' : '发送'}
      </button>
    </div>
  )
}
```

- [ ] **Step 7: 实现 MessageList.jsx**

```jsx
import AnswerCard from './AnswerCard'

export default function MessageList({ messages }) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
      {messages.length === 0 && (
        <div style={{ textAlign: 'center', color: '#aaa', marginTop: 60 }}>
          输入银行业监管制度相关问题开始问答
        </div>
      )}
      {messages.map((msg, i) => <AnswerCard key={i} message={msg} />)}
    </div>
  )
}
```

- [ ] **Step 8: 实现 App.jsx**

```jsx
import { useState } from 'react'
import MessageList from './components/MessageList'
import ChatInput from './components/ChatInput'
import { askQuestion } from './api/client'

export default function App() {
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(false)

  const handleSend = async (question) => {
    setMessages(prev => [...prev, { role: 'user', content: question }])
    setLoading(true)
    try {
      const result = await askQuestion(question)
      setMessages(prev => [...prev, { role: 'assistant', content: result }])
    } catch (err) {
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: { answer: '', confidence: 'low', evidence: [], refuse_reason: err.message }
      }])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', maxWidth: 800, margin: '0 auto', fontFamily: 'sans-serif' }}>
      <div style={{ padding: 16, borderBottom: '1px solid #eee', fontWeight: 'bold', fontSize: 18 }}>
        银行业监管制度问答系统
      </div>
      <MessageList messages={messages} />
      <ChatInput onSend={handleSend} loading={loading} />
    </div>
  )
}
```

- [ ] **Step 9: 本地联调验证**

```bash
# 终端 1：启动后端
uvicorn src.api.main:app --reload

# 终端 2：启动前端
cd src/frontend && npm run dev
# 浏览器打开 http://localhost:5173
# 测试发送一个问题，确认页面渲染正常
```

- [ ] **Step 10: 构建并集成到后端**

```bash
cd src/frontend && npm run build
# 构建产物在 src/frontend/dist/
# 重启后端后，浏览器打开 http://localhost:8000 应能看到前端页面
```

- [ ] **Step 11: Commit**

```bash
cd ../..
git add src/frontend/
git commit -m "feat: add React chat UI with evidence panel"
```

---

## Task 13：评测脚本（成员 C）

**Files:**

- Create: `scripts/run_eval.py`
- Create: `data/eval/qa_seed.jsonl`（示例）

- [ ] **Step 1: 创建示例评测集 data/eval/qa_seed.jsonl**

每行一条，格式如下（补充真实问答对）：

```jsonl
{"id": "Q001", "question": "商业银行资本充足率监管要求是多少？", "answer": "不得低于10.5%", "source_title": "商业银行资本管理办法", "qa_type": "threshold", "difficulty": "easy"}
{"id": "Q002", "question": "不良贷款的认定标准是什么？", "answer": "借款人逾期90天以上的贷款应归入不良", "source_title": "商业银行金融资产风险分类办法", "qa_type": "definition", "difficulty": "medium"}
```

- [ ] **Step 2: 实现 scripts/run_eval.py**

```python
#!/usr/bin/env python
"""
对评测集跑问答，输出 eval_report.json。
用法：python scripts/run_eval.py
"""
import json
import os
import re
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from src.generator.answer_builder import AnswerBuilder

load_dotenv()

QA_PATH = Path("data/eval/qa_seed.jsonl")
REPORT_PATH = Path("data/eval/eval_report.json")

judge_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"],
    base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)


def llm_judge(question: str, expected: str, actual: str) -> bool:
    prompt = f"""判断以下答案是否与标准答案意思相符（关键数字和事实必须一致）。
只回复 YES 或 NO。

问题：{question}
标准答案：{expected}
实际答案：{actual}"""
    resp = judge_client.chat.completions.create(
        model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0, max_tokens=5,
    )
    return resp.choices[0].message.content.strip().upper() == "YES"


def main():
    builder = AnswerBuilder()
    qa_items = []
    with open(QA_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                qa_items.append(json.loads(line))

    results = []
    correct = 0

    for item in qa_items:
        print(f"[评测] {item['id']}: {item['question'][:30]}...")
        result = builder.answer(item["question"])
        is_correct = llm_judge(item["question"], item["answer"], result.get("answer", ""))
        if is_correct:
            correct += 1
        results.append({
            "id": item["id"],
            "question": item["question"],
            "expected": item["answer"],
            "actual": result.get("answer", ""),
            "correct": is_correct,
            "confidence": result.get("confidence"),
            "refuse_reason": result.get("refuse_reason"),
            "latency_ms": result.get("latency_ms"),
        })

    total = len(qa_items)
    report = {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0,
        "results": results,
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n评测完成：{correct}/{total}，准确率 {report['accuracy']:.1%}")
    print(f"报告保存至：{REPORT_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run_eval.py data/eval/qa_seed.jsonl
git commit -m "feat: add evaluation script with LLM-as-Judge"
```

---

## Task 14：README + 完整集成验证（队长 + 所有人）

**Files:**

- Create: `README.md`
- Modify: `.gitignore`

- [ ] **Step 1: 创建 .gitignore**

```
.env
__pycache__/
*.pyc
*.pkl
data/raw/
src/frontend/node_modules/
src/frontend/dist/
.venv/
```

- [ ] **Step 2: 创建 README.md**

```markdown
# 可信 RAG 银行业监管问答系统

面向银行业监管制度与统计报表的检索增强生成（RAG）问答系统。

## 快速启动

### 1. 安装依赖
```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入 OPENAI_API_KEY 等
```

### 3. 启动 Qdrant

```bash
docker compose up -d
```

### 4. 构建知识库

```bash
# 编辑 data/manifest.json，填入文件信息
python scripts/ingest.py
# 然后运行向量入库
python -c "
from src.indexer.qdrant_index import QdrantIndex
idx = QdrantIndex()
idx.create_collections()
idx.index_chunks('data/chunks/clause_chunks.jsonl', 'regulations')
idx.index_chunks('data/chunks/table_chunks.jsonl', 'tables')
from src.indexer.bm25_index import BM25Index
bm25 = BM25Index()
bm25.build(['data/chunks/clause_chunks.jsonl', 'data/chunks/table_chunks.jsonl'])
"
```

### 5. 启动服务

```bash
uvicorn src.api.main:app --reload
```

### 6. 打开前端

浏览器访问 http://localhost:8000

### 7. 运行评测

```bash
python scripts/run_eval.py
# 报告输出至 data/eval/eval_report.json
```

## 运行测试

```bash
pytest tests/ -v
```

## 目录说明

- `src/parser/` — 文档解析层
- `src/indexer/` — 向量索引层
- `src/retriever/` — 混合检索层
- `src/generator/` — 生成层
- `src/api/` — FastAPI 服务
- `src/frontend/` — React 前端
- `scripts/` — 批量处理脚本
- `data/chunks/` — 解析后的结构化知识库
- `data/eval/` — 评测集和报告

```
- [ ] **Step 3: 端到端验证清单**

```bash
# 1. 所有单元测试通过
pytest tests/ -v

# 2. ingest 脚本可运行
python scripts/ingest.py

# 3. API 健康检查
curl http://localhost:8000/api/health

# 4. 问答接口返回结构化结果
curl -X POST http://localhost:8000/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"商业银行资本充足率要求是多少？"}'

# 5. 前端页面可以正常交互（浏览器打开 http://localhost:8000）

# 6. 评测脚本输出报告
python scripts/run_eval.py
```

- [ ] **Step 4: 最终提交 Commit**

```bash
git add README.md .gitignore
git commit -m "docs: add README and finalize project"

# 合入 dev 分支
git checkout dev
git merge feature/generator
git merge feature/parser
git merge feature/retriever
git push origin dev
```

---

## 里程碑检查表

| 里程碑    | Task       | 负责人        | 验收标准                          |
| --------- | ---------- | ------------- | --------------------------------- |
| 第 1 周末 | Task 0–1   | 全员          | 环境跑通，Chunk 结构锁定          |
| 第 2 周末 | Task 2–4   | 成员 A        | 100 份文件全部解析入 JSONL        |
| 第 2 周末 | Task 5–8   | 成员 B        | `retrieve()` 可返回 Top-5 chunks  |
| 第 2 周末 | Task 9–11  | 成员 C        | `/api/ask` 返回带 evidence 的答案 |
| 第 3 周末 | Task 12    | 成员 C        | 前端问答页面可正常交互            |
| 第 3 周末 | —          | 全员          | 端到端 3 条验证路径全通           |
| 第 4 周末 | Task 13–14 | 成员 C + 队长 | 评测准确率 ≥ 85%，README 完整     |
