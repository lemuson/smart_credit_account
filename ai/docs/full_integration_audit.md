# Комплексный аудит интеграции AI Service, Main Backend и ML Scoring

Дата проверки: 25 октября 2026 года.

## Итог

Существующая цепочка `Frontend -> Main Backend -> RabbitMQ -> AI Service -> Qwen/RAG/HTTP Tools`
работает на локальном интегрированном стенде. Фактически подтверждены авторизованный вход через UI,
создание и polling AI job, сохранение результата в Backend, получение профиля, поиск кредитных
продуктов, чтение статуса заявки и RAG-ответы.

Полная интеграция ML Scoring не готова: в фактическом коде, live OpenAPI и live HTTP Main Backend
нет трёх маршрутов `/api/v1/scoring/*`. Локальный Logistic Regression inference и What-if работают,
а read-only AI tool `get_scoring_result` проходит mock-тесты, но связать эти части настоящим E2E
сейчас невозможно. Наличие проектного OpenAPI не считается реализацией.

Во время свежего RAG E2E выявлена одна настоящая ошибка качества: вопрос про документы ИП по
демонстрационному чек-листу получил релевантный `KB-03`, но Qwen перечислила только три документа
из четырёх и пропустила анкету. Кроме того, эта формулировка ошибочно вызвала
`search_credit_products`, хотя ответ должен был быть RAG-only. Код в рамках аудита не исправлялся.

## Состояние репозитория и ограничения аудита

- Ветка: `main`, совпадает с `origin/main` по отслеживаемой истории.
- Незакоммиченные изменения этапов 6 и 7 сохранены без перезаписи.
- Main Backend, Frontend, ML-модель, RabbitMQ topology и публичные контракты не изменялись.
- Docker volumes и пользовательские данные не удалялись; `docker compose down -v` не выполнялся.
- Git-коммит не создавался.
- Единственное изменение этого аудита в рабочем дереве — данный отчёт.
- Для сценария статуса создан один локальный демонстрационный черновик заявки со статусом `DRAFT`.
  Это изолированный локальный демо-контур, не внешний или production-стенд.
- E2E добавили локальные тестовые диалоги и AI jobs в существующую демо-БД.

## Состояние стенда

| Компонент | Фактическое состояние |
|---|---|
| Main Backend API | `Up`, healthcheck `healthy`, live OpenAPI доступен |
| Frontend | `Up`, healthcheck `healthy`, страница и чат открываются в браузере |
| PostgreSQL | `Up`, healthcheck `healthy` |
| RabbitMQ | `Up`, healthcheck `healthy` |
| Backend AI bridge | `Up` |
| AI worker | `Up` |
| AI ingest | Завершён с кодом `0` |
| Ollama | Из AI worker доступны `qwen2.5:7b-instruct` и `qwen3-embedding:0.6b` |
| ChromaDB | Persistent collection `credit_knowledge`: 23 чанка из `KB-01`–`KB-07` |

После E2E очереди `ai.chat.request`, `ai.chat.result`, `ai.chat.retry` и `ai.chat.dead` имели
`messages_ready=0` и `messages_unacknowledged=0`. У request/result очередей было по одному активному
consumer. Это подтверждает отсутствие зависших сообщений после проверки, но само по себе не
является доказательством exactly-once доставки; идемпотентность дополнительно покрыта Backend-тестами.

## Матрица сценариев

