import os

from dotenv import load_dotenv
from typesafe_sdk import Choice, Noul, TypeSafeClient

load_dotenv()

QUERY_TYPES = ("regulation", "table", "hybrid", "out_of_scope")

# Choice 没选中任何候选值时统一返回这个标签，代码据此判断"没有这一维坐标"。
NO_MATCH = "无法确定"

# Choice 的选项硬上限；候选超过这个数必须先用 BM25 收窄。
MAX_CHOICE_OPTIONS = 255

# 判断落到这个置信度以下就不据此收窄检索：路由回落 hybrid，坐标当作没选中。
MIN_CONFIDENCE = 0.5

# Noul 返回的是 yes 的概率，高于这个值才按 yes 处理。
NOUL_YES = 0.5

ROUTE_CRITERIA = {
    "regulation": {
        "what": "答案写在监管制度文件的条文里：定义、适用范围、义务、禁止事项、"
                "办理流程、时限、责任与处罚、报送要求，以及计算口径本身是怎么规定的。",
        "not_for": "只要从统计报表里读出一个数字就能回答的问题。",
        "examples": [
            "保险公司收入确认应当遵循什么规定",
            "偿付能力充足率应当如何计算、由哪份文件规定",
            "会计师事务所应当如何寄送银行询证函",
        ],
    },
    "table": {
        "what": "答案是统计报表里的具体数值：某一行某一列的取数、跨期或跨地区的数值"
                "比较、以及基于这些数值的增减和差额计算。",
        "not_for": "问这个数字背后的制度依据、口径由哪份文件规定、指标含义如何定义——"
                   "那属于 regulation，即使问题里出现了「计算」「指标」这类词。",
        "examples": [
            "2023年12月全国合计的健康险保费收入是多少",
            "银行业金融机构的总负债从一季度到四季度增加了多少",
            "在账面余额口径下哪一项数值最高",
        ],
    },
    "hybrid": {
        "what": "必须同时读制度条文和统计数值才能回答：拿报表里的数字去对照制度阈值"
                "判断是否达标，或者需要跨文件、跨条目综合判断。拿不准是 regulation "
                "还是 table 时也归到这里。",
        "not_for": "只看条文就能答完，或者只看数字就能答完的问题。",
        "examples": [
            "该公司的偿付能力充足率是否达到了监管要求",
            "根据监管规定和统计数据判断这项指标是否达标",
        ],
    },
    "out_of_scope": {
        "what": "与银行业、保险业的监管制度和行业统计报表完全无关：闲聊、写代码、"
                "其他行业话题、对问答系统本身的提问。",
        "not_for": "任何涉及银行、保险、监管规定或行业统计数据的问题，哪怕知识库里"
                   "未必收录了答案，也不算 out_of_scope。",
        "examples": [
            "帮我写一个 Python 排序函数",
            "今天天气怎么样",
            "你用的是什么模型",
        ],
    },
}

ROUTE_INSTRUCTIONS = {
    "task": "判断 `question` 应该到哪一类知识库里找答案。",
    "corpus": "知识库只有两类内容：银行业与保险业的监管制度文件，以及行业统计报表。",
    "context": "`conversation` 是此前的对话。当前问题可能省略了主语、时间或口径，"
               "要结合对话理解它真正在问什么，再做判断。",
}

ROW_INSTRUCTIONS = {
    "task": "`question` 要取的第一个数值位于这张表格的哪一行？",
    "candidates": "候选值是这张表格里真实存在的行标签，保留了原始排版，可能含多余空格。"
                  "问题里的写法与候选值不完全一致时，选含义相同的那一个。",
    "no_match": f"问题没有指向任何一个候选行标签时选「{NO_MATCH}」。",
}

COLUMN_INSTRUCTIONS = {
    "task": "`question` 要取的第一个数值位于这张表格的哪一个列口径？",
    "candidates": "候选值是这张表格里真实存在的列标题。",
    "no_match": f"问题没有指向任何一个候选列标题时选「{NO_MATCH}」。",
}

SECOND_ROW_INSTRUCTIONS = {
    "task": "`question` 是否还要取第二个数值，用来做比较、求差额或算变化？"
            "如果要，第二个数值位于哪一行？",
    "note": "两个数值在同一行、只有列口径不同时，这里选和第一个数值相同的行。",
    "no_match": f"问题只取一个数值时选「{NO_MATCH}」。",
}

SECOND_COLUMN_INSTRUCTIONS = {
    "task": "`question` 要取的第二个数值位于哪一个列口径？",
    "note": "两个数值在同一列口径、只有行不同时，这里选和第一个数值相同的列。",
    "no_match": f"问题只取一个数值时选「{NO_MATCH}」。",
}

