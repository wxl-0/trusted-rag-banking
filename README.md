# 可信 RAG 银行业监管问答系统

面向银行业监管制度与统计报表的检索增强生成（RAG）问答系统。
第五届中国研究生金融科技创新大赛 · 南京银行赛题

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
python scripts/ingest.py
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
```

## 运行测试
```bash
pytest tests/ -v
```

## 分工
| 成员 | 负责模块 |
|---|---|
| 成员 A | `src/parser/` + `scripts/ingest.py` |
| 成员 B | `src/indexer/` + `src/retriever/` |
| 成员 C | `src/generator/` + `src/api/` + `src/frontend/` + `scripts/run_eval.py` |
