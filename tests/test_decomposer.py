from unittest.mock import Mock

import pytest

from src.generator.decomposer import QueryDecomposer


class FakeJudge:
    def __init__(self, route="regulation", coordinates=None, option_rows=None):
        self.route_value = route
        self.coordinates = coordinates or {}
        self.option_rows = option_rows or {}
        self.route_calls = []
        self.last_state = None
        self.last_candidates = None

    def route(self, question, conversation=""):
        self.route_calls.append((question, conversation))
        return self.route_value

    def table_coordinates(self, state, candidates):
        self.last_state = state
        self.last_candidates = candidates
        return dict(self.coordinates)

    def table_option_rows(self, state, options, candidates):
        self.last_state = state
        self.last_candidates = candidates
        return dict(self.option_rows)


class FakeBM25:
    def __init__(self, title="", chunks=()):
        self.title = title
        self.chunks = list(chunks)
        self.resolved_hints = []

    def resolve_source_titles(self, title_hint):
        self.resolved_hints.append(title_hint)
        if self.title and title_hint:
            return [self.title], "exact"
        return [], "none"

    def chunks_for_source_titles(self, titles, filters=None, max_chunks=20):
        return list(self.chunks)

    def search(self, query, top_k=20, filters=None):
        return list(self.chunks)[:top_k]


def table_chunks(title, rows, columns, period="", table_name="", sections=()):
    return [
        {
            "source_title": title,
            "chunk_type": "table_row",
            "row_label": row,
            "column_header": column,
            "period": period,
            "table_name": table_name,
            "section_path": list(sections),
        }
        for row in rows
        for column in columns
    ]


def make_decomposer(route="regulation", coordinates=None, option_rows=None,
                    title="", chunks=(), include_single_fact_options=False):
    judge = FakeJudge(route, coordinates, option_rows)
    bm25 = FakeBM25(title, chunks)
    decomposer = QueryDecomposer(
        include_single_fact_options=include_single_fact_options,
        bm25=bm25,
        judge=judge,
    )
    decomposer.llm.chat = Mock(side_effect=AssertionError("不应调用生成模型"))
    return decomposer


@pytest.mark.parametrize(
    "route",
    ["regulation", "table", "hybrid", "out_of_scope"],
)
def test_decomposer_keeps_the_route_the_judgment_returned(route):
    question = "根据《消费金融公司管理办法》，下列哪项表述正确？"
    decomposer = make_decomposer(route=route)

    result = decomposer.decompose(question)

    assert len(result) == 1
    assert result[0]["question"] == question
    assert result[0]["type"] == route
    assert result[0]["target_id"] == "main"
    assert decomposer.last_decision_method == "judgment"
    assert decomposer.last_route == route
    assert decomposer.last_judgment_metrics == {"api_calls": 1}


def test_decomposer_routes_a_regulation_question_without_table_cue_words():
    # 旧的关键词表会因为「计算」命中 table，从此再也查不到制度库
    question = "保险公司应当如何计算偿付能力充足率，依据是哪份文件？"
    decomposer = make_decomposer(route="regulation")

    result = decomposer.decompose(question)

    assert result[0]["type"] == "regulation"


def test_decomposer_passes_conversation_to_the_routing_judgment():
    history = [{"role": "user", "content": "上一轮问的是银行函证"}]
    decomposer = make_decomposer(route="regulation")

    decomposer.decompose("那具体是哪一条？", history=history)

    question, conversation = decomposer.judge.route_calls[0]
    assert question == "那具体是哪一条？"
    assert "上一轮问的是银行函证" in conversation


