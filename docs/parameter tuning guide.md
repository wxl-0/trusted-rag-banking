# 参数调优指南

本文说明系统中影响评测指标的关键参数位置及调整策略。

---

## 一、关键参数总览

### 1. 检索数量 `top_k`
**文件：** `src/retriever/hybrid_retriever.py`  
**影响指标：** 证据引用命中率（目标 ≥90%）

```python
vector_results += self.qdrant.search(query, col, filters=filters, top_k=20)  # 向量召回数量
bm25_results = self.bm25.search(query, top_k=20)                              # BM25 召回数量
return self.reranker.rerank(query, merged, top_k=top_k)                       # 最终传给LLM的数量（默认5）
```

- 召回阶段 `top_k=20`：越大命中率越高，但速度变慢
- 精排后 `top_k=5`：传给生成层的最终数量，可调整为 3～8
- **建议：** 命中率不达标时，先把召回阶段改为 `top_k=30`

---

### 2. 生成温度 `temperature`
**文件：** `src/generator/llm_client.py`  
**影响指标：** 关键字段错误率（目标 ≤5%）、幻觉率

```python
def chat(self, system: str, user: str, temperature: float = 0) -> str:
```

- 保持 `temperature=0`，输出最稳定，不要修改
- 温度越高，模型越"发散"，数字/文号出错概率上升

---

### 3. System Prompt 规则
**文件：** `src/generator/prompt_builder.py`  
**影响指标：** 所有指标，影响最大

```
规则：
1. 只能使用【参考资料】中的内容作答，禁止引入外部知识
2. 涉及金额、比例、日期、机构名称、文号必须原文引用，不得改写
3. 注意区分"应当/必须""可以""不得""原则上"等规范强度词
4. 若参考资料不足以回答问题，在 refuse_reason 中说明原因，answer 留空
5. 严格按照 JSON 格式输出，不要输出其他内容
```

- 规则措辞越严，拒答率越高、幻觉越少
- 后期某类指标不达标，**优先在这里调整**

---

### 4. 使用的模型
**文件：** `.env`  
**影响指标：** 制度事实准确率（目标 ≥85%）、表格取数准确率（目标 ≥80%）

```
LLM_MODEL=gpt-4o-mini    # 默认，成本低
LLM_MODEL=gpt-4o         # 准确率更高，约贵10倍
```

- 模型是准确率的最大影响因素
- 开发阶段用 `gpt-4o-mini`，评测冲指标时可换 `gpt-4o`

---

## 二、调优策略

先跑评测脚本，看哪项指标不达标，再针对性调整：

```bash
python scripts/run_eval.py --limit 50
```

| 指标不达标 | 调整位置 |
|---|---|
| 证据引用命中率低 | 加大召回 `top_k`（20→30） |
| 关键字段错误多 | 加强 Prompt 规则第2条 |
| 拒答率不够 | 加强 Prompt 规则第4条 |
| 准确率整体偏低 | 换 `LLM_MODEL=gpt-4o` |
| 表格取数错误 | 检查 Excel 解析是否保留了单位和表头 |

---

## 三、RRF 融合参数（进阶）

**文件：** `src/retriever/hybrid_retriever.py`

```python
def _rrf_merge(self, list_a, list_b, k: int = 60) -> list[dict]:
```

- `k=60` 是 RRF 的标准值，控制向量检索和 BM25 的融合权重
- 一般不需要调整；若想加强 BM25 权重可以降低 `k` 值
