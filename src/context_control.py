import math
import os
import re
from dataclasses import dataclass
from uuid import UUID

from src.conversations import ConversationStore


SUMMARY_PREFIX = "【历史对话摘要】"


@dataclass(frozen=True)
class ContextSettings:
    normal_input_tokens: int = 65_536
    complex_input_tokens: int = 131_072
    hard_input_tokens: int = 204_800
    output_reserve_tokens: int = 8_192
    recent_history_tokens: int = 16_384
    summary_tokens: int = 8_192

    @classmethod
    def from_env(cls) -> "ContextSettings":
        settings = cls(
            normal_input_tokens=int(os.getenv("CONTEXT_NORMAL_INPUT_TOKENS", "65536")),
            complex_input_tokens=int(os.getenv("CONTEXT_COMPLEX_INPUT_TOKENS", "131072")),
            hard_input_tokens=int(os.getenv("CONTEXT_HARD_INPUT_TOKENS", "204800")),
            output_reserve_tokens=int(os.getenv("CONTEXT_OUTPUT_RESERVE_TOKENS", "8192")),
            recent_history_tokens=int(os.getenv("CONTEXT_RECENT_HISTORY_TOKENS", "16384")),
            summary_tokens=int(os.getenv("CONTEXT_SUMMARY_TOKENS", "8192")),
        )
        if not 8_192 <= settings.output_reserve_tokens <= 16_384:
            raise ValueError("CONTEXT_OUTPUT_RESERVE_TOKENS must be between 8192 and 16384")
        if not (
            settings.normal_input_tokens
            <= settings.complex_input_tokens
            <= settings.hard_input_tokens
        ):
            raise ValueError("context input budgets must be ordered normal <= complex <= hard")
        if settings.recent_history_tokens <= 0 or settings.summary_tokens <= 0:
            raise ValueError("history and summary budgets must be positive")
        return settings


def estimate_tokens(text: str) -> int:
    """Deterministic conservative estimate for mixed Chinese/ASCII prompts."""
    weighted = sum(1 if ord(char) > 127 else 0.25 for char in text)
    return max(1, math.ceil(weighted)) if text else 0


def message_tokens(message: dict[str, str]) -> int:
    return 4 + estimate_tokens(str(message.get("content", "")))


@dataclass(frozen=True)
class AssembledContext:
    system: str
    user: str
    history: list[dict[str, str]]

    @property
    def messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system},
            *self.history,
            {"role": "user", "content": self.user},
        ]


class ContextAssembler:
    def __init__(self, settings: ContextSettings | None = None):
        self.settings = settings or ContextSettings.from_env()

    def assemble(
        self,
        *,
        system: str,
        user: str,
        history: list[dict[str, str]] | None,
        complex_query: bool,
    ) -> AssembledContext:
        tier_budget = (
            self.settings.complex_input_tokens
            if complex_query
            else self.settings.normal_input_tokens
        )
        prompt_budget = min(tier_budget, self.settings.hard_input_tokens)
        prompt_budget -= self.settings.output_reserve_tokens

        system_message = {"role": "system", "content": system}
        system_cost = message_tokens(system_message)
        if system_cost + 4 > prompt_budget:
            raise ValueError("system prompt exceeds the configured context budget")
        user = self._fit_user_prompt(user, prompt_budget - system_cost - 4)
        user_message = {"role": "user", "content": user}
        remaining = prompt_budget - system_cost - message_tokens(user_message)

        history = history or []
        summaries = [
            message for message in history
            if message.get("role") == "system"
            or str(message.get("content", "")).startswith(SUMMARY_PREFIX)
        ]
        recent = [message for message in history if message not in summaries]
        selected = []

        for message in summaries:
            cost = message_tokens(message)
            if cost <= remaining:
                selected.append(message)
                remaining -= cost
                continue
            if remaining > 4:
                selected.append({
                    "role": "system",
                    "content": self._fit_text(
                        str(message.get("content", "")),
                        remaining - 4,
                    ),
                })
                remaining = 0
            break

        selected_recent = []
        for message in reversed(recent):
            cost = message_tokens(message)
            if cost > remaining:
                break
            selected_recent.append(message)
            remaining -= cost
        selected_recent.reverse()
        selected.extend(selected_recent)
        return AssembledContext(system=system, user=user, history=selected)

    def _fit_user_prompt(self, prompt: str, token_budget: int) -> str:
        if estimate_tokens(prompt) <= token_budget:
            return prompt
        marker = "\n\n【问题】\n"
        if marker not in prompt:
            return self._fit_text(prompt, token_budget)
        evidence, question = prompt.rsplit(marker, 1)
        required = marker + question
        required_tokens = estimate_tokens(required)
        if required_tokens >= token_budget:
            return self._fit_text(required, token_budget)
        return self._fit_text(evidence, token_budget - required_tokens) + required

    @staticmethod
    def _fit_text(text: str, token_budget: int) -> str:
        if token_budget <= 0:
            return ""
        result = []
        used = 0.0
        for char in text:
            used += 1 if ord(char) > 127 else 0.25
            if math.ceil(used) > token_budget:
                break
            result.append(char)
        return "".join(result)