def test_decomposer_splits_table_change_into_two_lookup_targets():
    title = "2023年12月全国各地区原保险保费收入情况表"
    question = (
        "需要对同一 Excel 附件做两处取数并计算。"
        f"根据《{title}》，"
        "“全国合计”从“合计”到“健康险”的数值变化约为多少？"
    )
    decomposer = make_decomposer(
        route="table",
        coordinates={
            "row_1": "全国合计",
            "column_1": "合计",
            "row_2": "全国合计",
            "column_2": "健康险",
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["全国合计", "北  京", "河  北"],
            columns=["合计", "健康险", "寿险"],
        ),
    )

    result = decomposer.decompose(question)

    assert result == [
        {
            "target_id": "operand_1",
            "label": "全国合计 / 合计",
            "question": f"《{title}》 全国合计 合计",
            "type": "table",
            "source_title": title,
            "filters": {},
            "strict_filters": {"row_label": "全国合计", "column_header": "合计"},
            "coverage_terms": ["全国合计", "合计"],
        },
        {
            "target_id": "operand_2",
            "label": "全国合计 / 健康险",
            "question": f"《{title}》 全国合计 健康险",
            "type": "table",
            "source_title": title,
            "filters": {},
            "strict_filters": {"row_label": "全国合计", "column_header": "健康险"},
            "coverage_terms": ["全国合计", "健康险"],
        },
    ]
    assert decomposer.last_route == "table"
    assert decomposer.last_judgment_metrics == {"api_calls": 2}


def test_decomposer_offers_only_indexed_labels_as_coordinate_candidates():
    title = "2023年12月全国各地区原保险保费收入情况表"
    decomposer = make_decomposer(
        route="table",
        coordinates={"row_1": "全国合计", "column_1": "合计"},
        title=title,
        chunks=table_chunks(
            title,
            rows=["全国合计", "北  京"],
            columns=["合计", "健康险"],
            period="2023年12月",
            sections=["各地区数据（月度）"],
        ),
    )

    decomposer.decompose(f"根据《{title}》，全国合计的合计是多少？")

    assert decomposer.judge.last_candidates["row_label"] == ["全国合计", "北  京"]
    assert decomposer.judge.last_candidates["column_header"] == ["健康险", "合计"]
    assert decomposer.judge.last_candidates["period"] == ["2023年12月"]
    assert decomposer.judge.last_candidates["section_path"] == ["各地区数据（月度）"]


def test_decomposer_keeps_explicit_table_section_in_change_targets():
    title = "2023年银行业总资产、总负债（季度）"
    question = (
        f"根据《{title}》，"
        "在“1. 银行业金融机构”区块中，"
        "“总负债”从“一季度”到“四季度”的数值变化约为多少？"
    )
    decomposer = make_decomposer(
        route="table",
        coordinates={
            "row_1": "总负债",
            "column_1": "一季度",
            "row_2": "总负债",
            "column_2": "四季度",
            "section": "1. 银行业金融机构",
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["总资产", "总负债"],
            columns=["一季度", "四季度"],
            sections=["1. 银行业金融机构"],
        ),
    )

    result = decomposer.decompose(question)

    assert result[0]["question"] == (
        f"《{title}》 1. 银行业金融机构 总负债 一季度"
    )
    assert result[0]["strict_filters"] == {
        "row_label": "总负债",
        "column_header": "一季度",
        "section_path": "1. 银行业金融机构",
    }
    assert result[0]["coverage_terms"] == [
        "总负债", "一季度", "1. 银行业金融机构",
    ]
    assert result[1]["strict_filters"]["column_header"] == "四季度"


@pytest.mark.parametrize(
    "question",
    [
        "2023年银行业金融机构的总负债从一季度到四季度增加了多少？",
        "2023年“银行业金融机构”的“总负债”从“一季度”到“四季度”增加了多少？",
        (
            "根据《2023年银行业总资产、总负债（季度）》，"
            "在银行业金融机构区块中，总负债从一季度到四季度增加了多少？"
        ),
    ],
)
def test_decomposer_splits_table_change_regardless_of_phrasing(question):
    title = "2023年银行业总资产、总负债（季度）"
    decomposer = make_decomposer(
        route="table",
        coordinates={
            "row_1": "总负债",
            "column_1": "一季度",
            "row_2": "总负债",
            "column_2": "四季度",
            "section": "银行业金融机构",
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["总资产", "总负债"],
            columns=["一季度", "四季度"],
            sections=["银行业金融机构"],
        ),
    )

    result = decomposer.decompose(question)

    assert [target["target_id"] for target in result] == ["operand_1", "operand_2"]
    assert result[0]["question"].endswith("银行业金融机构 总负债 一季度")
    assert result[1]["question"].endswith("银行业金融机构 总负债 四季度")
    assert result[0]["strict_filters"] == {
        "row_label": "总负债",
        "column_header": "一季度",
        "section_path": "银行业金融机构",
    }


