from unittest.mock import Mock

import pytest

from src.generator.decomposer import QueryDecomposer


@pytest.mark.parametrize(
    ("question", "expected_type"),
    [
        ("根据 Excel 工作表，全国合计到健康险的数值变化是多少？", "table"),
        ("根据《消费金融公司管理办法》，下列哪项表述正确？", "regulation"),
        (
            "根据《寿险合同负债评估折现率曲线》，下列哪项表述正确？\n"
            "A. 计算现金流现值时采用某曲线\nB. 统计数据发生变化",
            "regulation",
        ),
        ("根据监管规定和统计数据，计算该指标是否达标。", "hybrid"),
    ],
)
def test_decomposer_routes_clear_questions_without_llm(question, expected_type):
    decomposer = QueryDecomposer()
    decomposer.llm.chat = Mock(side_effect=AssertionError("明确问题不应调用模型"))

    result = decomposer.decompose(question)

    assert result == [{"question": question, "type": expected_type}]
    assert decomposer.last_decision_method == "rule"