| Сценарий | Состояние | Реальный E2E | Причина проблемы |
|---|---|---:|---|
| Frontend: загрузка кабинета | Работает | Да | — |
| Frontend: вход демо-клиента | Работает | Да | — |
| Frontend: отправка вопроса и отображение ответа | Работает | Да | — |
| A. Профиль компании | Работает | Да | `GET /api/v1/profile` вернул `200`, job завершён и ответ показан в UI |
| B. Кредитные продукты | Работает | Да | Получены три продукта из `GET /api/v1/credit-products/search`, не выдуманный каталог |
| C. RAG: чек-лист ИП без залога | Частично | Да | `KB-03` найден, но Qwen пропустила анкету и перечислила 3 из 4 документов; ошибочно вызван product search |
| D. Статус разрешённой заявки | Работает | Да | Создан локальный демо-черновик; Backend и AI вернули один и тот же UUID и `DRAFT` |
| Неизвестный продукт банка X | Работает с замечанием | Да | Не выдуман список документов, но ответ раскрывает внутренние имена tools и предлагает лишние технические шаги |
| Нерелевантный вопрос вне KB | Работает | Да | Корректно сообщено об отсутствии сведений, `sources=[]` |
| Prompt injection с требованием гарантии | Работает | Да | Гарантия/решение банка не выданы; использованы защитные KB-источники |
| RabbitMQ request/result round trip | Работает | Да | Все свежие API/UI jobs завершились, результаты доступны через Backend polling |
| Локальный Logistic Regression inference | Работает | Нет, локальный компонент | Модель не подключена к Main Backend |
| Локальный What-if | Работает | Нет, локальный компонент | Пересчёт работает, но нет Backend persistence/API |
| `get_scoring_result` | Работает на mocks | Нет | Live GET scoring endpoint отсутствует |
| Создание assessment | Не реализовано | Нет | Live `POST /api/v1/scoring/assessments` возвращает `404` |
| Получение assessment | Не реализовано | Нет | Live `GET /api/v1/scoring/assessments/{id}` возвращает `404` |
| Создание What-if | Не реализовано | Нет | Live `POST /api/v1/scoring/assessments/{id}/what-if` возвращает `404` |
| Пользовательский путь анкета -> ML -> объяснение | Не интегрирован | Нет | Нет Backend adapter, persistence, scoring API и scoring UI |

## Реальные AI/RabbitMQ E2E

Свежим запуском выполнены семь API-сценариев через Main Backend и RabbitMQ и один дополнительный
сценарий через браузерный UI. Во всех случаях Backend job перешёл в `completed`.

### Профиль

AI worker фактически вызвал `GET /api/v1/profile` и получил `200`. Ответ содержал данные демо-профиля:
ООО «Демо Бизнес», 81 месяц работы, годовую выручку 24 000 000 рублей, месячные расходы 500 000
рублей, хорошую кредитную историю, отсутствие просрочек и залога. Те же данные отобразились в UI.

Замечание: свежие профильные ответы не всегда явно называли сам профиль демонстрационным, хотя UI
и весь стенд маркированы как учебные. Это не подмена данных, но оговорку стоит сделать
детерминированной для каждого tool-response с `is_demo=true`.

### Кредитные продукты

AI worker фактически вызвал `GET /api/v1/credit-products/search` и получил `200`. Ответ перечислил
три записи текущего Backend: «Демо: оборудование», «Демо: развитие бизнеса» и
«Демо: оборотный капитал» с их суммами, сроками и ставками. `sources=[]`, поскольку источником был
Backend tool, а не RAG. Ответ явно назвал продукты демонстрационными.

### RAG

В ChromaDB находятся семь файлов и 23 чанка:

| Документ | Чанки |
|---|---:|
| `KB-01` | 3 |
| `KB-02` | 3 |
| `KB-03` | 3 |
| `KB-04` | 3 |
| `KB-05` | 3 |
| `KB-06` | 4 |
| `KB-07` | 4 |

Retrieval eval обработал все 18 вопросов. Для обязательных вопросов 1–12 ожидаемый документ был
среди результатов во всех случаях (`12/12`). Вопрос 13 вернул оба ожидаемых `KB-01` и `KB-07`,
вопрос 17 корректно вернул пустой retrieval. Сырой retrieval вопроса 18 не содержал `KB-01/KB-06`,
но live orchestrator применил safety-expansion, и реальный ответ использовал `KB-01`, `KB-06` и не
дал гарантии одобрения.

Для обязательного сценария C retrieval был корректным: в `sources` присутствует `KB-03`. Ошибка
возникла после retrieval: ответ назвал удостоверение личности, регистрацию ИП и выписку за шесть
месяцев, но пропустил анкету. По логам в этом же запросе был лишний вызов
`GET /api/v1/credit-products/search`. Рекомендация для AI Service: расширить RAG-only распознавание
на формулировки «демонстрационный/учебный чек-лист» и добавить eval/assertion на полноту четырёх
пунктов, не переписывая Backend contract.

### Статус заявки

До проверки у демо-пользователя не было разрешённой заявки. В локальной демо-БД создан отдельный
черновик. AI worker вызвал `GET /api/v1/applications/{application_id}/status`, получил `200` и вернул
тот же UUID и `DRAFT`. Ответ содержал демо-оговорку, `sources=[]`. Чужой UUID не использовался.

## ML Scoring

### Что подтверждено локально

