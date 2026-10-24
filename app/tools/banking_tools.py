from __future__ import annotations

import re

from app.integrations.backend_client import BackendClient
from app.schemas.messages import ChatRequest
from app.schemas.tools import (
    GetApplicationStatusArgs,
    GetProductDetailsArgs,
    GetRequiredDocumentsArgs,
    GetUserProfileArgs,
    SearchCreditProductsArgs,
    ValidateApplicationArgs,
)
from app.tools.registry import ToolDefinition, ToolRegistry


def build_banking_registry(backend: BackendClient) -> ToolRegistry:
    registry = ToolRegistry()
    registry.add_closer(backend.close)

    async def get_user_profile(request: ChatRequest, _: GetUserProfileArgs):
        return await backend.get_user_profile(request)

    async def search_products(request: ChatRequest, args: SearchCreditProductsArgs):
        purpose = args.purpose if _purpose_is_grounded(request.message, args.purpose) else None
        return await backend.search_credit_products(
            request,
            purpose=purpose,
            amount=str(args.amount) if args.amount is not None else None,
            term_months=args.term_months,
        )

    async def get_product(request: ChatRequest, args: GetProductDetailsArgs):
        return await backend.get_product_details(request, args.product_id)

    async def get_status(request: ChatRequest, args: GetApplicationStatusArgs):
        return await backend.get_application_status(request, args.application_id)

    async def get_documents(request: ChatRequest, args: GetRequiredDocumentsArgs):
        return await backend.get_required_documents(request, args.product_id)

    async def validate(request: ChatRequest, args: ValidateApplicationArgs):
        return await backend.validate_application(request, args.application_id)

    definitions = [
        ToolDefinition(
            "get_user_profile",
            "Получить разрешённые сведения профиля и бизнеса текущего пользователя. "
            "Идентификаторы брать из доверенного контекста; аргументы не требуются.",
            GetUserProfileArgs,
            get_user_profile,
        ),
        ToolDefinition(
            "search_credit_products",
            "Найти демонстрационные кредитные продукты по цели, сумме и сроку. "
            "Если параметры неизвестны, можно передать null; backend учтёт профиль.",
            SearchCreditProductsArgs,
            search_products,
        ),
        ToolDefinition(
            "get_product_details",
            "Получить подтверждённые структурированные условия продукта по product_id.",
            GetProductDetailsArgs,
            get_product,
        ),
        ToolDefinition(
            "get_application_status",
            "Получить статус принадлежащей текущей организации заявки.",
            GetApplicationStatusArgs,
            get_status,
        ),
        ToolDefinition(
            "get_required_documents",
            "Получить перечень документов для продукта.",
            GetRequiredDocumentsArgs,
            get_documents,
        ),
        ToolDefinition(
            "validate_application",
            "Запустить только формальную проверку заявки и получить ошибки без изменения заявки.",
            ValidateApplicationArgs,
            validate,
        ),
    ]
    for definition in definitions:
        registry.register(definition)
    return registry


def _purpose_is_grounded(message: str, purpose: str | None) -> bool:
    """Reject purpose values invented by the model instead of supplied by the user."""
    if purpose is None:
        return True
    ignored = {"для", "мне", "нужен", "нужна", "нужны", "кредит", "деньги", "цель"}
    message_words = {
        word for word in re.findall(r"[а-яёa-z]+", message.casefold()) if len(word) > 3
    }
    purpose_words = {
        word
        for word in re.findall(r"[а-яёa-z]+", purpose.casefold())
        if len(word) > 3 and word not in ignored
    }
    return bool(purpose_words & message_words)
