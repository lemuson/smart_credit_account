from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.rag.models import RetrievedChunk

LIST_REQUEST_PATTERN = re.compile(
    r"чек[-\s]?лист|комплект|перечень|список|перечисл|"
    r"(?:какие|сколько)\s+(?:\w+\s+){0,3}(?:документ|пункт|позиц)",
    re.IGNORECASE,
)
SECTION_PATTERN = re.compile(r"(?:^|\n)\d+\.\s+", re.MULTILINE)
ITEM_MARKER_PATTERN = re.compile(r"\((\d+)\)\s*")
WORD_PATTERN = re.compile(r"[а-яёa-z]+", re.IGNORECASE)

_KEYWORD_STOPWORDS = {
    "актуальные",
    "документ",
    "документы",
    "заявителя",
    "заполненная",
    "подтверждение",
    "последние",
    "пример",
    "сведения",
}
_QUESTION_STOPWORDS = {
    "без",
    "для",
    "какие",
    "комплект",
    "нужны",
    "перечень",
    "согласно",
    "учебный",
    "демонстрационный",
    "чек",
    "лист",
}


@dataclass(frozen=True, slots=True)
class GroundedEnumeration:
    document_id: str
    source: str
    items: tuple[str, ...]


def extract_relevant_enumeration(
    question: str, rows: list[RetrievedChunk]
) -> GroundedEnumeration | None:
    """Find the best complete inline enumeration in retrieved source text."""
    if not LIST_REQUEST_PATTERN.search(question):
        return None

    question_words = _words(question) - _QUESTION_STOPWORDS
    candidates: list[tuple[int, int, GroundedEnumeration]] = []
    for row in rows:
        text = row.chunk.text
        for start in ITEM_MARKER_PATTERN.finditer(text):
            if start.group(1) != "1":
                continue
            section_end_match = SECTION_PATTERN.search(text, start.end())
            section_end = section_end_match.start() if section_end_match else len(text)
            block = text[start.start() : section_end]
            markers = list(ITEM_MARKER_PATTERN.finditer(block))
            numbers = [int(marker.group(1)) for marker in markers]
            if len(markers) < 2 or numbers != list(range(1, len(numbers) + 1)):
                continue

            items: list[str] = []
            for index, marker in enumerate(markers):
                end = markers[index + 1].start() if index + 1 < len(markers) else len(block)
                item = _clean_item(block[marker.end() : end])
                if not item:
                    break
                items.append(item)
            if len(items) != len(markers):
                continue

            previous_section = list(SECTION_PATTERN.finditer(text, 0, start.start()))
            context_start = (
                previous_section[-1].start() if previous_section else max(0, start.start() - 240)
            )
            context = text[context_start : start.start()]
            overlap = len(question_words & _words(context))
            candidates.append(
                (
                    overlap,
                    len(items),
                    GroundedEnumeration(
                        document_id=row.chunk.metadata["document_id"],
                        source=row.chunk.metadata["source"],
                        items=tuple(items),
                    ),
                )
            )

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: (candidate[0], candidate[1]))[2]


def missing_enumeration_items(answer: str, enumeration: GroundedEnumeration) -> list[str]:
    answer_stems = _stems(answer)
    missing: list[str] = []
    for item in enumeration.items:
        keywords = _stems(item) - {_stem(word) for word in _KEYWORD_STOPWORDS}
        if not keywords:
            keywords = _stems(item)
        required = max(1, math.ceil(len(keywords) * 0.35))
        if len(keywords & answer_stems) < required:
            missing.append(item)
    return missing


def render_grounded_enumeration(enumeration: GroundedEnumeration) -> str:
    lines = [
        "В демонстрационном перечне указаны следующие позиции:",
        *(f"{index}. {item}." for index, item in enumerate(enumeration.items, start=1)),
        "",
        "Это учебный пример из демонстрационной базы знаний, а не официальные требования банка.",
    ]
    return "\n".join(lines)


def _clean_item(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip(" ,;:\n")
    if ". " in value:
        value = value.split(". ", 1)[0]
    return value.rstrip(".")


def _words(value: str) -> set[str]:
    return {word.casefold() for word in WORD_PATTERN.findall(value)}


def _stem(word: str) -> str:
    normalized = word.casefold()
    return normalized[:5] if len(normalized) > 5 else normalized


def _stems(value: str) -> set[str]:
    return {_stem(word) for word in _words(value)}
