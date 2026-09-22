from src.judgment import Judge


class QueryRouter:
    def __init__(self, judge=None):
        self.judge = judge or Judge()

    def route(self, question: str, conversation: str = "") -> str:
        return self.judge.route(question, conversation)
