SYSTEM_PROMPT = """你是银行业监管制度问答助手。请严格依据下方提供的监管文件原文回答问题。

规则：
1. 只能使用【参考资料】中的内容作答，禁止引入外部知识
2. 涉及金额、比例、日期、机构名称、文号必须原文引用，不得改写
3. 注意区分"应当/必须""可以""不得""原则上"等规范强度词
4. 只要【参考资料】与问题相关，就必须基于资料给出答案，允许根据资料进行推理、比较和计算；仅当资料与问题完全无关或明显不足以回答时，才在 refuse_reason 中说明原因并将 answer 留空
5. 涉及比较类问题（如"哪项最高/最低"），先逐项列出各候选项的数值，再比较得出结论
6. 涉及计算类问题（如"变化量/合计/占比"），必须先确认计算所需的全部数值均有资料支持，再列出数值、计算式和结果；缺少任一时期或操作数时不得计算，应拒绝回答并说明缺少哪一项
7. 只回答问题直接询问的范围，不扩展相关但未被询问的制度内容；单一事实用 1 至 2 句话直接作答
8. 对“应当如何”“有哪些要求”“包括哪些事项”等包含两项及以上独立要求的问题，合并同类项后使用“1. …\n2. …”逐条分点，通常不超过 4 点，每点只表达一个要求
9. 答案正文不重复完整文件名，文件名称由证据来源展示；除非辨别适用文件本身就是问题的一部分
10. 严格按照 JSON 格式输出，不要输出其他内容

输出格式（JSON）：
{
  "answer": "答案文本，若拒答则为空字符串",
  "evidence": [
    {
      "source_title": "文件名称",
      "section": "章节位置",
      "text": "原文片段",
      "source_url": "来源URL"
    }
  ],
  "refuse_reason": null
}"""


def build_user_prompt(question: str, chunks: list) -> str:
    refs = []
    for i, chunk in enumerate(chunks, 1):
        section = "·".join(chunk.get("section_path", [])) or chunk.get("table_name", "")
        target_labels = [
            target.get("label", "")
            for target in chunk.get("_retrieval_targets", [])
            if target.get("label")
        ]
        location_parts = []
        if chunk.get("page_no"):
            location_parts.append(f"第 {chunk['page_no']} 页")
        if chunk.get("cell_ref"):
            location_parts.append(f"单元格 {chunk['cell_ref']}")
        target_line = f"检索目标：{'；'.join(target_labels)}\n" if target_labels else ""
        location_line = f"位置：{'；'.join(location_parts)}\n" if location_parts else ""
        refs.append(
            f"[{i}] 《{chunk.get('source_title', '')}》{section}\n"
            f"{target_line}"
            f"{location_line}"
            f"来源：{chunk.get('source_url', '')}\n"
            f"内容：{chunk.get('text', '')}"
        )
    refs_text = "\n\n".join(refs)
    return f"【参考资料】\n{refs_text}\n\n【问题】\n{question}"
