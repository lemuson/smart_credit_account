from __future__ import annotations

from uuid import UUID

ORG_1 = UUID("10000000-0000-0000-0000-000000000001")
ORG_2 = UUID("10000000-0000-0000-0000-000000000002")
USER_1 = UUID("20000000-0000-0000-0000-000000000001")
USER_2 = UUID("20000000-0000-0000-0000-000000000002")
APP_DRAFT = UUID("30000000-0000-0000-0000-000000000001")
APP_OTHER = UUID("30000000-0000-0000-0000-000000000002")

PROFILES = {
    USER_1: {
        "user_id": str(USER_1),
        "organization_id": str(ORG_1),
        "legal_form": "ИП",
        "industry": "розничная торговля",
        "business_age_months": 30,
        "annual_revenue": "7200000.00",
        "region": "Москва",
        "is_demo": True,
    },
    USER_2: {
        "user_id": str(USER_2),
        "organization_id": str(ORG_2),
        "legal_form": "ООО",
        "industry": "услуги",
        "business_age_months": 8,
        "annual_revenue": "2400000.00",
        "region": "Казань",
        "is_demo": True,
    },
}

PRODUCTS = {
    "demo-working-capital": {
        "product_id": "demo-working-capital",
        "name": "Демо Оборотный капитал",
        "purpose": ["закупка товара", "пополнение оборотных средств"],
        "min_amount": "300000.00",
        "max_amount": "5000000.00",
        "min_term_months": 6,
        "max_term_months": 36,
        "annual_rate_percent": "18.50",
        "min_business_age_months": 12,
        "legal_forms": ["ИП", "ООО"],
        "required_documents": [
            {"code": "tax_return", "name": "Налоговая декларация", "required": True},
            {"code": "bank_statement", "name": "Выписка по расчётному счёту", "required": True},
        ],
        "restrictions": ["Только демонстрационный продукт", "Не является офертой"],
        "is_demo": True,
    },
    "demo-investment": {
        "product_id": "demo-investment",
        "name": "Демо Инвестиционный",
        "purpose": ["покупка оборудования", "модернизация"],
        "min_amount": "1000000.00",
        "max_amount": "15000000.00",
        "min_term_months": 12,
        "max_term_months": 60,
        "annual_rate_percent": "17.90",
        "min_business_age_months": 24,
        "legal_forms": ["ИП", "ООО"],
        "required_documents": [
            {"code": "financial_statements", "name": "Финансовая отчётность", "required": True},
            {"code": "equipment_offer", "name": "Коммерческое предложение", "required": True},
        ],
        "restrictions": ["Целевое использование", "Только демонстрационный продукт"],
        "is_demo": True,
    },
    "demo-express": {
        "product_id": "demo-express",
        "name": "Демо Экспресс",
        "purpose": ["текущие расходы"],
        "min_amount": "100000.00",
        "max_amount": "1000000.00",
        "min_term_months": 3,
        "max_term_months": 18,
        "annual_rate_percent": "21.00",
        "min_business_age_months": 6,
        "legal_forms": ["ИП"],
        "required_documents": [
            {"code": "bank_statement", "name": "Выписка по расчётному счёту", "required": True}
        ],
        "restrictions": ["Для ИП", "Только демонстрационный продукт"],
        "is_demo": True,
    },
}

APPLICATIONS = {
    APP_DRAFT: {
        "application_id": str(APP_DRAFT),
        "organization_id": str(ORG_1),
        "product_id": "demo-investment",
        "status": "draft",
        "status_label": "Черновик",
        "next_action": "Добавьте коммерческое предложение и укажите срок кредита",
        "fields": {"amount": "2000000.00", "term_months": None},
        "documents": ["financial_statements"],
        "is_demo": True,
    },
    APP_OTHER: {
        "application_id": str(APP_OTHER),
        "organization_id": str(ORG_2),
        "product_id": "demo-express",
        "status": "submitted",
        "status_label": "Отправлена",
        "next_action": "Ожидайте проверки",
        "fields": {"amount": "500000.00", "term_months": 12},
        "documents": ["bank_statement"],
        "is_demo": True,
    },
}
