import openpyxl

from scripts.run_eval import load_qa_items, score_answer


def _write_qa_workbook(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "id",
        "source_type",
        "difficulty",
        "qa_type",
        "question",
        "option_a",
        "option_b",
        "option_c",
        "option_d",
        "answer",
        "answer_text",
        "source_title",
    ])
    for question_id in ("Q001", "Q002", "Q003"):
        ws.append([
            question_id,
            "excel",
            "easy",
            "表格取数",
            f"问题 {question_id}",
            "选项 A",
            "选项 B",
            "选项 C",
            "选项 D",
            "A",
            "选项 A",
            "测试文件",
        ])
    wb.save(path)


def test_load_qa_items_uses_requested_id_order(tmp_path):
    qa_path = tmp_path / "qa.xlsx"
    _write_qa_workbook(qa_path)

    items = load_qa_items(qa_path=qa_path, item_ids=["Q003", "Q001"])

    assert [item["id"] for item in items] == ["Q003", "Q001"]


def test_score_answer_uses_structured_choice():
    item = {
        "answer": "B",
        "option_a": "10",
        "option_b": "20",
        "option_c": "30",
        "option_d": "40",
    }

    score = score_answer({"choice": "b", "answer": "依据资料，结果为 20。"}, item)

    assert score == {
        "choice": "B",
        "is_correct": True,
        "scoring_method": "structured_choice",
    }


def test_score_answer_matches_normalized_numeric_option():
    item = {
        "answer": "A",
        "option_a": "281573.61",
        "option_b": "265731.16",
        "option_c": "258173.61",
        "option_d": "281735.16",
    }

    score = score_answer({"answer": "根据资料计算，结果为 281,573.61。"}, item)

    assert score == {
        "choice": "A",
        "is_correct": True,
        "scoring_method": "normalized_option_text",
    }


def test_score_answer_extracts_explicit_choice_from_answer_text():
    item = {
        "answer": "C",
        "option_a": "甲",
        "option_b": "乙",
        "option_c": "丙",
        "option_d": "丁",
    }

    score = score_answer({"answer": "答案：C。依据如下。"}, item)

    assert score == {
        "choice": "C",
        "is_correct": True,
        "scoring_method": "explicit_choice_text",
    }


def test_score_answer_does_not_extract_choice_from_refusal_explanation():
    item = {
        "answer": "C",
        "option_a": "甲",
        "option_b": "乙",
        "option_c": "丙",
        "option_d": "丁",
    }
    result = {
        "choice": None,
        "answer": "选项A、B、C、D的第二句均未在参考资料中出现。",
        "refuse_reason": "资料不足，无法选择。",
    }

    score = score_answer(result, item)

    assert score == {
        "choice": "",
        "is_correct": False,
        "scoring_method": "refused",
    }