Манифест выбирает `synthetic-credit-logreg`, модель `1.0`, schema `1.0`, family
`logistic_regression`. SHA-256 основного bundle фактически совпал с манифестом:
`0c393f9b54d4b50d28a9c01d3d4f1343aa99af55edf044c8e11192e846702fe3`.
Также совпали SHA-256 остальных перечисленных artifacts и explanation reference.

Свежие расчёты:

| Входной пример | Результат |
|---|---|
| Выручка 5 000 000, history `good`, бизнес 48 мес., сумма 3 000 000, залог, срок 24 | score `0.7257224270636591`, display `72.57`, ровно 6 факторов |
| Выручка 350 000, history `none`, бизнес 3 мес., сумма 250 000, без залога, срок 6 | score `0.09971556709519051`, display `9.97`, ровно 6 факторов |
| What-if: сумма 3 000 000 -> 1 500 000 | `41.45` -> `61.1`, delta `19.6484` п.п., исходный snapshot сохранён отдельно |

Во всех ответах указано, что оценка демонстрационная, обучена на синтетических данных и не является
банковским решением или гарантией. Тесты проверяют детерминизм, границы, tampered artifact,
serialization, ровно шесть факторов и повторный inference What-if.

### Чего нет в Main Backend

Поиск по фактическому Backend-коду не нашёл scoring router, handler, schema, service, repository или
migration. Live OpenAPI также не содержит scoring paths. Прямые запросы ко всем трём проектным
маршрутам вернули `404`. Во Frontend нет assessment/What-if API calls или интерфейса scoring.

Следовательно, не подтверждены и не могут быть проверены в live-системе:

- mapping заявки в шесть ML-признаков;
- вызов Logistic Regression из Main Backend;
- immutable persistence assessment и What-if;
- idempotency POST и отсутствие повторного inference при GET;
- tenant isolation конкретного assessment;
- live `scoring:read` delegated authorization;
- получение реального `assessment_id`/`what_if_id` через UI;
- объяснение Qwen сохранённого live assessment.

## `get_scoring_result` и защита чисел

При `BACKEND_CONTRACT=mock` и тестовом service token узкий набор scoring/orchestrator/planner/schema
завершился как `46 passed`. Он подтверждает:

- trusted identity и запрет identity-аргументов от LLM;
- `401`, `403`, `404`, `409`, `503` и timeout;
- строгий UUID и соответствие assessment/What-if IDs;
- ровно шесть ожидаемых факторов;
- удаление `application_id`, consistency, bundle hash и лишних root/nested полей до Qwen;
- сохранение score, logit contributions и What-if delta без пересчёта;
- десятичную точку/запятую и эквивалентные завершающие нули;
- запрет нового округления, смены знака logit и изменённой delta в процентных пунктах;
- повтор генерации один раз, затем безопасный fallback без неподтверждённых чисел;
- отсутствие ложного срабатывания numeric guard в обычном RAG-ответе с числами;
- обязательную оговорку о синтетических данных;
- совместимость с неизменённым `ChatRequest 1.0`.

Ограничение guardrail остаётся архитектурным: он сравнивает множество разрешённых числовых значений.
Если неверное утверждение использует число, которое уже законно присутствует в другом поле того же
payload, семантическую перестановку он не обнаружит. Для production-критичных чисел предпочтителен
структурированный ответ Qwen с field-by-field validation либо шаблонный renderer.

## Безопасность и надёжность

- Backend-тесты фактически подтвердили tenant isolation для существующих application tools,
  отклонение истёкшего delegated JWT и невозможность использовать delegation после завершения job.
- Тесты подтвердили `401` без пользовательской авторизации, `401` при неверной service identity,
  `403` при подмене organization и `404` для чужого/отсутствующего application ID.
- TTL delegated JWT формируется Backend и ограничен 10 минутами; обход авторизации не применялся.
- Scoring-specific tenant isolation нельзя считать проверенным: scoring resources в Backend не
  существуют. Mock-проверка не заменяет live ACL.
- Повтор одного `request_id` не создаёт второй ответ: это покрыто transactional inbox/idempotency
  Backend-тестами. После live E2E очереди пусты.
- GET scoring без повторного inference и неизменность persisted What-if нельзя проверить до
  реализации Backend. Локальный `ml_scoring` тест подтверждает, что What-if пересчитывает оба
  snapshot и не подменяет исходный результат.
- В просмотренных свежих логах токены и секреты не обнаружены. HTTP-клиент логирует method/path/status,
  но не Authorization headers. Реальные значения секретов в отчёт не включены.

## Результаты проверок

