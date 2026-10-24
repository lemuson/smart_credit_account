# Интеграция Main Backend с AI Service

Документ описывает обязательный контракт для замены `mock_backend` настоящим Main Backend без
изменения оркестратора AI Service. Main Backend остаётся источником истины и единственным
компонентом, который хранит пользователей, организации, продукты, заявки и историю диалога.

## Подключение в этом репозитории

Корневой `./start.sh` использует `compose.integrated.yaml`: RabbitMQ, основной backend,
backend AI bridge и этот worker. `mock-backend` не запускается. Для worker заданы
`BACKEND_BASE_URL=http://api:8000`, `BACKEND_CONTRACT=main` и отдельный `BACKEND_SERVICE_TOKEN`.
Режим по умолчанию `BACKEND_CONTRACT=mock` сохранён для самостоятельного демо.
Main adapter сопоставляет список продуктов, `annual_rate`, `required_documents`, `errors` и профиль
с форматом инструментов; русские цели переводятся в enum backend по явному словарю.
Неизвестная цель не снимает фильтр, а возвращает пустой подбор.

Main Backend сохраняет outbox/inbox, историю и tenant ACL. В envelope 1.0 передаётся JWT
делегирования на 10 минут, привязанный к `request_id`, вместо пользовательского access token.
Backend проверяет отдельный shared service secret, audience, user/profile/job, заголовки контекста
и allow-list read-only маршрутов. После завершения job токен не принимается.
Это локальный сервисный контур; production требует отдельной workload identity, TLS и прав брокера.
Подробности и HTTP chat API — в `backend/README.md`.

## Обязанности Main Backend

Main Backend должен аутентифицировать пользователя, проверить его активную организацию, сформировать
доверенный контекст, сохранить запрос, опубликовать его в RabbitMQ и дедуплицировать результат по
`request_id`. При каждом HTTP tool-вызове он повторно проверяет сервисную идентичность, пользовательский
токен, роль и принадлежность ресурса организации.

Main Backend не должен доверять `user_id`, `organization_id`, `application_id` или роли только потому,
что они присутствуют в сообщении. Рекомендуется подписывать envelope либо выдавать короткоживущий
audience-bound токен. Демонстрационный статический `X-Service-Token` предназначен только для локального
Mock Backend.

## RabbitMQ

- Exchange: `ai.events`, direct, durable.
- Request routing key и очередь: `ai.chat.request`.
- Result routing key и очередь: `ai.chat.result`.
- Correlation ID равен строковому `request_id`.
- Сообщения публикуются persistent с publisher confirms.
- Main Backend создаёт durable result queue и подтверждает результат только после транзакционного или
  идемпотентного сохранения.

Семантика — at-least-once. Таблица входящих и исходящих событий должна иметь уникальный индекс по
`request_id`. Повторный результат не должен повторно менять статус, отправлять уведомление или создавать
объекты.

## Контракт запроса

```json
{
  "schema_version": "1.0",
  "request_id": "11111111-1111-1111-1111-111111111111",
  "conversation_id": "22222222-2222-2222-2222-222222222222",
  "user_id": "33333333-3333-3333-3333-333333333333",
  "organization_id": "44444444-4444-4444-4444-444444444444",
  "message": "Какой статус у моей заявки?",
  "history": [{"role": "user", "content": "Я заполнил черновик"}],
  "application_id": "55555555-5555-5555-5555-555555555555",
  "trusted_context": {
    "subject": "auth-subject",
    "roles": ["entrepreneur"],
    "authorization": "Bearer short-lived-token"
  },
  "created_at": "2026-10-20T09:00:00Z"
}
```

История должна быть уже отфильтрована по `conversation_id` и пользователю. AI Service дополнительно
ограничивает её число и размер, но не является постоянным хранилищем.

## Контракт результата

```json
{
  "schema_version": "1.0",
  "request_id": "11111111-1111-1111-1111-111111111111",
  "conversation_id": "22222222-2222-2222-2222-222222222222",
  "status": "completed",
  "answer": "Заявка находится в статусе Черновик.",
  "sources": [],
  "suggested_actions": [],
  "error_code": null,
  "completed_at": "2026-10-20T09:00:03Z",
  "model": "qwen2.5:7b-instruct"
}
```

`status` принимает `completed`, `needs_clarification` или `failed`. `error_code` стабилен для
программной обработки; текст `answer` предназначен пользователю и может меняться.

## HTTP API, которое должен предоставить Main Backend

Все маршруты используют JSON, проверяют `Authorization`, сервисную идентичность и организацию.
Набор полей можно расширять обратно совместимо. Точные демонстрационные примеры приведены в
`api_contracts.md`.

- `GET /api/v1/profile` — разрешённые данные текущего предпринимателя и бизнеса.
- `GET /api/v1/credit-products/search` — детерминированный подбор по `purpose`, `amount`,
  `term_months` и серверному профилю.
- `GET /api/v1/credit-products/{product_id}` — актуальные структурированные условия.
- `GET /api/v1/credit-products/{product_id}/required-documents` — перечень документов.
- `GET /api/v1/applications/{application_id}/status` — статус только доступной заявки.
- `POST /api/v1/applications/{application_id}/validate` — read-only формальная проверка без
  изменения заявки и без кредитного решения.

Для чужого ресурса рекомендуется отвечать 404, чтобы не подтверждать его существование. `401/403`
не повторяются с другими идентификаторами. `429` и `5xx` могут считаться временными только в рамках
ограниченного retry budget.

## Чеклист подключения

1. Реализовать маршруты и схемы, совместимые с Mock Backend.
2. Заменить статический сервисный токен на mTLS или workload identity.
3. Выпускать короткоживущий токен с audience AI Service → Main Backend.
4. Создать transactional outbox для `ai.chat.request` и inbox для `ai.chat.result`.
5. Добавить уникальность `request_id` и связь результата с пользователем и беседой.
6. Сохранять историю до публикации нового запроса и передавать только разрешённое окно.
7. Не включать документы, полные токены и персональные данные в логи.
8. Согласовать таймауты: HTTP меньше общего LLM timeout, retry — только для временных ошибок.
9. Прогнать сценарии доступа к чужой организации и повторной доставки.
10. Переключить `BACKEND_BASE_URL` и секреты через среду; код оркестратора не менять.

