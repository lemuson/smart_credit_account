from __future__ import annotations

import re
from decimal import Decimal
from uuid import UUID

from app.schemas.tools import ToolCall

UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
PRODUCT_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b", re.IGNORECASE)

DEMO_KNOWLEDGE_PATTERN = re.compile(
    r"\bKB-\d{2}\b|"
    r"\b(?:учебн|демонстрационн)\w*(?:\s+\w+){0,3}\s+"
    r"(?:чек[-\s]?лист|комплект|перечень|пример|база|материал|документ)\w*|"
    r"\b(?:чек[-\s]?лист|комплект|перечень)\w*(?:\s+\w+){0,3}\s+"
    r"(?:учебн|демонстрационн)\w*",
    re.IGNORECASE,
)

_NO_READ_TOOL_PATTERNS = (
    r"системн\w*\s+промпт",
    r"(?:вызови|запусти)\s+shell",
    r"/etc/",
    r"сменить\s+user_id",
    r"чуж\w*\s+заяв",
    r"гарантир",
    r"окончательн\w*\s+решен",
    r"автоматически\s+отправ",
    r"измени\s+сумм",
    r"токен\w*\s+авторизац",
    r"внутренн\w*\s+заголов",
    r"реальн\w*\s+предложен",
)


def _amount(message: str) -> Decimal | None:
    matches = re.finditer(
        r"\b(\d+(?:[.,]\d+)?)\s*(млн|миллион\w*|тыс\w*)?\s*(?:руб\w*)?",
        message,
        re.IGNORECASE,
    )
    for match in matches:
        value = Decimal(match.group(1).replace(",", "."))
        unit = (match.group(2) or "").casefold()
        if unit.startswith(("млн", "миллион")):
            return value * 1_000_000
        if unit.startswith("тыс"):
            return value * 1_000
        if "руб" in match.group(0).casefold():
            return value
        # Bare numbers are too ambiguous: they may be a term or an ordinal.
    return None


def _term_months(message: str) -> int | None:
    month = re.search(r"\b(\d{1,3})\s*месяц\w*", message, re.IGNORECASE)
    if month:
        return int(month.group(1))
    year = re.search(r"\b(\d{1,2})\s*(?:год|года|лет)\b", message, re.IGNORECASE)
    return int(year.group(1)) * 12 if year else None


def _purpose(message: str) -> str | None:
    match = re.search(r"\bна\s+([^?.!,]+)", message, re.IGNORECASE)
    if match is None:
        return None
    purpose = match.group(1).strip()
    if re.search(r"\d", purpose):
        return None
    purpose = re.split(r"\s+(?:и|сроком)\s+", purpose, maxsplit=1)[0].strip()
    return purpose[:200] or None


def requests_demo_knowledge(message: str) -> bool:
    """Return whether the user explicitly asks about the demo knowledge corpus."""
    return bool(DEMO_KNOWLEDGE_PATTERN.search(message))


def plan_tool_calls(message: str) -> list[ToolCall]:
    """Plan only high-confidence read-only calls; ambiguous requests stay with the LLM."""
    normalized = message.casefold()
    uuid_matches = [str(UUID(value)) for value in UUID_PATTERN.findall(message)]
    scoring_intent = re.search(
        r"ml[-\s]?оцен|скоринг|\bscoring\b|assessment|what[-\s]?if|симуляц|\bпрогноз\w*|"
        r"(?:оценк|прогноз).*(?:фактор|признак|logit|процент|гарант)|"
        r"(?:фактор|признак|logit|гарант).*(?:оценк|прогноз)",
        normalized,
    )
    if uuid_matches and scoring_intent:
        arguments = {"assessment_id": uuid_matches[0]}
        if len(uuid_matches) > 1:
            arguments["what_if_id"] = uuid_matches[1]
        return [ToolCall(name="get_scoring_result", arguments=arguments)]

    if any(re.search(pattern, normalized) for pattern in _NO_READ_TOOL_PATTERNS):
        return []

    if uuid_matches:
        application_id = uuid_matches[0]
        if re.search(r"прове\w*|ошиб\w*|заполн\w*", normalized):
            return [
                ToolCall(name="validate_application", arguments={"application_id": application_id})
            ]
        if re.search(r"статус|что\s+.*дальше|следующ\w*\s+действ", normalized):
            return [
                ToolCall(
                    name="get_application_status", arguments={"application_id": application_id}
                )
            ]
        return []

    product_ids = list(dict.fromkeys(PRODUCT_ID_PATTERN.findall(normalized)))
    if product_ids:
        if re.search(r"документ", normalized):
            return [
                ToolCall(name="get_required_documents", arguments={"product_id": product_id})
                for product_id in product_ids
            ]
        calls: list[ToolCall] = []
        if re.search(r"почему|подой\w*|соответств", normalized):
            calls.append(ToolCall(name="get_user_profile", arguments={}))
        calls.extend(
            ToolCall(name="get_product_details", arguments={"product_id": product_id})
            for product_id in product_ids
        )
        return calls

    if re.search(r"сведен\w*.*(?:бизнес|профил)|(?:бизнес|профил).*сведен", normalized):
        return [ToolCall(name="get_user_profile", arguments={})]

    search_intent = re.search(
        r"кредитн\w*\s+продукт|какие\s+кредит|подбер\w*\s+.*кредит|"
        r"что\s+подходит|мне\s+нужн|нужн\w*\s+деньг|кредит\s+на|назови\s+ставк|"
        r"(?:ставк|лимит)\w*.*кредит|кредит\w*.*(?:ставк|лимит)",
        normalized,
    )
    if not search_intent:
        return []

    calls = []
    if re.search(r"мо(?:ему|й)\s+ип|подбер\w*\s+мне", normalized):
        calls.append(ToolCall(name="get_user_profile", arguments={}))
    calls.append(
        ToolCall(
            name="search_credit_products",
            arguments={
                "purpose": _purpose(message),
                "amount": _amount(message),
                "term_months": _term_months(message),
            },
        )
    )
    return calls
