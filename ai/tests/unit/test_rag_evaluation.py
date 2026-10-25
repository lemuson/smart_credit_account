from pathlib import Path

import pytest

from scripts.evaluate_rag_demo import load_questions


def test_load_questions_reads_only_numbered_table_rows(tmp_path: Path) -> None:
    path = tmp_path / "questions.md"
    path.write_text(
        "# Набор\n\n"
        "| № | Вопрос | Источник | Проверка |\n"
        "|---|---|---|---|\n"
        "| 1 | Первый вопрос? | KB-01 | Факт |\n"
        "| 2 | Второй вопрос? | Backend | Tool |\n",
        encoding="utf-8",
    )

    questions = load_questions(path)

    assert [(row.id, row.question, row.expected_source) for row in questions] == [
        (1, "Первый вопрос?", "KB-01"),
        (2, "Второй вопрос?", "Backend"),
    ]


def test_load_questions_rejects_empty_dataset(tmp_path: Path) -> None:
    path = tmp_path / "questions.md"
    path.write_text("# Нет таблицы\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No evaluation questions"):
        load_questions(path)
