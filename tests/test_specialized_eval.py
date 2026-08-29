from pathlib import Path

import pytest

from scripts.specialized_eval.run_eval import (
    classify_behavior,
    evidence_item_match,
    entity_match,
    load_dataset,
    score_result,
    source_match,
)


DATASET_PATH = "data/eval/银行监管RAG专项评测集_100题.xlsx"


def test_specialized_workbook_is_authoritative_100_question_dataset():
    if not Path(DATASET_PATH).exists():
        pytest.skip("私有 100 题专项评测集未包含在仓库中")
    items = load_dataset(DATASET_PATH)
    assert len(items) == 100
    assert sum(item["category"] == "关键实体" for item in items) == 50
    assert sum(item["category"] == "库外处理" for item in items) == 30
    cross = [item for item in items if item["category"] == "跨文件"]
    assert len(cross) == 20
    assert {item["subtype"] for item in cross} == {"两个Excel跨期比较/计算"}
    assert all(len(item["expected_evidence"]) == 2 for item in cross)


def test_numeric_entity_uses_explicit_tolerance():
    entity = {"type": "数字", "value": 11.0, "tolerance": 0.01, "match": "numeric"}
    assert entity_match(entity, "核心一级资本充足率为11.00%。")
    assert not entity_match(entity, "一级资本充足率为12.57%。")


def test_integer_entity_accepts_chinese_number_with_matching_unit():
    assert entity_match(
        {"type": "数字", "value": 3, "unit": "年", "tolerance": 0, "match": "numeric"},
        "该项安排连续实施三年。",
    )
    assert entity_match(
        {"type": "数字", "value": 1, "unit": "个函证基准日", "tolerance": 0, "match": "numeric"},
        "一份询证函只能列示一个函证基准日。",
    )


def test_integer_entity_rejects_chinese_number_with_wrong_unit():
    entity = {"type": "数字", "value": 3, "unit": "年", "tolerance": 0, "match": "numeric"}
    assert not entity_match(entity, "文件列出了三个条件。")


def test_behavior_distinguishes_refusal_and_clarification():
    assert classify_behavior({"answer": "", "refuse_reason": "资料不足"}) == "refuse"
    assert classify_behavior({"answer": "请补充年份和季度。", "refuse_reason": None}) == "clarify"
    assert classify_behavior({"behavior": "refuse", "answer": "请补充年份。", "refuse_reason": "资料不足"}) == "refuse"


def test_source_title_accepts_suffix_and_alias():
    assert source_match(
        "2023年商业银行主要监管指标情况表（季度）",
        "2023年商业银行主要监管指标情况表（季度） 商业银行主要监管指标情况表(季度)（2023年）",
    )
    assert source_match("2024年9月财产保险公司经营情况表", "2024年9月财产险公司经营情况表")


def test_cross_file_question_requires_all_expected_sources_for_question_pass():
    item = {
        "category": "跨文件",
        "expected_behavior": "回答",
        "critical_entities": [{"type": "数字", "value": 11.0, "tolerance": 0.01, "match": "numeric"}],
        "expected_sources": ["文件A", "文件B"],
        "expected_evidence": [
            {"source_title": "文件A", "items": [{"cell_ref": "E42", "period": "2024", "indicator": "核心一级资本充足率", "value": 11.0, "tolerance": 0.01}]},
            {"source_title": "文件B", "items": [{"text_terms": ["监管阈值"]}]},
        ],
        "forbidden_values": [],
    }
    result = {
        "behavior": "answer",
        "answer": "结果为11.00%。",
        "refuse_reason": None,
        "evidence": [{"source_title": "文件A", "section": "单元格 E42；期间2024", "text": "核心一级资本充足率为11.00%。"}],
    }
    score = score_result(item, result)
    assert score["answer_correct"] is True
    assert score["evidence_complete"] is False
    assert score["is_correct"] is False


def test_exact_evidence_rejects_wrong_quarter_cell_in_same_file():
    requirement = {
        "cell_ref": "E42",
        "period": "2024",
        "indicator": "核心一级资本充足率",
        "value": 11.0,
        "tolerance": 0.01,
    }
    wrong = {
        "section": "商业银行季度，单元格 D42",
        "text": "行指标「核心一级资本充足率」；列口径「三季度」；原始值为10.86%；期间：2024。",
    }
    correct = {
        "section": "商业银行季度，单元格 E42",
        "text": "行指标「核心一级资本充足率」；列口径「四季度」；原始值为11.00%；期间：2024。",
    }
    assert not evidence_item_match(requirement, wrong)
    assert evidence_item_match(requirement, correct)


def test_labeled_numeric_entities_reject_swapped_similar_metrics():
    core = {
        "type": "数字", "value": 11.0, "tolerance": 0.01, "match": "numeric",
        "context_patterns": [r"核心一级资本充足率"],
    }
    tier_one = {
        "type": "数字", "value": 12.57, "tolerance": 0.01, "match": "numeric",
        "context_patterns": [r"(?<!核心)一级资本充足率"],
    }
    correct = "核心一级资本充足率为11.00%；一级资本充足率为12.57%。"
    swapped = "核心一级资本充足率为12.57%；一级资本充足率为11.00%。"
    assert entity_match(core, correct) and entity_match(tier_one, correct)
    assert not entity_match(core, swapped)
    assert not entity_match(tier_one, swapped)
