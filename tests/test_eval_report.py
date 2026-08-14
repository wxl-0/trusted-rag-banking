from scripts.run_eval import build_competition_metrics, summarize_accuracy


def test_competition_metrics_reports_regulation_fact_accuracy():
    results = [
        {"qa_type": "单事实检索", "is_correct": True},
        {"qa_type": "多事实检索", "is_correct": False},
        {"qa_type": "表格取数", "is_correct": True},
    ]

    metrics = build_competition_metrics(results)

    assert metrics["regulation_fact_accuracy"] == {
        "status": "available",
        "total": 2,
        "correct": 1,
        "rate": 0.5,
        "target": 0.85,
        "meets_target": False,
    }


def test_competition_metrics_reports_table_accuracy():
    results = [
        {"qa_type": "表格取数", "is_correct": True},
        {"qa_type": "表格比较", "is_correct": True},
        {"qa_type": "表格计算", "is_correct": False},
        {"qa_type": "单事实检索", "is_correct": False},
    ]

    metrics = build_competition_metrics(results)

    assert metrics["table_accuracy"] == {
        "status": "available",
        "total": 3,
        "correct": 2,
        "rate": 0.6667,
        "target": 0.8,
        "meets_target": False,
    }


def test_competition_metrics_reports_evidence_source_hit_rate():
    results = [
        {
            "expected_source_title": "银行询证函工作操作指引",
            "evidence": [{"source_title": "《银行询证函工作操作指引》"}],
        },
        {
            "expected_source_title": "商业银行资本管理办法",
            "evidence": [{"source_title": "银行业监督管理法"}],
        },
        {
            "expected_source_title": "",
            "evidence": [{"source_title": "不计入评测"}],
        },
    ]

    metrics = build_competition_metrics(results)

    assert metrics["evidence_citation_hit_rate"] == {
        "status": "available",
        "evaluated": 2,
        "hits": 1,
        "rate": 0.5,
        "target": 0.9,
        "meets_target": False,
        "definition": (
            "返回证据中至少一个 source_title 经规范化及标题别名处理后"
            "包含题库标准来源标题"
        ),
    }


def test_evidence_source_hit_rate_treats_null_evidence_as_a_miss():
    results = [
        {
            "expected_source_title": "银行询证函工作操作指引",
            "evidence": None,
        }
    ]

    metrics = build_competition_metrics(results)

    assert metrics["evidence_citation_hit_rate"]["hits"] == 0


def test_evidence_source_hit_rate_accepts_a_section_suffix_after_title():
    results = [
        {
            "expected_source_title": "2023年10月人身险公司经营情况表",
            "evidence": [
                {
                    "source_title": (
                        "《2023年10月人身险公司经营情况表》"
                        "人身保险公司（月度）"
                    )
                }
            ],
        }
    ]

    metrics = build_competition_metrics(results)

    assert metrics["evidence_citation_hit_rate"]["hits"] == 1


def test_evidence_source_hit_rate_accepts_property_insurance_title_alias():
    results = [
        {
            "expected_source_title": "2024年9月财产保险公司经营情况表",
            "evidence": [
                {"source_title": "《2024年9月财产险公司经营情况表》产险公司数据（月度）"}
            ],
        }
    ]

    metrics = build_competition_metrics(results)

    assert metrics["evidence_citation_hit_rate"]["hits"] == 1


def test_competition_metrics_marks_unscorable_metrics_unavailable():
    results = [
        {"refused": True},
        {"refused": False},
    ]

    metrics = build_competition_metrics(results)

    assert metrics["critical_entity_error_rate"] == {
        "status": "unavailable",
        "rate": None,
        "target_max": 0.05,
        "meets_target": None,
        "reason": "题库尚无结构化的数字、日期、机构名称和文号金标准标注",
    }
    assert metrics["out_of_scope_refusal_rate"] == {
        "status": "unavailable",
        "rate": None,
        "target": 0.8,
        "meets_target": None,
        "observed_refusal_count": 1,
        "observed_refusal_rate": 0.5,
        "reason": "当前评测集均为可回答选择题，尚无库外或依据不足题目标注",
    }


def test_accuracy_summary_groups_results_by_difficulty():
    results = [
        {"difficulty": "easy", "is_correct": True},
        {"difficulty": "easy", "is_correct": False},
        {"difficulty": "hard", "is_correct": True},
    ]

    summary = summarize_accuracy(results, "difficulty")

    assert summary == {
        "easy": {"total": 2, "correct": 1, "accuracy": 0.5},
        "hard": {"total": 1, "correct": 1, "accuracy": 1.0},
    }
