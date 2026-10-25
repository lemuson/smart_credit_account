# Интеграция сохранённого ML Scoring с Qwen

## Статус

На 25 октября 2026 года AI Service подготовлен к чтению сохранённой демонстрационной ML-оценки
через `get_scoring_result`. Реальный Scoring API в Main Backend пока не реализован.

Проверены одновременно код Backend и OpenAPI запущенного локального контейнера. Ни один из трёх
согласованных маршрутов в них отсутствует:

- `POST /api/v1/scoring/assessments`;
- `GET /api/v1/scoring/assessments/{assessment_id}`;
- `POST /api/v1/scoring/assessments/{assessment_id}/what-if`.

Поэтому client/tool и объяснение Qwen проверены на mock HTTP responses. Реальный scoring E2E не
засчитывается и остаётся заблокированным до реализации Main Backend API. Существующие реальные
маршруты профиля, продуктов и заявок не изменялись.

## Read-only tool

`get_scoring_result` зарегистрирован в существующем allow-list и использует общий `BackendClient`.
Новый HTTP-клиент, доступ к БД и загрузка ML-модели не добавлялись.

Строгая схема аргументов:

```json
{
  "assessment_id": "UUID, обязательно",
  "what_if_id": "UUID или null, необязательно"
}
```

`additionalProperties=false`: `user_id`, `organization_id`, токены и любые другие аргументы
отклоняются до HTTP-вызова. Tool выполняет только:

```text
GET /api/v1/scoring/assessments/{assessment_id}
GET /api/v1/scoring/assessments/{assessment_id}?what_if_id={what_if_id}
```

Ответ сокращается до данных, необходимых для объяснения: ID и версии assessment/model/schema,
score, baseline, ровно шесть сохранённых факторов, обязательное предупреждение и выбранный What-if.
Из ответа исключаются `application_id`, feature snapshot, consistency diagnostics, bundle hash,
внутренние DB-поля и любые токены. Ответ с другим assessment/what-if ID, отсутствующим выбранным
What-if или не шестью факторами считается нарушением протокола.

## Авторизация и tenant isolation

BackendClient передаёт существующий доверенный контекст:

- `Authorization` из `ChatRequest.trusted_context.authorization`;
- настроенный `X-Service-Token`;
- `X-User-ID`, `X-Organization-ID` и `X-Request-ID` только из проверенного message envelope.

Main Backend обязан повторно проверить service identity, delegated user, роль и принадлежность
assessment организации. Чужой и отсутствующий ресурс должны одинаково давать `404`.

Текущий Main Backend создаёт для AI tools отдельный JWT с audience `smart-credit-ai-tools` и TTL
10 минут. Он публикуется в durable RabbitMQ message по действующему контракту 1.0. Интеграция не
расширяет срок жизни или объём credentials и не меняет механизм делегации. Для production всё ещё
нужна согласованная политика минимального TTL, redelivery после истечения и управления секретами.

## Контекст и маршрутизация

`ChatRequest 1.0` не содержит `assessment_id` или `what_if_id` и остаётся неизменным. Совместимый
MVP-вариант требует, чтобы пользователь явно указал UUID assessment; для What-if указываются два
UUID в порядке assessment, затем What-if. Planner вызывает tool только при наличии UUID и явного
scoring intent. Без UUID Qwen должна запросить идентификатор, а не придумывать его.

Для UI-контекстного сценария рекомендуется согласованная RabbitMQ schema 1.1 с необязательными
`assessment_id` и `what_if_id`, сформированными Main Backend. Такое изменение должно одновременно
поддерживаться producer и consumer и в текущую реализацию не входит.

## Правила объяснения Qwen

Системный prompt и orchestrator задают следующие границы:

- score, `display_percent`, `logit_contribution` и `delta_percentage_points` не пересчитываются и
  не округляются заново;
- Qwen не придумывает факторы, числа или What-if;
- logit contribution не называется процентными пунктами или причинным эффектом;
- только `delta_percentage_points` является разницей в процентных пунктах;
- оценка всегда называется демонстрационной, основанной на синтетических данных;
- оценка не является решением банка, гарантией одобрения или основанием обещать результат;
- Qwen не может изменить, повысить или сохранить новую оценку.

После tool call числовой guardrail сравнивает каждый числовой литерал ответа только с типизированными
числовыми полями сокращённого tool response. Числа из вопроса, UUID, timestamps и строковых версий
не считаются источником истины. Сравнение выполняется через `Decimal`: десятичная точка и запятая,
а также эквивалентные завершающие нули принимаются; другое округление, новый знак или новое значение
отклоняются. Это одинаково применяется к score, logit contribution и What-if delta.

При новом или изменённом числе Qwen получает одну попытку переписать ответ. При повторном нарушении
возвращается безопасное объяснение без чисел. Если Qwen пропустила оговорку о синтетических данных,
orchestrator добавляет сохранённый `limitations_warning` из Backend payload. Guardrail активируется
только после успешного `get_scoring_result`, поэтому обычные RAG-ответы с числами, например
«6 месяцев», не блокируются.

Это defense-in-depth, а не математическая верификация естественного языка: если ошибочное число
буквально совпадает с другим разрешённым числовым полем того же payload, проверка множества значений
не определит неверную семантическую привязку. Риск уменьшают минимальный view, строгий prompt,
отсутствие вычислений и безопасный fallback; для production можно перейти к шаблонному рендерингу
критических чисел или к структурированному ответу Qwen с последующей field-by-field валидацией.

## What-if и RAG

При `what_if_id` Backend должен вернуть конкретную сохранённую симуляцию в `selected_what_if`.
Tool проверяет соответствие обоих ID и наличие шести факторов в original/alternative. AI Service
не создаёт What-if, не изменяет заявку и не запускает inference.

