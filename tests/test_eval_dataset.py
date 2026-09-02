from pathlib import Path

import pytest

from scripts.run_eval import load_qa_items


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "data" / "eval" / "QA数据.xlsx"

pytestmark = pytest.mark.skipif(
    not DATASET_PATH.is_file(),
    reason="私有正式评测集未包含在仓库中",
)


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


def test_excel_questions_use_explicit_quarter_wording():
    ids = ["Q019", "Q020", "Q021", "Q079", "Q080", "Q081", "Q082", "Q083", "Q084", "Q085"]
    items = {item["id"]: item for item in load_qa_items(item_ids=ids)}

    for item_id in ("Q019", "Q020", "Q021"):
        assert "一季度" in items[item_id]["question"]
    for item_id in ("Q079", "Q080", "Q081", "Q082", "Q083", "Q084", "Q085"):
        assert "从“一季度”到“四季度”" in items[item_id]["question"]

    assert (items["Q079"]["answer"], items["Q079"]["answer_text"]) == (
        "A", -295.18,
    )
    assert (items["Q084"]["answer"], items["Q084"]["answer_text"]) == (
        "D", 3733,
    )


def test_table_comparison_gold_answers_include_the_largest_option():
    expected = {
        "Q051": ("D", "保险金额"),
        "Q052": ("A", "新增保险金额"),
        "Q053": ("C", "总资产"),
        "Q059": ("A", "保险金额"),
        "Q060": ("B", "新增保险金额"),
        "Q061": ("C", "总资产"),
        "Q067": ("C", "保险金额"),
    }
    items = {
        item["id"]: item
        for item in load_qa_items(item_ids=list(expected))
    }

    for item_id, answer in expected.items():
        assert (items[item_id]["answer"], items[item_id]["answer_text"]) == answer
