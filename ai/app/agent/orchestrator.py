from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.agent.context import ContextManager
from app.agent.planner import plan_tool_calls, requests_demo_knowledge
from app.core.config import Settings
from app.core.exceptions import AIServiceError
from app.llm.client import LLMClient
from app.llm.prompts import RAG_CONTEXT_TEMPLATE, SYSTEM_PROMPT
from app.rag.grounding import (
    GroundedEnumeration,
    extract_relevant_enumeration,
    missing_enumeration_items,
    render_grounded_enumeration,
)
from app.rag.retriever import RagRetriever
from app.schemas.messages import AnswerSource, ChatRequest, ChatResult
from app.schemas.tools import ToolCall
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ChatOrchestrator:
    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        registry: ToolRegistry,
        retriever: RagRetriever | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.registry = registry
        self.retriever = retriever
        self.context = ContextManager(settings.context_max_messages, settings.context_max_chars)

    async def close(self) -> None:
        await self.registry.close()
        llm_close = getattr(self.llm, "close", None)
        if llm_close is not None:
            await llm_close()
        if self.retriever is not None:
            embeddings_close = getattr(self.retriever.embeddings, "close", None)
            if embeddings_close is not None:
                await embeddings_close()

    async def handle(self, request: ChatRequest) -> ChatResult:
        rag_rows = []
        rag_attempted = self.retriever is None
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(
            {"role": item.role, "content": item.content}
            for item in self.context.trim(request.history)
        )
        messages.append({"role": "user", "content": request.message})

        demo_knowledge_requested = requests_demo_knowledge(request.message)
        confirmed_absent = bool(
            re.search(
                r"откуда\s+взять.*документ|продукт\w*.*нет\s+в\s+базе",
                request.message,
                re.IGNORECASE,
            )
        )
        rag_requested = demo_knowledge_requested or confirmed_absent
        retrieval_query = request.message
        if re.search(r"игнорир\w*.*(?:гарантир|одобр|решен)", request.message, re.IGNORECASE):
            retrieval_query += (
                " Ограничения демонстрационной базы знаний, синтетическая ML-оценка "
                "и решение банка."
            )
        planned_calls = [] if confirmed_absent else plan_tool_calls(request.message)
        rag_only = rag_requested and not planned_calls
        scoring_payload: dict[str, Any] | None = None
        expected_enumeration: GroundedEnumeration | None = None
        demo_tool_used = False
        if planned_calls:
            self._append_assistant_tool_calls(messages, planned_calls)
            tool_payloads = await self._execute_tool_calls(messages, planned_calls, request)
            demo_tool_used = any(self._payload_is_demo(payload) for payload in tool_payloads)
            if planned_calls[0].name == "get_scoring_result" and tool_payloads:
                candidate = tool_payloads[0]
                if candidate.get("ok") and isinstance(candidate.get("data"), dict):
                    scoring_payload = candidate["data"]
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Однозначные read-only инструменты уже выполнены маршрутизатором. "
                        "Сформируй ответ строго по их результатам и не вызывай их повторно. "
                        "Ставки, суммы, сроки, продуктовые требования и персональные статусы из "
                        "результата называй данными Backend, а не данными базы знаний. "
                        "Если данные помечены is_demo=true, явно назови их демонстрационными."
                    ),
                }
            )
            if scoring_payload is not None:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Это сохранённый scoring result. Не вычисляй и не меняй ни одного "
                            "числа. Используй только числовые значения из tool result. "
                            "Передай предупреждение о синтетических данных. Вклады факторов "
                            "выражены в logit, кроме явно названного delta_percentage_points."
                        ),
                    }
                )
            rag_attempted = not rag_requested

        answer = ""
        language_retry_used = False
        scoring_retry_used = False
        enumeration_retry_used = False
        for _ in range(self.settings.llm_max_tool_rounds):
            tool_schemas = [] if planned_calls or rag_only else self.registry.schemas
            reply = await self.llm.chat(messages, tool_schemas)
            if not reply.tool_calls:
                if not rag_attempted and self.retriever is not None:
                    rag_attempted = True
                    try:
                        rag_rows = await self.retriever.retrieve(retrieval_query)
                    except AIServiceError:
                        rag_rows = []
                    if rag_rows:
                        expected_enumeration = extract_relevant_enumeration(
                            request.message, rag_rows
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": RAG_CONTEXT_TEMPLATE.format(
                                    context=self.retriever.format_context(rag_rows)
                                ),
                            }
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Сформируй окончательный ответ на исходный вопрос. "
                                    "Не изменяй параметры уже выполненных инструментов "
                                    "на основании справочного контекста."
                                ),
                            }
                        )
                    else:
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "В демонстрационной базе знаний нет релевантного контекста "
                                    "для исходного вопроса. Не отвечай из общих знаний и не "
                                    "придумывай источник. Кратко сообщи, что подтверждённых "
                                    "сведений в базе нет."
                                ),
                            }
                        )
                    continue
                foreign_draft = re.search(r"[\u3400-\u9fff]", reply.content) or re.match(
                    r"\s*(?:no|yes)\s*[,!.]", reply.content, re.IGNORECASE
                )
                if foreign_draft and not language_retry_used:
                    language_retry_used = True
                    messages.append({"role": "assistant", "content": reply.content})
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Предыдущий черновик содержит фрагмент не на русском языке. "
                                "Перепиши ответ полностью на русском языке, сохрани факты."
                            ),
                        }
                    )
                    continue
                if foreign_draft:
                    if re.match(r"\s*no\s*[,!.]", reply.content, re.IGNORECASE):
                        reply.content = re.sub(
                            r"^\s*no\b", "Нет", reply.content, count=1, flags=re.IGNORECASE
                        )
                    elif re.match(r"\s*yes\s*[,!.]", reply.content, re.IGNORECASE):
                        reply.content = re.sub(
                            r"^\s*yes\b", "Да", reply.content, count=1, flags=re.IGNORECASE
                        )
                    else:
                        reply.content = (
                            "Не удалось безопасно сформировать ответ полностью на русском языке. "
                            "Пожалуйста, повторите вопрос."
                        )
                if expected_enumeration is not None:
                    missing_items = missing_enumeration_items(reply.content, expected_enumeration)
                    if missing_items and not enumeration_retry_used:
                        enumeration_retry_used = True
                        required_items = "\n".join(
                            f"{index}. {item}"
                            for index, item in enumerate(expected_enumeration.items, start=1)
                        )
                        messages.append({"role": "assistant", "content": reply.content})
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "Предыдущий черновик пропустил позиции документального "
                                    "перечня. Перепиши ответ и отрази каждую позицию без "
                                    "сокращений. Перечень извлечён из найденного источника:\n"
                                    f"{required_items}"
                                ),
                            }
                        )
                        continue
                    if missing_items:
                        answer = render_grounded_enumeration(expected_enumeration)
                        break
                if (
                    scoring_payload is not None
                    and self._has_ungrounded_number(reply.content, scoring_payload)
                    and not scoring_retry_used
                ):
                    scoring_retry_used = True
                    messages.append({"role": "assistant", "content": reply.content})
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Предыдущий черновик изменил или добавил число. Перепиши ответ: "
                                "разрешены только числовые литералы, дословно присутствующие в "
                                "результате get_scoring_result. Числа из вопроса не являются "
                                "источником истины. Ничего не вычисляй."
                            ),
                        }
                    )
                    continue
                if scoring_payload is not None and self._has_ungrounded_number(
                    reply.content, scoring_payload
                ):
                    answer = (
                        "Сохранённый результат получен, но я не могу безопасно объяснить его без "
                        "риска изменить числовые данные. Демонстрационная оценка основана на "
                        "синтетических данных и не является решением банка или гарантией одобрения."
                    )
                    break
                answer = reply.content.strip()
                break

            self._append_assistant_tool_calls(messages, reply.tool_calls, reply.content)
            tool_payloads = await self._execute_tool_calls(messages, reply.tool_calls, request)
            demo_tool_used = demo_tool_used or any(
                self._payload_is_demo(payload) for payload in tool_payloads
            )
            if not rag_attempted and self.retriever is not None:
                rag_attempted = True
                try:
                    rag_rows = await self.retriever.retrieve(retrieval_query)
                except AIServiceError:
                    rag_rows = []
                if rag_rows:
                    expected_enumeration = extract_relevant_enumeration(request.message, rag_rows)
                    messages.append(
                        {
                            "role": "system",
                            "content": RAG_CONTEXT_TEMPLATE.format(
                                context=self.retriever.format_context(rag_rows)
                            ),
                        }
                    )
        else:
            answer = (
                "Не удалось завершить обработку: достигнут безопасный лимит вызовов инструментов. "
                "Уточните вопрос и повторите попытку."
            )

        if not answer:
            answer = "Не удалось сформировать ответ. Пожалуйста, уточните вопрос."

        if scoring_payload is not None and not re.search(
            r"синтетическ|демонстрационн", answer, re.IGNORECASE
        ):
            answer = f"{answer}\n\n{scoring_payload['limitations_warning']}"

        if demo_tool_used and not re.search(r"демонстрационн", answer, re.IGNORECASE):
            answer = (
                f"{answer}\n\nДанные получены из демонстрационного контура и не являются "
                "официальным предложением или решением банка."
            )
        if (
            demo_knowledge_requested
            and rag_rows
            and not re.search(r"демонстрационн|учебн", answer, re.IGNORECASE)
        ):
            answer = (
                f"{answer}\n\nЭто сведения из демонстрационной базы знаний, а не официальные "
                "требования банка."
            )
        answer = self._hide_internal_tool_names(answer)

        sources = [
            AnswerSource(
                document_id=row.chunk.metadata["document_id"],
                source=row.chunk.metadata["source"],
                chunk_id=row.chunk.metadata["chunk_id"],
                document_version=row.chunk.metadata["document_version"],
                excerpt=row.chunk.text[:240],
            )
            for row in rag_rows
        ]
        return ChatResult(
            request_id=request.request_id,
            conversation_id=request.conversation_id,
            status="completed",
            answer=answer,
            sources=sources,
            model=self.settings.ollama_llm_model,
        )

    @staticmethod
    def _append_assistant_tool_calls(
        messages: list[dict[str, Any]], calls: list[ToolCall], content: str = ""
    ) -> None:
        messages.append(
            {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.loads(
                                json.dumps(call.arguments, ensure_ascii=False, default=str)
                            ),
                        },
                    }
                    for call in calls
                ],
            }
        )

    async def _execute_tool_calls(
        self,
        messages: list[dict[str, Any]],
        calls: list[ToolCall],
        request: ChatRequest,
    ) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for call in calls:
            try:
                result = await self.registry.execute(call.name, call.arguments, request)
            except AIServiceError as exc:
                logger.warning(
                    "tool_call_failed",
                    extra={
                        "request_id": str(request.request_id),
                        "tool_name": call.name,
                        "error_code": exc.code,
                    },
                )
                result_payload = {
                    "ok": False,
                    "error_code": exc.code,
                    "message": str(exc),
                }
            else:
                result_payload = result.model_dump(mode="json")
            payloads.append(result_payload)
            messages.append(
                {
                    "role": "tool",
                    "tool_name": call.name,
                    "content": json.dumps(result_payload, ensure_ascii=False),
                }
            )
        return payloads

    @staticmethod
    def _payload_is_demo(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("is_demo") is True:
                return True
            return any(ChatOrchestrator._payload_is_demo(item) for item in value.values())
        if isinstance(value, list):
            return any(ChatOrchestrator._payload_is_demo(item) for item in value)
        return False

    def _hide_internal_tool_names(self, answer: str) -> str:
        for name in sorted(self.registry.names, key=len, reverse=True):
            answer = re.sub(
                rf"`?\b{re.escape(name)}\b`?",
                "внутренний сервис",
                answer,
                flags=re.IGNORECASE,
            )
        return re.sub(
            r"\bBackend\s+Tools?(?:\s+внутренний сервис)?\b",
            "защищённый сервис проверки данных",
            answer,
            flags=re.IGNORECASE,
        )

    @staticmethod
    def _has_ungrounded_number(answer: str, scoring_payload: dict[str, Any]) -> bool:
        number_pattern = re.compile(r"(?<![\w-])[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][+-]?\d+)?")

        def parsed(value: str) -> Decimal | None:
            try:
                return Decimal(value.replace(",", ".").lstrip("+"))
            except InvalidOperation:
                return None

        def payload_numbers(value: Any) -> set[Decimal]:
            if isinstance(value, bool) or value is None:
                return set()
            if isinstance(value, int | float | Decimal):
                return {Decimal(str(value))}
            if isinstance(value, dict):
                result: set[Decimal] = set()
                for nested in value.values():
                    result.update(payload_numbers(nested))
                return result
            if isinstance(value, list):
                result = set()
                for nested in value:
                    result.update(payload_numbers(nested))
                return result
            return set()

        claims = {
            number
            for match in number_pattern.finditer(answer)
            if (number := parsed(match.group(0))) is not None
        }
        return not claims.issubset(payload_numbers(scoring_payload))
