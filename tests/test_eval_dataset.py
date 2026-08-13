from scripts.run_eval import load_qa_items


def test_ambiguous_q075_is_excluded_by_default_but_available_by_id():
    assert "Q075" not in {item["id"] for item in load_qa_items()}

    item = load_qa_items(item_ids=["Q075"])[0]

    assert item["id"] == "Q075"
    assert item["eval_status"] == "excluded_ambiguous"


def test_known_excel_questions_have_verified_answers_and_periods():
    ids = [
        "Q044", "Q045", "Q071", "Q072", "Q073", "Q074",
        "Q076", "Q077", "Q078",
    ]
    items = {item["id"]: item for item in load_qa_items(item_ids=ids)}

    assert (items["Q044"]["answer"], items["Q044"]["answer_text"]) == (
        "D", "新增保险金额",
    )
    assert (items["Q045"]["answer"], items["Q045"]["answer_text"]) == (
        "B", "总资产",
    )

    for item_id in ("Q071", "Q072", "Q073"):
        assert "一季度数值" in items[item_id]["question"]

    for item_id in ("Q074", "Q076", "Q077", "Q078"):
        assert "从“一季度”到“四季度”" in items[item_id]["question"]

    assert "在“1. 银行业金融机构”区块中" in items["Q074"]["question"]
