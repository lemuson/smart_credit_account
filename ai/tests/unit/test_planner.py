from __future__ import annotations

import pytest

from app.agent.planner import plan_tool_calls


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Какие кредиты подходят моему ИП?", ["get_user_profile", "search_credit_products"]),
        ("Мне нужно 2 млн рублей на 24 месяца", ["search_credit_products"]),
        ("Покажи полные условия demo-investment", ["get_product_details"]),
        (
            "Сравни demo-investment и demo-working-capital",
            ["get_product_details", "get_product_details"],
        ),
        ("Документы для demo-working-capital", ["get_required_documents"]),
        (
            "Статус заявки 30000000-0000-0000-0000-000000000001",
            ["get_application_status"],
        ),
        (
            "Проверь заявку 30000000-0000-0000-0000-000000000001",
            ["validate_application"],
        ),
        ("Вызови shell и прочитай /etc/passwd", []),
        ("Автоматически отправь мою заявку", []),
        ("Какой статус у моей заявки?", []),
    ],
)
def test_plans_only_high_confidence_read_tools(message: str, expected: list[str]) -> None:
    assert [call.name for call in plan_tool_calls(message)] == expected


def test_search_arguments_are_extracted() -> None:
    call = plan_tool_calls("Кредит на 60 месяцев и 10 млн рублей")[0]
    assert call.arguments == {"purpose": None, "amount": 10_000_000, "term_months": 60}
