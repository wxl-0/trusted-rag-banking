# Bad Case 回归集

本目录把已经有公开证据的历史错误与人工发现的问题整理为独立回归资产，用于形成“发现问题—定位层级—通用修复—回归验证”的可追溯闭环。它不替代或改写官方评测集、100 题专项评测集及其正式报告。

## 文件

- `bad_cases.jsonl`：每行一个可追溯案例。
- `source_hashes.json`：建立回归集时四个上游评测资产的 SHA-256，用于防止回归整理过程静默修改正式资产。
- `verification_2026-08-29.json`：本轮清空上传数据、直接恢复基线索引后，对 24 个案例执行的轻量验证记录；只保存结果摘要、基线哈希与命令，不复制正式报告正文。

## 状态口径

| 状态 | 含义 |
|---|---|
| `fixed` | Git 中存在明确修复提交，且当前仓库有对应自动化测试 |
| `snapshot_failed` | 在已发布评测快照中确定失败，但没有在当前任务中重新调用模型验证，不能宣称当前仍失败或已经修复 |
| `open` | 当前已复现和定位到故障层级，但尚未完成通用修复与自动化回归 |

`snapshot_failed` 特意与 `open` 分开：模型、检索代码和索引都可能在报告发布后变化，旧报告只能证明当时失败。即使当前隔离重跑通过，也不能在缺少明确修复提交和定向自动化测试时直接改成 `fixed`；当前验证结果单独写入 verification 文件。

## 分层运行

先校验回归资产本身，不调用模型：

```bash
uv run --frozen python -m pytest tests/test_bad_case_regression_dataset.py -q
```

历史已修复案例直接运行记录中的 `regression.command`。例如：

```bash
uv run --frozen python -m pytest \
  tests/test_decomposer.py::test_decomposer_rewrites_context_dependent_follow_up_for_retrieval \
  tests/test_answer_builder.py::test_answer_supplements_only_missing_table_target_once \
  -q
```

正式评测失败快照使用原有隔离运行方式，不覆盖正式报告：

```bash
uv run --frozen python scripts/run_eval.py \
  --ids Q094,Q140,Q237,Q245,Q251,Q255,Q261,Q276 \
  --run-name bad-case-official-rerun
```

专项评测失败快照同样写入独立运行目录，禁止附加 `--publish`：

```bash
uv run --frozen python scripts/specialized_eval/run_eval.py \
  --ids S012,S013,S029,S033,S049,S074,S075,S094,S097,S099 \
  --run-name bad-case-specialized-rerun
```

上述两个命令会调用外部模型，只能在凭据、依赖和数据基线明确时运行。单条修复应先跑定向案例和对应单元测试，再跑相关评测子集；阶段性收口时才跑完整官方与专项评测，并分别报告结果。

## 2026-08-29 当前验证

本轮先清空维护入口产生的 PostgreSQL 知识文档事实、MinIO 对象、动态 BM25 代际、Redis 状态和上传向量，再直接恢复仓库已有的 Qdrant Snapshot 与 BM25 索引。恢复后法规 Collection 为 8,945 点、表格 Collection 为 29,561 点，BM25 为 38,506 条，上传版本向量为 0。

| 分组 | 当前通过 | 当前失败 | 执行错误 |
|---|---:|---:|---:|
| 5 个历史 `fixed` 案例（8 条定向测试） | 5 | 0 | 0 |
| 8 个官方历史失败快照 | 4 | 4 | 0 |
| 10 个专项历史失败快照 | 3 | 7 | 0 |
| 1 个当前多轮案例 | 0 | 1 | 0 |
| 合计 | 12 | 12 | 0 |

官方当前通过 Q094、Q237、Q251、Q276，仍失败 Q140、Q245、Q255、Q261。专项当前通过 S013、S049、S075，其余 7 题仍失败。多轮案例仍能复现：上下文改写已识别“它们”为总资产和总负债，但没有拆成四个操作数；同时纯基线表格 Chunk 缺少 2 月的两个绝对值。逐例结果与索引哈希见 `verification_2026-08-29.json`。

## 新增与修复规则

1. 先保存问题、历史、预期行为、必要证据和实际表现，再修改代码。
2. 先判断错误属于解析、来源限定、检索、上下文改写、生成、计算、准入控制还是评测适配层。
3. 修复必须覆盖一类问题，不为单个题号或固定问句硬编码答案。
4. 修复完成后添加自动化测试，把状态改为 `fixed`，写入完整提交哈希和测试节点。
5. 不把健康检查、一次人工成功或模型主观判断当作回归通过。
6. 不在回归集中保存令牌、密码、原始私有资料、对象存储地址或完整内部异常。

## 当前规模

- 5 个有 Git 测试证据的历史已修复案例。
- 8 个官方评测失败快照。
- 10 个专项评测失败快照。
- 1 个当前待修复的多轮表格追问案例。

共 24 个案例。面试叙事应优先使用已有修复提交与回归测试的 `fixed` 案例；`snapshot_failed` 和 `open` 只能描述为已发现或待验证，不能包装为已解决。

## 可用于面试复盘的已修复案例

| 案例 | 发现的问题 | 通用修复 | 回归证据 |
|---|---|---|---|
| `FIXED-CONTEXT-001` | “那发送和收回呢”缺少主语和来源，无法稳定检索 | 使用受控对话历史把追问改写为包含来源标题和完整语义的问题 | `test_decomposer_rewrites_context_dependent_follow_up_for_retrieval` |
| `FIXED-TABLE-001` | 两个操作数只召回一个 | 将计算题拆成独立目标，只对缺失目标补搜一次 | `test_answer_supplements_only_missing_table_target_once` |
| `FIXED-EVIDENCE-001` | 多事实问题遗漏初排第4位的必要证据 | 扩展并按目标汇总候选证据，再做覆盖判断 | `test_answer_multi_fact_uses_relevant_evidence_ranked_after_third` |
| `FIXED-PARSER-001` | Excel 合并行、空白承接行导致指标或季度丢失 | 解析时继承分组行标签，并保留季度与重复区块路径 | 两个 `test_parser_real_data.py` 回归测试 |
| `FIXED-CALC-001` | 变化计算依赖模型自由运算，缺操作数时仍可能生成 | 双操作数齐备后执行确定性计算；缺任一值直接拒绝 | `test_answer_builds_deterministic_change_with_both_values_and_formula` |

面试中应按“现象—证据排除—根因层级—通用修复—回归结果”讲述，而不是只说调了 Prompt。修复提交和测试节点均记录在对应 JSONL 条目中。
