from __future__ import annotations

import json
import re
from typing import Any

from app.agent.context import ContextManager
from app.agent.planner import plan_tool_calls
from app.core.config import Settings
from app.core.exceptions import AIServiceError
from app.llm.client import LLMClient
from app.llm.prompts import RAG_CONTEXT_TEMPLATE, SYSTEM_PROMPT
from app.rag.retriever import RagRetriever
from app.schemas.messages import AnswerSource, ChatRequest, ChatResult
from app.schemas.tools import ToolCall
from app.tools.registry import ToolRegistry


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

        planned_calls = plan_tool_calls(request.message)
        if planned_calls:
            self._append_assistant_tool_calls(messages, planned_calls)
            await self._execute_tool_calls(messages, planned_calls, request)
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Однозначные read-only инструменты уже выполнены маршрутизатором. "
                        "Сформируй ответ строго по их результатам и не вызывай их повторно. "
                        "Если данные помечены is_demo=true, явно назови их демонстрационными."
                    ),
                }
            )
            if self.retriever is not None:
                rag_attempted = True
                try:
                    rag_rows = await self.retriever.retrieve(request.message)
                except AIServiceError:
                    rag_rows = []
                if rag_rows:
                    messages.append(
                        {
                            "role": "system",
                            "content": RAG_CONTEXT_TEMPLATE.format(
                                context=self.retriever.format_context(rag_rows)
                            ),
                        }
                    )

        answer = ""
        language_retry_used = False
        for _ in range(self.settings.llm_max_tool_rounds):
            reply = await self.llm.chat(messages, [] if planned_calls else self.registry.schemas)
            if not reply.tool_calls:
                if not rag_attempted and self.retriever is not None:
                    rag_attempted = True
                    try:
                        rag_rows = await self.retriever.retrieve(request.message)
                    except AIServiceError:
                        rag_rows = []
                    if rag_rows:
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
                        continue
                if re.search(r"[\u3400-\u9fff]", reply.content) and not language_retry_used:
                    language_retry_used = True
                    messages.append({"role": "assistant", "content": reply.content})
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "Предыдущий черновик содержит китайские символы. "
                                "Перепиши ответ полностью на русском языке, сохрани факты."
                            ),
                        }
                    )
                    continue
                answer = reply.content.strip()
                break

            self._append_assistant_tool_calls(messages, reply.tool_calls, reply.content)
            await self._execute_tool_calls(messages, reply.tool_calls, request)
            if not rag_attempted and self.retriever is not None:
                rag_attempted = True
                try:
                    rag_rows = await self.retriever.retrieve(request.message)
                except AIServiceError:
                    rag_rows = []
                if rag_rows:
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
    ) -> None:
        for call in calls:
            try:
                result = await self.registry.execute(call.name, call.arguments, request)
            except AIServiceError as exc:
                result_payload = {
                    "ok": False,
                    "error_code": exc.code,
                    "message": str(exc),
                }
            else:
                result_payload = result.model_dump(mode="json")
            messages.append(
                {
                    "role": "tool",
                    "tool_name": call.name,
                    "content": json.dumps(result_payload, ensure_ascii=False),
                }
            )
