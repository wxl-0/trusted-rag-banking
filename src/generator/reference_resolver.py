import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TableFact:
    source_title: str
    period: str
    row_label: str
    column_header: str

    @property
    def display_row(self) -> str:
        return re.sub(r"\s+", "", self.row_label)


@dataclass(frozen=True)
class ReferenceResolution:
    question: str
    method: str = "structured_evidence"


class ConversationReferenceResolver:
    """Resolve narrow table references from persisted answer evidence.

    The resolver only rewrites when prior evidence identifies the source,
    period and table coordinates unambiguously. Other follow-ups remain on the
    existing model-based contextualization path.
    """

    _PLURAL_REFERENCE = re.compile(r"两地|两个地区|这两个地区|两者|二者")
    _SHORT_ENTITY = re.compile(r"^([\u4e00-\u9fff]{2,8})呢[？?]?$")
    _NON_ENTITY_FOLLOW_UPS = {
        "具体", "这个", "那个", "这些", "那些", "另外", "其中", "它们",
    }

    def resolve(self, question: str, history: list[dict]) -> ReferenceResolution | None:
        facts = self._table_facts(history)
        if not facts:
            return None

        short_match = self._SHORT_ENTITY.fullmatch(question.strip())
        if short_match and short_match.group(1) not in self._NON_ENTITY_FOLLOW_UPS:
            return self._resolve_short_entity(
                short_match.group(1), history, facts[-1]
            )

        if self._PLURAL_REFERENCE.search(question):
            pair = self._latest_compatible_pair(facts)
            if pair:
                return self._resolve_pair(question, pair)
        return None

    def _resolve_short_entity(
        self,
        entity: str,
        history: list[dict],
        fact: TableFact,
    ) -> ReferenceResolution:
        previous_user = next(
            (
                str(message.get("content", "")).strip()
                for message in reversed(history)
                if message.get("role") == "user"
                and str(message.get("content", "")).strip()
            ),
            "",
        )
        rewritten = previous_user
        if fact.display_row in rewritten:
            rewritten = rewritten.replace(fact.display_row, entity, 1)
        elif fact.row_label in rewritten:
            rewritten = rewritten.replace(fact.row_label, entity, 1)
        else:
            metric = (
                "原保险保费收入合计"
                if fact.column_header == "合计"
                else f"{fact.column_header}收入"
            )
            rewritten = f"{fact.period}，{entity}的{metric}是多少？"

        if f"《{fact.source_title}》" not in rewritten:
            rewritten = f"根据《{fact.source_title}》，{rewritten}"
        return ReferenceResolution(question=rewritten)

    def _resolve_pair(
        self,
        question: str,
        pair: tuple[TableFact, TableFact],
    ) -> ReferenceResolution:
        first, second = pair
        entities = f"{first.row_label}和{second.row_label}"
        rewritten = self._PLURAL_REFERENCE.sub(entities, question, count=1)
        if first.period and first.period not in rewritten:
            rewritten = f"{first.period}，{rewritten}"
        if f"《{first.source_title}》" not in rewritten:
            rewritten = f"根据《{first.source_title}》，{rewritten}"
        return ReferenceResolution(question=rewritten)

    def _latest_compatible_pair(
        self,
        facts: list[TableFact],
    ) -> tuple[TableFact, TableFact] | None:
        latest = facts[-1]
        selected = []
        seen_rows = set()
        for fact in reversed(facts):
            if (
                fact.source_title != latest.source_title
                or fact.period != latest.period
                or fact.column_header != latest.column_header
                or fact.display_row in seen_rows
            ):
                continue
            selected.append(fact)
            seen_rows.add(fact.display_row)
            if len(selected) == 2:
                first, second = reversed(selected)
                return first, second
        return None

    def _table_facts(self, history: list[dict]) -> list[TableFact]:
        facts = []
        for message in history[-12:]:
            if message.get("role") != "assistant":
                continue
            evidence = message.get("evidence")
            if not isinstance(evidence, list):
                continue
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", ""))
                row_match = re.search(r"行指标「([^」]+)」", text)
                column_match = re.search(r"列口径「([^」]+)」", text)
                period_match = re.search(r"期间：([^。；]+)", text)
                source_title = str(item.get("source_title", "")).strip()
                if not (source_title and row_match and column_match and period_match):
                    continue
                facts.append(TableFact(
                    source_title=source_title,
                    period=period_match.group(1).strip(),
                    row_label=row_match.group(1).strip(),
                    column_header=column_match.group(1).strip(),
                ))
        return facts
