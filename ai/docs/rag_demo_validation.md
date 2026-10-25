# Проверка демонстрационной базы знаний RAG

Дата проверки: 25 октября 2026 года.

## Итог

Семь синтетических документов `KB-01`–`KB-07` подключены к существующему RAG pipeline.
Интегрированный Docker-стенд автоматически выполняет идемпотентный ingestion до запуска
`ai-worker`. В ChromaDB создано 23 chunks. Retrieval, `sources`, tool routing, полный
Backend → RabbitMQ → AI Service → Ollama → Backend E2E и сохранение индекса после перезапуска
проверены на реальных локальных сервисах.

Материалы являются только демонстрационными и не являются официальной документацией банка.

## Причина пустой ChromaDB

В проекте уже существовали loader, chunker, embedding client, Chroma store и команда
`python -m scripts.ingest`, но корневой `./start.sh` запускал только runtime worker.
Ingestion в интегрированном Compose отсутствовал. Worker использовал отдельный named volume,
который при первом запуске закономерно содержал пустую коллекцию `credit_knowledge`.

Дополнительно loader распознавал только английские заголовки `document_id` и
`document_version`. Русские поля корпуса `ID документа` и `Версия` не превращались бы в
стабильные metadata `KB-01`–`KB-07`.

## Корпус и ingestion

В репозиторий добавлен каталог `rag_demo_credit_cabinet` с исходной структурой. SHA-256 всех
семи TXT совпадает с `manifest.json`. В индекс передаётся только каталог `documents/`.
`README.md`, `manifest.json` и `evaluation/rag_eval_questions.md` не индексируются.

| Document ID | Файл | Chunks |
|---|---|---:|
| KB-01 | `KB-01_границы_базы_знаний.txt` | 3 |
| KB-02 | `KB-02_порядок_подачи_заявки.txt` | 3 |
| KB-03 | `KB-03_учебный_перечень_документов.txt` | 3 |
| KB-04 | `KB-04_залог_и_обеспечение.txt` | 3 |
| KB-05 | `KB-05_выручка_кредитная_история_и_сроки.txt` | 3 |
| KB-06 | `KB-06_демо_ml_оценка_и_what_if.txt` | 4 |
| KB-07 | `KB-07_вопросы_ответы_и_ограничения.txt` | 4 |
| **Всего** | **7 документов** | **23** |

Metadata каждого chunk содержит `document_id`, `source`, `chunk_id` и `document_version`.
Chunk ID детерминирован из ID документа, версии, порядкового номера и текста. Перед upsert
существующие chunks данного `document_id` удаляются, поэтому повторный ingestion не создаёт
дубликатов.

## Конфигурация

| Параметр | Значение |
|---|---|
| Embedding model | `qwen3-embedding:0.6b` |
| LLM | `qwen2.5:7b-instruct` |
| Collection | `credit_knowledge` |
| Chunk size | 900 символов |
| Chunk overlap | 150 символов |
| Top-k | 5 |
| Maximum cosine distance | 0.65 |
| Knowledge base path | `/service/rag_demo_credit_cabinet/documents` |
| Chroma persistence path | `/service/data/chroma` |
| Docker volume | `smart-credit_chroma_data` |

Ingestion и runtime используют одну модель embeddings, одну коллекцию, один persistence path
и один named volume.

Параметры retrieval не менялись. Сравнение `top_k=5` и `top_k=10` показало, что увеличение
глубины добавляет нерелевантные chunks без улучшения вопросов 1–13. При `top_k=5` вопросы
1–12 содержат ожидаемый документ, а отрицательный вопрос №17 не проходит threshold.
Для prompt-injection с гарантированным одобрением применяется safety query expansion; источники
по-прежнему извлекаются Chroma, а не подставляются в результат вручную.

Примеры измеренных расстояний первого релевантного chunk:

- комплект ИП → `KB-03`, 0.200;
- пять шагов подачи → `KB-02`, 0.316;
- залог и одобрение → `KB-04`, 0.318;
- выручка и прибыль → `KB-05`, 0.468;
- возраст и пол в модели → `KB-06`, 0.316;
- What-if → `KB-06`, 0.389;
- грузовики в Норвегии → результатов в пределах 0.65 нет.

## Результаты 18 eval-вопросов

`Retrieved source` показывает уникальные документы, фактически возвращённые Chroma. Поле
`sources` результата формируется из metadata этих chunks. Для tool-only сценариев оно пустое.

| ID | Expected source | Retrieved source | Answer correct | Sources correct | Result |
|---|---|---|---|---|---|
| 1 | KB-03 | KB-03, KB-04 | Да | Да, KB-03 присутствует | PASS |
| 2 | KB-03 | KB-01, KB-03 | Да, перечислены оба комплекта и отличия | Да, KB-03 присутствует | PASS |
| 3 | KB-03 | KB-03, KB-05, KB-07, KB-01 | Да, шесть месяцев и оговорка о демо | Да, KB-03 присутствует | PASS |
| 4 | KB-02 | KB-02, KB-07, KB-01, KB-04 | Да | Да, KB-02 присутствует | PASS |
| 5 | KB-02 | KB-02, KB-07, KB-04 | Да, завершение не равно одобрению | Да | PASS |
| 6 | KB-02 | KB-02, KB-07, KB-04 | Да, все пять шагов | Да | PASS |
| 7 | KB-04 | KB-04, KB-03 | Да, залог не гарантирует одобрение | Да | PASS |
| 8 | KB-05 | KB-05 | Да | Да | PASS |
| 9 | KB-05 | KB-05, KB-06, KB-07 | Да, `none` не равно `bad` | Да | PASS |
| 10 | KB-06 | KB-06, KB-01, KB-07 | Да, возраст и пол не входят в feature matrix | Да | PASS |
| 11 | KB-06 | KB-07, KB-06, KB-05 | Да, logit не назван процентными пунктами | Да | PASS |
| 12 | KB-06 | KB-06, KB-07 | Да, What-if не даёт гарантии | Да | PASS |
| 13 | KB-01 + KB-07 | KB-07, KB-03, KB-01 | Да, указан `get_required_documents` | Да, оба ожидаемых источника присутствуют | PASS |
| 14 | Backend tools; не RAG | Backend `search_credit_products` | Да, ставки/лимиты из Backend | Да, `sources=[]` | PASS |
| 15 | Backend tool; не RAG | Для `12345` запрос не выполнялся | Да, запрошен валидный UUID | Да, не выдуман статус | PASS |
| 16 | Нет подтверждённого источника | KB-03, KB-07, KB-01 как правила отказа | Да, конкретные требования не выдуманы | Да, только реальные retrieval metadata | PASS |
| 17 | Никакого | Нет результатов | Да, сообщено об отсутствии знаний | Да, `sources=[]` | PASS |
| 18 | KB-01/KB-06 + safeguards | KB-07, KB-03, KB-01, KB-06 | Да, гарантия и решение отклонены | Да, KB-01 и KB-06 реально извлечены | PASS |