| Проверка | Результат | Комментарий |
|---|---:|---|
| AI Service + ML pytest | `123 passed, 4 skipped` | Пропущены opt-in external-service tests; их основные интеграции проверены отдельными live E2E |
| Scoring/mock/numeric/planner/schema | `46 passed` | Запуск с `BACKEND_CONTRACT=mock` и тестовым service token |
| Main Backend pytest | `64 passed, 1 skipped` | Skip — отдельный тест с изолированным RabbitMQ; live RabbitMQ проверен текущим стендом |
| Frontend unit tests | `8 passed` | — |
| Frontend production build | PASS | 1564 modules transformed |
| Ruff lint всего `ai/` | PASS | `All checks passed` |
| Ruff format изменённых Stage 6–7 файлов | PASS | 15 файлов уже отформатированы |
| Ruff format всего `ai/` | Не чист | 8 существующих ML-файлов требуют форматирования; в аудите не изменялись |
| `git diff --check` | PASS | — |
| RAG retrieval eval | 18/18 выполнены | Обязательные expected sources 1–12: `12/12` |
| Свежие RabbitMQ API E2E | 7 jobs `completed` | A–D и edge cases 16–18 |
| Свежий UI E2E | `completed` | Вход, отправка профильного вопроса, отображение ответа |
| Live scoring HTTP | FAIL / отсутствует | Все три проектных endpoint возвращают `404` |

Четыре AI integration-теста пропущены штатным условием `RUN_EXTERNAL_INTEGRATION != 1`: наличие
Ollama-моделей, Ollama embedding/RAG, real Ollama orchestrator и отдельный RabbitMQ round trip.
Это не скрытые ошибки: текущий Compose отдельно подтвердил модели, Chroma retrieval, orchestrator,
RabbitMQ request/result и HTTP tools. Backend skip аналогично требует отдельный изолированный broker,
чтобы не вмешиваться в рабочие очереди стенда.

## Задачи для исправления

### AI Service

1. Исправить маршрутизацию формулировки «согласно демонстрационному/учебному чек-листу»: это RAG-only,
   без `search_credit_products`.
2. Добавить E2E/assertion, что ответ по `KB-03` перечисляет все четыре пункта, включая анкету.
3. Сделать демо-оговорку детерминированной для каждого ответа на tool payload с `is_demo=true`.
4. По возможности скрыть внутренние имена tools от пользовательских ответов по неизвестным продуктам.
5. После появления Backend fixtures повторить 10 scoring eval-сценариев уже как настоящий E2E.

### Main Backend

1. Реализовать три маршрута из согласованного OpenAPI и подключить router к live app.
2. Реализовать adapter заявки в ровно шесть признаков и вызвать существующий
   `LocalInferenceService`, не перенося ML-вычисления в AI Service.
3. Добавить immutable assessment/What-if persistence, migration, audit trail и idempotency POST.
4. Зафиксировать application version и feature snapshot hash; повторно проверять version перед
   сохранением результата.
5. Реализовать `scoring:read`/`scoring:write`, service identity, delegated JWT, tenant isolation и
   одинаковый `404` для чужого и отсутствующего assessment.
6. GET должен читать сохранённый payload без inference и возвращать ровно шесть факторов,
   сохранённые model/schema versions и обязательный warning.
7. What-if должен делать полный inference по копии snapshot, не меняя заявку и исходный assessment.
8. Добавить Problem Details для `401/403/404/409/422/503`, тесты timeout/model integrity и fixtures
   с настоящими `assessment_id`/`what_if_id` для E2E.
9. Только после Backend API добавить/согласовать Frontend UI оценки и What-if отдельной задачей.

## Критерии полного пользовательского E2E

Полный сценарий можно объявить успешным только после того, как Frontend создаёт assessment для
разрешённой версии заявки, Backend формирует шесть признаков и вызывает проверенный bundle,
сохраняет immutable результат, GET возвращает его без inference, What-if создаёт отдельный snapshot,
а AI-чат по реальному UUID через delegated authorization вызывает `get_scoring_result`. Числа ответа
Qwen должны совпасть с persisted payload, чужой tenant и истёкший JWT должны получить отказ, а
исходная заявка и assessment — остаться неизменными.

На текущий момент AI-часть готова к подключению Backend на уровне схем, mock tool, фильтрации данных,
числовых guardrails и обработки ошибок. Весь продукт к ML Scoring E2E не готов, пока Backend не
реализует и не сохранит scoring resources.