def test_decomposer_takes_the_title_from_the_stem_not_from_an_option():
    stem_title = "应当编报保险集团偿付能力报告的公司名单"
    question = (
        f"根据《{stem_title}》，下列哪一项数值最高？\n"
        "A. 北京\n"
        "B. 《保险公司偿付能力监管规则第19号：保险集团》里的数值"
    )
    decomposer = make_decomposer(route="table", title=stem_title)

    decomposer.decompose(question)

    # 选项里的《》不参与定位表格，否则会取到错误的文件
    assert decomposer.bm25.resolved_hints == [stem_title]


def test_decomposer_resolves_short_table_follow_up_from_history_without_rewriting():
    title = "2026年1月全国各地区原保险保费收入情况表"
    history = [
        {
            "role": "user",
            "content": "2026年1月，北京的原保险保费收入合计是多少？",
        },
        {
            "role": "assistant",
            "content": "2026年1月，北京的原保险保费收入合计为721.72亿元。",
            "evidence": [{
                "source_title": title,
                "section": "各地区数据（月度）",
                "text": (
                    "行指标「北  京」；列口径「合计」；原始值为 721.72；"
                    "单位：亿元；期间：2026年1月。"
                ),
                "source_url": "",
            }],
        },
    ]
    decomposer = make_decomposer(
        route="table",
        coordinates={
            "row_1": "河  北",
            "column_1": "合计",
            "period": "2026年1月",
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["北  京", "河  北"],
            columns=["合计", "寿险"],
            period="2026年1月",
        ),
    )

    result = decomposer.decompose("河北呢？", history=history)

    assert len(result) == 1
    assert result[0]["type"] == "table"
    assert result[0]["source_title"] == title
    assert "河北" in result[0]["question"]
    assert "2026年1月" in result[0]["question"]
    assert "合计" in result[0]["question"]
    assert result[0]["strict_filters"] == {
        "row_label": "河  北",
        "column_header": "合计",
    }
    assert decomposer.last_contextualization_metrics == {
        "method": "judgment",
        "api_calls": 0,
    }
    # 历史里的结构化证据整段交给判断，不再反向解析已渲染的证据文本
    assert "行指标「北  京」" in decomposer.judge.last_state["conversation"]


def test_decomposer_resolves_two_regions_and_splits_strict_table_operands():
    title = "2026年1月全国各地区原保险保费收入情况表"
    history = [
        {"role": "user", "content": "2026年1月，北京的原保险保费收入合计是多少？"},
        {
            "role": "assistant",
            "content": "2026年1月，北京的原保险保费收入合计为721.72亿元。",
            "evidence": [{
                "source_title": title,
                "section": "各地区数据（月度）",
                "text": (
                    "行指标「北  京」；列口径「合计」；原始值为 721.72；"
                    "单位：亿元；期间：2026年1月。"
                ),
                "source_url": "",
            }],
        },
        {"role": "user", "content": "河北呢？"},
        {
            "role": "assistant",
            "content": "2026年1月，河北的原保险保费收入合计为465.02亿元。",
            "evidence": [{
                "source_title": title,
                "section": "各地区数据（月度）",
                "text": (
                    "行指标「河  北」；列口径「合计」；原始值为 465.02；"
                    "单位：亿元；期间：2026年1月。"
                ),
                "source_url": "",
            }],
        },
    ]
    decomposer = make_decomposer(
        route="table",
        coordinates={
            "row_1": "北  京",
            "column_1": "寿险",
            "row_2": "河  北",
            "column_2": "寿险",
            "period": "2026年1月",
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["北  京", "河  北"],
            columns=["合计", "寿险"],
            period="2026年1月",
        ),
    )

    result = decomposer.decompose(
        "两地的寿险收入分别是多少，差额是多少？",
        history=history,
    )

    assert [target["target_id"] for target in result] == ["operand_1", "operand_2"]
    assert [target["operand_label"] for target in result] == ["北京", "河北"]
    assert [target["strict_filters"] for target in result] == [
        {"row_label": "北  京", "column_header": "寿险"},
        {"row_label": "河  北", "column_header": "寿险"},
    ]
    assert all(target["source_title"] == title for target in result)
    assert "北京和河北" in decomposer.last_contextualized_question.replace(" ", "")
    assert "2026年1月" in decomposer.last_contextualized_question
    assert decomposer.last_contextualization_metrics == {
        "method": "judgment",
        "api_calls": 0,
    }


