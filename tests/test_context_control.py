from src.context_control import (
    ContextAssembler,
    ContextSettings,
    message_tokens,
)


def _settings() -> ContextSettings:
    return ContextSettings(
        normal_input_tokens=180,
        complex_input_tokens=260,
        hard_input_tokens=280,
        output_reserve_tokens=40,
        recent_history_tokens=100,
        summary_tokens=40,
    )


def test_normal_context_stays_in_budget_and_keeps_newest_history():
    assembler = ContextAssembler(_settings())
    history = [
        {"role": "system", "content": "【历史对话摘要】\n早期事实"},
        {"role": "user", "content": "OLD-" + "旧问题" * 12},
        {"role": "assistant", "content": "OLD-" + "旧回答" * 12},
        {"role": "user", "content": "NEW-" + "新问题" * 8},
        {"role": "assistant", "content": "NEW-" + "新回答" * 8},
    ]

    context = assembler.assemble(
        system="系统指令" * 4,
        user="【参考资料】\n证据\n\n【问题】\n当前问题",
        history=history,
        complex_query=False,
    )

    prompt_tokens = sum(message_tokens(message) for message in context.messages)
    assert prompt_tokens <= 180 - 40
    assert context.messages[0]["role"] == "system"
    assert any("早期事实" in item["content"] for item in context.messages)
    assert any("NEW-" in item["content"] for item in context.messages)
    assert all("OLD-" not in item["content"] for item in context.messages)


def test_complex_context_can_use_more_history_than_normal_context():
    assembler = ContextAssembler(_settings())
    history = [
        {"role": "user", "content": f"turn-{index}-" + "历史" * 12}
        for index in range(4)
    ]
    arguments = {
        "system": "系统指令" * 4,
        "user": "【参考资料】\n证据\n\n【问题】\n当前问题",
        "history": history,
    }

    normal = assembler.assemble(**arguments, complex_query=False)
    complex_context = assembler.assemble(**arguments, complex_query=True)

    assert len(complex_context.messages) > len(normal.messages)
    assert sum(message_tokens(item) for item in complex_context.messages) <= 260 - 40


def test_evidence_precedes_summary_and_hard_cap_limits_complex_context():
    settings = ContextSettings(
        normal_input_tokens=180,
        complex_input_tokens=400,
        hard_input_tokens=220,
        output_reserve_tokens=40,
        recent_history_tokens=100,
        summary_tokens=80,
    )
    assembler = ContextAssembler(settings)
    evidence = "EVIDENCE-" + "证据正文" * 24
    context = assembler.assemble(
        system="系统指令" * 4,
        user=f"【参考资料】\n{evidence}\n\n【问题】\n当前问题",
        history=[
            {"role": "system", "content": "【历史对话摘要】\n" + "摘要" * 30},
            {"role": "user", "content": "最新历史" * 20},
        ],
        complex_query=True,
    )

    assert "EVIDENCE-" in context.user
    assert "【问题】\n当前问题" in context.user
    assert sum(message_tokens(item) for item in context.messages) <= 220 - 40