SECTION_INSTRUCTIONS = {
    "task": "`question` 限定了表格里的哪一个区块？",
    "no_match": f"问题没有限定区块时选「{NO_MATCH}」。",
}

PERIOD_INSTRUCTIONS = {
    "task": "`question` 问的是哪一个期间的数值？",
    "no_match": f"问题没有限定期间时选「{NO_MATCH}」。",
}

SHEET_INSTRUCTIONS = {
    "task": "`question` 指定了哪一张工作表？",
    "no_match": f"问题没有指定工作表时选「{NO_MATCH}」。",
}

COMPARISON_COLUMN_INSTRUCTIONS = {
    "task": "`question` 是在哪一个列口径下比较各个选项的数值？",
    "no_match": f"问题没有说明列口径时选「{NO_MATCH}」。",
}

SECOND_VALUE_INSTRUCTIONS = {
    "task": "`question` 是否需要取第二个数值才能回答？",
    "context": "只取一个数值就能回答的问题（某行某列是多少），答 no；"
               "要比较两个数值、求差额、算变化或增长的问题，答 yes。",
}

COORDINATE_FIELDS = {
    "row_1": ("row_label", ROW_INSTRUCTIONS),
    "column_1": ("column_header", COLUMN_INSTRUCTIONS),
    "row_2": ("row_label", SECOND_ROW_INSTRUCTIONS),
    "column_2": ("column_header", SECOND_COLUMN_INSTRUCTIONS),
    "section": ("section_path", SECTION_INSTRUCTIONS),
    "period": ("period", PERIOD_INSTRUCTIONS),
}


def _criteria(options: list) -> dict:
    criteria = {option: None for option in options}
    criteria[NO_MATCH] = "候选值里没有一个符合问题的意思。"
    return criteria


class Judge:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        # 延迟构造：缺 TYPESAFE_API_KEY 时在第一次真正判断的地方崩，而不是在建对象时
        if self._client is None:
            self._client = TypeSafeClient(api_key=os.environ["TYPESAFE_API_KEY"])
        return self._client

    def _select(self, state: dict, questions: dict) -> dict:
        answers = self.client.system_one(state, questions).answers
        selected = {}
        for key, answer in answers.items():
            if answer.type == "noul":
                selected[key] = answer.noul >= NOUL_YES
            elif answer.choice == NO_MATCH or answer.confidence < MIN_CONFIDENCE:
                selected[key] = None
            else:
                selected[key] = answer.choice
        return selected

    def route(self, question: str, conversation: str = "") -> str:
        state = {"question": question}
        if conversation:
            state["conversation"] = conversation
        answer = self.client.system_one(
            state,
            {"route": Choice(
                instructions=ROUTE_INSTRUCTIONS,
                criteria=ROUTE_CRITERIA,
            )},
        ).answers["route"]
        if answer.confidence < MIN_CONFIDENCE:
            return "hybrid"
        return answer.choice

    def table_coordinates(self, state: dict, candidates: dict) -> dict:
        questions = {"needs_second": Noul(instructions=SECOND_VALUE_INSTRUCTIONS)}
        for key, (field, instructions) in COORDINATE_FIELDS.items():
            options = candidates.get(field) or []
            if not options:
                continue
            questions[key] = Choice(
                instructions=instructions,
                criteria=_criteria(options),
            )
        return self._select(state, questions)

    def table_option_rows(self, state: dict, options: dict,
                          candidates: dict) -> dict:
        questions = {}
        row_labels = candidates.get("row_label") or []
        for option, text in options.items():
            if not row_labels:
                continue
            questions[f"option_{option}"] = Choice(
                instructions={
                    "task": f"选项「{text}」对应这张表格里的哪一行？",
                    "candidates": ROW_INSTRUCTIONS["candidates"],
                    "no_match": f"没有对应的行时选「{NO_MATCH}」。",
                },
                criteria=_criteria(row_labels),
            )
        column_headers = candidates.get("column_header") or []
        if column_headers:
            questions["column"] = Choice(
                instructions=COMPARISON_COLUMN_INSTRUCTIONS,
                criteria=_criteria(column_headers),
            )
        table_names = candidates.get("table_name") or []
        if table_names:
            questions["table_name"] = Choice(
                instructions=SHEET_INSTRUCTIONS,
                criteria=_criteria(table_names),
            )
        if not questions:
            return {}
        return self._select(state, questions)