def test_decomposer_falls_back_to_one_target_when_no_coordinate_is_selected():
    title = "2023年12月全国各地区原保险保费收入情况表"
    question = f"根据《{title}》，这张表主要说明了什么？"
    decomposer = make_decomposer(
        route="table",
        coordinates={},
        title=title,
        chunks=table_chunks(title, rows=["全国合计"], columns=["合计"]),
    )

    result = decomposer.decompose(question)

    assert len(result) == 1
    assert result[0]["target_id"] == "main"
    assert result[0]["strict_filters"] == {}
    assert result[0]["question"] == question


def test_decomposer_splits_table_comparison_by_option_and_column():
    title = "2023年4季度保险业资金运用情况表"
    sheet = "2023年4季度保险资金运用情况表"
    question = (
        f"根据 Excel 附件《{title}》"
        f"（工作表：{sheet}），"
        "在“截至当期-账面余额”口径下，以下哪一项数值最高？\n"
        "A. 年化综合收益率\n"
        "B. 年化财务收益率\n"
        "C. 资金运用余额\n"
        "D. 银行存款"
    )
    decomposer = make_decomposer(
        route="table",
        option_rows={
            "option_A": "年化综合收益率",
            "option_B": "年化财务收益率",
            "option_C": "资金运用余额",
            "option_D": "银行存款",
            "column": "截至当期-账面余额",
            "table_name": sheet,
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["年化综合收益率", "年化财务收益率", "资金运用余额", "银行存款"],
            columns=["截至当期-账面余额"],
            table_name=sheet,
        ),
    )

    result = decomposer.decompose(question)

    assert len(result) == 4
    assert result[0] == {
        "target_id": "option_A",
        "label": "A. 年化综合收益率",
        "question": (
            f"《{title}》 工作表 {sheet} 截至当期-账面余额 年化综合收益率"
        ),
        "type": "table",
        "source_title": title,
        "filters": {},
        "strict_filters": {
            "table_name": sheet,
            "row_label": "年化综合收益率",
            "column_header": "截至当期-账面余额",
        },
        "coverage_terms": ["年化综合收益率", "截至当期-账面余额"],
        "option": "A",
    }
    assert result[-1]["target_id"] == "option_D"
    assert result[-1]["strict_filters"]["row_label"] == "银行存款"


def test_decomposer_copies_the_selected_sheet_name_verbatim():
    title = "2023年12月全国各地区原保险保费收入情况表"
    sheet = "各地区数据（月度）"
    question = (
        f"根据 Excel 附件《{title}》（工作表：{sheet}），"
        "在“健康险”口径下，以下哪一项数值最高？\n"
        "A. 北京\nB. 上海"
    )
    decomposer = make_decomposer(
        route="table",
        option_rows={
            "option_A": "北  京",
            "option_B": "上  海",
            "column": "健康险",
            "table_name": sheet,
        },
        title=title,
        chunks=table_chunks(
            title,
            rows=["北  京", "上  海"],
            columns=["健康险"],
            table_name=sheet,
        ),
    )

    result = decomposer.decompose(question)

    assert {target["strict_filters"]["table_name"] for target in result} == {sheet}
    assert [target["label"] for target in result] == ["A. 北京", "B. 上海"]


def test_decomposer_rewrites_context_dependent_follow_up_for_retrieval():
    history = [
        {
            "role": "user",
            "content": "根据《银行函证工作操作指引》，一份询证函可以列示几个基准日？",
        },
        {"role": "assistant", "content": "只列示一个函证基准日。"},
    ]
    rewritten = (
        "根据《银行函证工作操作指引》，"
        "会计师事务所应当如何管理银行询证函的发送和收回？"
    )
    decomposer = make_decomposer(route="regulation")
    decomposer.llm.chat = Mock(return_value=(
        '{"question": "' + rewritten + '"}'
    ))

    result = decomposer.decompose("那发送和收回应该怎么管理？", history=history)

    assert result[0]["question"] == rewritten
    assert result[0]["source_title"] == "银行函证工作操作指引"
    assert result[0]["type"] == "regulation"
    assert decomposer.last_contextualized_question == rewritten
    prompt = decomposer.llm.chat.call_args.kwargs["user"]
    assert "一份询证函可以列示几个基准日" in prompt
    assert "那发送和收回应该怎么管理" in prompt