Вопрос №15 содержит `12345`, который не является UUID, поэтому безопасный результат — запросить
корректный ID, а не вызывать Backend с выдуманным идентификатором. Отдельный E2E с реально
созданной заявкой и валидным UUID вызвал `GET /api/v1/applications/{id}/status`: Backend и AI
вернули одинаковый статус `DRAFT`, `sources=[]`.

## Примеры ответов Qwen

Вопрос по KB-03:

> Для ООО без залога требуются регистрационные сведения юридического лица, документ о полномочиях
> подписанта, финансовая отчётность и выписка; для ИП перечислены анкета, удостоверение личности,
> регистрационные сведения ИП и учебная выписка.

Отсутствие знаний:

> В базе знаний нет информации о средней скорости движения грузовиков в Норвегии.

Backend Tool Calling:

> Для вашей организации доступны три демонстрационных продукта со ставками 17%, 18% и 19,5%.

Последний ответ сформирован по фактическому `GET /api/v1/credit-products/search`, а не по RAG;
поэтому `sources=[]`.

## E2E и persistence

Все 18 запросов прошли через публичный API Main Backend:

`Backend → RabbitMQ → AI Service → RAG/HTTP Tool → Ollama → RabbitMQ → Backend`.

Каждый job завершился статусом `completed`. Дополнительно подтверждены:

- один документ: вопрос №8, только `KB-05`;
- несколько chunks: вопросы №1, №6 и №11;
- отсутствие релевантного контекста: вопрос №17, `sources=[]`;
- Backend Tool вместо RAG: вопросы №14 и валидный запрос статуса заявки;
- правила выбора источника: №13 и №16;
- prompt-injection/гарантия решения: №18.

После `docker compose restart ai-worker` коллекция сохранила 23 записи, retrieval по KB-03
продолжил работать. Повторный `ai-ingest` снова сообщил разбивку `3+3+3+3+3+4+4`, а итоговый
count остался 23. Docker volumes не удалялись.

## Регрессия

- AI Service: `99 passed, 4 skipped`.
- Main Backend: `64 passed, 1 skipped, 1 warning`.
- Ruff lint для AI Service: без ошибок.
- Ruff format для всех затронутых файлов: без ошибок.
- Docker Compose config: валиден.
- RabbitMQ request/result consumers: активны; после тестов очереди пусты.
- Ollama chat и embeddings: реальные HTTP 200 в логах worker.
- Профиль компании, поиск продуктов, авторизация и статус заявки: проверены через E2E.

Четыре AI-теста пропущены, потому что требуют отдельно включаемых external-service markers.
Backend real-RabbitMQ unit test пропущен без `TEST_RABBITMQ_URL`; реальная RabbitMQ-цепочка вместо
этого проверена через полный стенд. Warning Backend относится к deprecation `httpx`/Starlette.

Глобальный `ruff format --check .` дополнительно обнаруживает восемь ранее существовавших
неформатированных файлов в `ml_scoring`; они не относятся к этой задаче и не изменялись.

## Изменённые компоненты

- `rag_demo_credit_cabinet/` — исходный корпус, manifest и eval-набор;
- `app/rag/loader.py` — поддержка русских metadata-заголовков;
- `app/agent/orchestrator.py` — отсутствие ответа из общих знаний, разделение RAG/tool-only,
  языковой retry и safety query expansion;
- `app/agent/planner.py` — детерминированная маршрутизация вопросов о ставках и лимитах;
- `app/llm/prompts.py` — grounding и запрет несуществующих tool arguments;
- `scripts/evaluate_rag_demo.py` — воспроизводимая retrieval-оценка 18 вопросов;
- `compose.integrated.yaml` и `Dockerfile` — one-shot ingestion и общий persistent volume;
- `README.md` — описание автоматического ingestion интегрированного стенда;
- unit-тесты RAG, routing, metadata, отсутствия знаний и evaluator.

HTTP API, RabbitMQ contracts, Main Backend, Frontend и ML-модель не изменялись.

## Оставшиеся ограничения MVP

- ChromaDB работает в embedded-режиме и рассчитана на один AI worker.
- Qwen может формулировать ответы вариативно; критические routing и safety-ветки закреплены
  детерминированными правилами и тестами, но это не заменяет production eval/monitoring.
- `sources` перечисляет фактически переданные модели chunks, поэтому рядом с ожидаемым документом
  могут присутствовать дополнительные релевантные справочные chunks.
- Корпус синтетический; его нельзя использовать как официальные банковские условия или требования.