def _recent_messages(messages: list[dict[str, str]], budget: int) -> tuple[list, int]:
    selected = []
    used = 0
    for message in reversed(messages):
        cost = message_tokens(message)
        if used + cost > budget:
            break
        selected.append(message)
        used += cost
    selected.reverse()
    return selected, len(messages) - len(selected)


def select_controlled_history(
    messages: list[dict[str, str]],
    settings: ContextSettings | None = None,
) -> list[dict[str, str]]:
    settings = settings or ContextSettings.from_env()
    summaries = [
        message for message in messages
        if message.get("role") == "system"
        and str(message.get("content", "")).startswith(SUMMARY_PREFIX)
    ]
    recent_candidates = [
        message for message in messages
        if message.get("role") in {"user", "assistant"}
    ]
    recent, _ = _recent_messages(
        recent_candidates,
        settings.recent_history_tokens,
    )
    if not summaries:
        return recent
    summary = summaries[-1]
    return [{
        "role": "system",
        "content": ContextAssembler._fit_text(
            str(summary.get("content", "")),
            settings.summary_tokens,
        ),
    }, *recent]


def _compact_summary(
    previous: str | None,
    messages: list[dict[str, str]],
    budget: int,
) -> str:
    lines = []
    if previous:
        lines.extend(previous.removeprefix(SUMMARY_PREFIX).strip().splitlines())
    labels = {"user": "用户", "assistant": "助手"}
    for message in messages:
        content = re.sub(r"\s+", " ", str(message.get("content", ""))).strip()
        lines.append(f"{labels.get(message.get('role'), '消息')}：{content}")

    kept = []
    used = estimate_tokens(SUMMARY_PREFIX)
    for line in reversed(lines):
        cost = estimate_tokens(line) + 1
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    return SUMMARY_PREFIX + ("\n" + "\n".join(kept) if kept else "")


def prepare_conversation_history(
    store: ConversationStore,
    conversation_id: UUID,
    request_id: str,
    settings: ContextSettings | None = None,
) -> list[dict[str, str]]:
    settings = settings or ContextSettings.from_env()
    history = store.history_for_turn(conversation_id, request_id)
    summary, summarized_count = store.context_state(conversation_id)
    summarized_count = min(summarized_count, len(history))
    pending = history[summarized_count:]
    recent, older_count = _recent_messages(
        pending,
        settings.recent_history_tokens,
    )

    if older_count:
        summary = _compact_summary(
            summary,
            pending[:older_count],
            settings.summary_tokens,
        )
        store.update_context_summary(
            conversation_id,
            expected_message_count=summarized_count,
            summary=summary,
            message_count=summarized_count + older_count,
        )

    if summary:
        return [{"role": "system", "content": summary}, *recent]
    return recent