def test_decomposer_uses_rolling_summary_from_controlled_history():
    history = [
        {
            "role": "system",
            "content": "【历史对话摘要】\n用户正在询问《银行函证工作操作指引》。",
        },
        *[
            {"role": "user", "content": f"近期问题 {index}"}
            for index in range(6)
        ],
    ]
    decomposer = make_decomposer(route="regulation")
    decomposer.llm.chat = Mock(return_value=(
        '{"question": "根据《银行函证工作操作指引》，该规定具体是什么？"}'
    ))

    decomposer.decompose("那该规定具体是什么？", history=history)

    prompt = decomposer.llm.chat.call_args.kwargs["user"]
    assert "历史对话摘要" in prompt
    assert "银行函证工作操作指引" in prompt


def test_decomposer_token_limits_untrusted_legacy_history(monkeypatch):
    monkeypatch.setenv("CONTEXT_RECENT_HISTORY_TOKENS", "35")
    history = [
        {"role": "user", "content": "OLD-" + "旧历史" * 20},
        {"role": "assistant", "content": "NEW-" + "最新事实" * 6},
    ]
    decomposer = make_decomposer(route="regulation")
    decomposer.llm.chat = Mock(return_value='{"question": "根据监管规定，改写问题"}')

    decomposer.decompose("那具体呢？", history=history)

    prompt = decomposer.llm.chat.call_args.kwargs["user"]
    assert "NEW-" in prompt
    assert "OLD-" not in prompt


def test_decomposer_falls_back_when_follow_up_rewrite_fails():
    history = [{
        "role": "user",
        "content": "根据《银行函证工作操作指引》，函证工作有哪些要求？",
    }]
    decomposer = make_decomposer(route="regulation")
    decomposer.llm.chat = Mock(side_effect=RuntimeError("model unavailable"))

    result = decomposer.decompose("那具体是哪一条？", history=history)

    assert result[0]["type"] == "regulation"
    assert "银行函证工作操作指引" in result[0]["question"]
    assert "那具体是哪一条" in result[0]["question"]


def test_decomposer_does_not_rewrite_complete_question_with_history():
    question = "根据《银行函证工作操作指引》，一份询证函列示几个基准日？"
    decomposer = make_decomposer(route="regulation")

    result = decomposer.decompose(
        question,
        history=[{"role": "user", "content": "上一轮无关问题"}],
    )

    assert result[0]["question"] == question
    assert decomposer.last_contextualized_question is None


def test_decomposer_does_not_rewrite_follow_up_with_explicit_subject():
    question = "那一份银行询证函可以列示几个函证基准日？"
    decomposer = make_decomposer(route="regulation")

    result = decomposer.decompose(
        question,
        history=[{
            "role": "user",
            "content": "会计师事务所应当如何管理银行询证函的发送和收回？",
        }],
    )

    assert result[0]["question"] == question
    assert result[0]["type"] == "regulation"
    assert decomposer.last_contextualized_question is None


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
    decomposer = make_decomposer(route="regulation")

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
    decomposer = make_decomposer(route="regulation")

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


def test_eval_decomposer_splits_single_fact_options_with_source_constraints():
    question = (
        "检索《银行函证工作操作指引（PDF）》后，以下哪一项与材料内容一致？\n"
        "A. 折现率曲线由基础利率曲线形成。\n"
        "B. 基础利率曲线由三段组成。\n"
        "C. 会计师事务所应当采用公示地址作为邮寄地址。\n"
        "D. 移动平均曲线适用于0年到20年。"
    )
    decomposer = make_decomposer(
        route="regulation", include_single_fact_options=True
    )

    result = decomposer.decompose(question)

    assert [target["target_id"] for target in result] == [
        "option_A", "option_B", "option_C", "option_D",
    ]
    assert all(
        target["source_title"] == "银行函证工作操作指引（PDF）"
        for target in result
    )
    assert result[2]["coverage_terms"] == [
        "会计师事务所应当采用公示地址作为邮寄地址。"
    ]
    assert result[2]["question"] == (
        "《银行函证工作操作指引（PDF）》 "
        "会计师事务所应当采用公示地址作为邮寄地址。"
    )


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
    decomposer = make_decomposer(route="regulation")

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