RAG может объяснять общие понятия: кредитную историю, залог, выручку, срок, logit и смысл What-if.
Он не является источником score, факторов или конкретной сохранённой симуляции. Для
детерминированного scoring tool call retrieval не подмешивается, поэтому KB не может заменить или
изменить структурированный результат Backend.

## Ошибки

| Ситуация | Ошибка AI Service | Поведение ответа |
|---|---|---|
| `401/403` | `BACKEND_ACCESS_DENIED` | доступ не подтверждён, без данных оценки |
| `404` | `BACKEND_NOT_FOUND` | отсутствующий и чужой ресурс не различаются |
| `409` | `BACKEND_CONFLICT` | конфликт сохранённой версии/ресурса |
| timeout/connect/`5xx`, включая `503` | `DEPENDENCY_UNAVAILABLE` | временная недоступность, без фиктивных чисел |
| неверный response/ID/число факторов | `MODEL_PROTOCOL_ERROR` | payload не передаётся Qwen как валидный |
| неверный UUID/лишний аргумент | `TOOL_VALIDATION_ERROR` | HTTP-запрос не выполняется |

Сообщения ошибок не содержат токены, feature snapshots или полные финансовые данные.

## Проверки

Mock unit/contract-проверки покрывают:

- валидный assessment и минимизацию payload;
- валидный What-if;
- невалидный UUID и запрет identity-аргументов;
- `401`, `403`, `404`, `409`, `503` и timeout;
- чужой/отсутствующий What-if и несовпадающие ID;
- обязательные шесть факторов исходной оценки и обоих What-if snapshots;
- повтор Qwen при изменении score и отсутствие выдуманных чисел;
- обязательное предупреждение о синтетических данных;
- десятичную запятую, эквивалентные завершающие нули, запрет нового округления и смены знака logit;
- точную What-if delta в процентных пунктах и запрет округлённой delta;
- отсутствие ложного срабатывания numeric guard в обычном RAG-ответе;
- planner с явным UUID, отсутствие вызова без UUID и маршрутизацию всех 10 scoring eval.

В `evaluation/scoring_dataset.jsonl` находятся 10 требуемых scoring-сценариев. Они предназначены
для запуска после появления реальных assessment fixtures в Backend; текущий mock-test не считается
реальным E2E.

### Фактические результаты 25 октября 2026 года

- финальный полный AI Service + `ml_scoring` pytest: `123 passed, 4 skipped`;
- planner-набор, включая контракт всех 10 scoring eval-сценариев: `17 passed`;
- итоговый узкий scoring/orchestrator/planner/schema набор до dataset-contract: `45 passed`;
- Ruff lint для всего `ai/`: PASS;
- Ruff format для всех затронутых Stage 7 Python-файлов: PASS;
- mock `get_scoring_result`: PASS, включая `401/403/404/409/503`, timeout, What-if, шесть факторов,
  несовпадающие ID и удаление лишних вложенных/root полей;
- `ChatRequest 1.0`: AI schema не получила scoring-полей; cross-repository contract test PASS;
- expired delegated JWT и tenant isolation Backend: PASS; истёкший JWT получает отказ, обхода
  service/user authorization нет;
- retrieval: ожидаемый KB найден для всех 12 вопросов, где он обязателен (`12/12`);
- реальный RabbitMQ E2E: все 18 RAG-наборов завершились `completed`; сценарии 1–10 прошли до
  одновременной остановки локального Compose, сценарии 11–18 продолжены после запуска тех же
  persistent volumes. Разрыв был инфраструктурным (`api/db/rabbitmq` остановились вместе), а не
  ошибкой конкретного ответа;
- после обнаружения английского префикса в What-if и неверной расшифровки `annual_revenue` внесены
  guardrails и точечно повторены E2E: What-if отвечает по-русски, профиль говорит «годовая выручка»;
- реальные RabbitMQ E2E профиля и поиска продуктов: `completed`, данные получены из Main Backend,
  `sources=[]`, ответы явно демонстрационные;
- после E2E очереди `ai.chat.request`, `ai.chat.result`, `ai.chat.retry` и `ai.chat.dead` имеют
  `messages_ready=0` и `messages_unacknowledged=0`; API, DB, RabbitMQ, worker и bridge запущены;
- live OpenAPI повторно подтверждает отсутствие `/api/v1/scoring/*`; настоящий ML Scoring E2E не
  выполнялся и успешным не объявляется.

Четыре pytest-пропуска — существующие external-service tests, включаемые отдельными markers. Первый
запуск двух Backend-тестов дал `1 passed, 1 failed`: JWT-тест прошёл, а contract-тест не нашёл
соседний `/ai` внутри стандартного Backend image. После read-only mount исходной AI-схемы повторный
contract-тест прошёл (`1 passed, 1 warning`); warning относится к Starlette/httpx deprecation.

## Что требуется от backend-разработчика

1. Реализовать и включить три маршрута по согласованному OpenAPI.
2. Согласовать mapping заявки в шесть признаков, persistence и неизменяемость assessment/What-if.
3. Реализовать `scoring:read`, tenant isolation и одинаковый `404` для чужого/отсутствующего ID.
4. Возвращать ровно шесть факторов, сохранённые версии модели/schema и обязательный warning.
5. Подтвердить семантику `409`, Problem Details и поведение истёкшего delegated token при
   RabbitMQ redelivery.
6. Предоставить синтетические assessment/what-if fixtures для реального E2E.
7. Совместно решить, нужна ли schema 1.1 для контекстных ID; schema 1.0 односторонне не меняется.
