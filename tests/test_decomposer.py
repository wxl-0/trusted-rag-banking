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

    assert len(result) == 1
    assert result[0]["question"] == question
    assert result[0]["type"] == expected_type
    assert result[0]["target_id"] == "main"
    assert decomposer.last_decision_method == "rule"


def test_decomposer_splits_table_change_into_two_lookup_targets():
    question = (
        "需要对同一 Excel 附件做两处取数并计算。"
        "根据《2023年12月全国各地区原保险保费收入情况表》，"
        "“全国合计”从“合计”到“健康险”的数值变化约为多少？"
    )
    decomposer = QueryDecomposer()
    decomposer.llm.chat = Mock(side_effect=AssertionError("明确计算题不应调用模型"))

    result = decomposer.decompose(question)

    assert result == [
        {
            "target_id": "operand_1",
            "label": "全国合计 / 合计",
            "question": "《2023年12月全国各地区原保险保费收入情况表》 全国合计 合计",
            "type": "table",
            "source_title": "2023年12月全国各地区原保险保费收入情况表",
            "filters": {},
            "strict_filters": {"row_label": "全国合计", "column_header": "合计"},
            "coverage_terms": ["全国合计", "合计"],
        },
        {
            "target_id": "operand_2",
            "label": "全国合计 / 健康险",
            "question": "《2023年12月全国各地区原保险保费收入情况表》 全国合计 健康险",
            "type": "table",
            "source_title": "2023年12月全国各地区原保险保费收入情况表",
            "filters": {},
            "strict_filters": {"row_label": "全国合计", "column_header": "健康险"},
            "coverage_terms": ["全国合计", "健康险"],
        },
    ]
    assert decomposer.last_decision_method == "rule"
    assert decomposer.last_route == "table"


def test_decomposer_splits_table_comparison_by_option_and_column():
    question = (
        "根据 Excel 附件《2023年4季度保险业资金运用情况表》"
        "（工作表：2023年4季度保险资金运用情况表），"
        "在“截至当期-账面余额”口径下，以下哪一项数值最高？\n"
        "A. 年化综合收益率\n"
        "B. 年化财务收益率\n"
        "C. 资金运用余额\n"
        "D. 银行存款"
    )
    decomposer = QueryDecomposer()
    decomposer.llm.chat = Mock(side_effect=AssertionError("明确比较题不应调用模型"))

    result = decomposer.decompose(question)

    assert len(result) == 4
    assert result[0] == {
        "target_id": "option_A",
        "label": "A. 年化综合收益率",
        "question": (
            "《2023年4季度保险业资金运用情况表》 "
            "工作表 2023年4季度保险资金运用情况表 "
            "截至当期-账面余额 年化综合收益率"
        ),
        "type": "table",
        "source_title": "2023年4季度保险业资金运用情况表",
        "filters": {},
        "strict_filters": {
            "table_name": "2023年4季度保险资金运用情况表",
            "indicator": "年化综合收益率",
            "column_header": "截至当期-账面余额",
        },
        "coverage_terms": ["年化综合收益率", "截至当期-账面余额"],
        "option": "A",
    }
    assert result[-1]["target_id"] == "option_D"
    assert result[-1]["strict_filters"]["indicator"] == "银行存款"


def test_decomposer_splits_multi_fact_options_into_unique_claims():
    shared = "意外伤害保险以意外伤害造成死亡或者伤残为给付条件。"
    question = (
        "关于《意外伤害保险业务监管办法》，"
        "下列哪一组选项中的两项表述均属于该材料内容？\n"
        f"A. {shared}；基础利率曲线由三段组成。\n"
        f"B. {shared}；移动平均曲线适用于0年到20年。\n"
        f"C. {shared}；保险公司厘定保险费应采用公平、合理的定价假设。\n"
        f"D. {shared}；折现率曲线由基础利率曲线加综合溢价形成。"
    )
    decomposer = QueryDecomposer()
    decomposer.llm.chat = Mock(side_effect=AssertionError("明确多事实题不应调用模型"))

    result = decomposer.decompose(question)

    assert len(result) == 5
    assert result[0] == {
        "target_id": "claim_1",
        "label": f"选项 A/B/C/D：{shared}",
        "question": f"《意外伤害保险业务监管办法》 {shared}",
        "type": "regulation",
        "source_title": "意外伤害保险业务监管办法",
        "filters": {},
        "strict_filters": {},
        "coverage_terms": [shared],
        "options": ["A", "B", "C", "D"],
    }
    assert result[3]["options"] == ["C"]
    assert "公平、合理的定价假设" in result[3]["question"]


def test_decomposer_keeps_single_fact_question_with_source_title_hint():
    question = (
        "检索《应当编报保险集团偿付能力报告的公司名单》后，"
        "以下哪一项与材料内容一致？\n"
        "A. 其他材料内容\nB. 另一项内容\nC. 无关内容\nD. 名单内集团应编报报告"
    )
    decomposer = QueryDecomposer()
    decomposer.llm.chat = Mock(side_effect=AssertionError("明确制度题不应调用模型"))

    result = decomposer.decompose(question)

    assert result == [{
        "target_id": "main",
        "label": "检索《应当编报保险集团偿付能力报告的公司名单》后，以下哪一项与材料内容一致？",
        "question": question,
        "type": "regulation",
        "source_title": "应当编报保险集团偿付能力报告的公司名单",
        "filters": {},
        "strict_filters": {},
        "coverage_terms": [],
    }]


def test_decomposer_adds_target_for_document_referenced_by_an_option():
    question = (
        "检索《应当编报保险集团偿付能力报告的公司名单》后，"
        "以下哪一项与材料内容一致？\n"
        "A. 寿险合同负债评估采用折现率曲线。\n"
        "B. 基础利率曲线由三段组成。\n"
        "C. 移动平均曲线适用于0年到20年。\n"
        "D. 列入名单的保险集团应当按照"
        "《保险公司偿付能力监管规则第19号：保险集团》有关规定"
        "编报保险集团偿付能力报告。"
    )
    decomposer = QueryDecomposer()
    decomposer.llm.chat = Mock(side_effect=AssertionError("明确文件引用不应调用模型"))

    result = decomposer.decompose(question)

    assert [target["target_id"] for target in result] == ["main", "reference_D_1"]
    assert result[0]["source_title"] == "应当编报保险集团偿付能力报告的公司名单"
    assert result[0]["full_source"] is True
    assert result[1] == {
        "target_id": "reference_D_1",
        "label": "选项 D 引用：保险公司偿付能力监管规则第19号：保险集团",
        "question": (
            "列入名单的保险集团应当按照"
            "《保险公司偿付能力监管规则第19号：保险集团》有关规定"
            "编报保险集团偿付能力报告。"
        ),
        "type": "regulation",
        "source_title": "保险公司偿付能力监管规则第19号：保险集团",
        "filters": {},
        "strict_filters": {},
        "coverage_terms": [
            "列入名单的保险集团应当按照有关规定编报保险集团偿付能力报告"
        ],
        "option": "D",
        "full_source": True,
    }
