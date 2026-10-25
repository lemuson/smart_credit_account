# Интеграция ML Scoring

Реализованы три маршрута контракта `ai/ml_scoring/docs/backend_integration_openapi.yaml`:

- `POST /api/v1/scoring/assessments` — сохранение оценки версии заявки;
- `GET /api/v1/scoring/assessments/{assessment_id}` — чтение без inference;
- `POST /api/v1/scoring/assessments/{assessment_id}/what-if` — сохранение симуляции.

Оба POST требуют UUID в `Idempotency-Key`; replay возвращает 200, создание — 201.
Ключ общий для scoring-операций в пределах пользователя и организации. Изменение fingerprint даёт
409. UNIQUE в PostgreSQL и savepoint предотвращают сохранение двух результатов при гонке ключа.
Assessment, What-if, запись идемпотентности и AuditEvent сохраняются одной транзакцией.

## Mapping и права

Источником служит сохранённая `Application`, а не актуальный профиль:

| ML-признак | Поле заявки |
|---|---|
| annual_revenue | financials.annual_revenue: Decimal -> float на ML-границе |
| credit_history | financials.credit_history |
| business_age_months | полные календарные месяцы от company.registration_date до UTC-даты snapshot |
| loan_amount | amount: Decimal -> float на ML-границе |
| has_collateral | financials.has_collateral, только bool |
| loan_term_months | term_months |

Отсутствующие/невалидные данные дают 422 без подстановок. Сохраняются шесть признаков, SHA-256
канонического JSON, версия заявки, полный response и diagnostics ML. Версия заявки повторно
проверяется с PostgreSQL row lock после inference; конфликт даёт 409.

В текущем Backend организация — `Profile.id`, принадлежащий одному клиенту. Роли CLIENT разрешены
`scoring:read/write` только для его организации/заявок. BANK_OFFICER и ADMIN получают 403:
модель членства сотрудников в tenant отсутствует, глобальные права сотрудников на scoring не
вводились. Применяется серверная tenant-фильтрация, PostgreSQL RLS не добавлялся.

Delegated JWT AI Service допускает только GET assessment с существующими проверками workload token,
active user, организации, незавершённого ChatJob, request ID и TTL. Ни POST scoring, ни POST What-if
этому JWT не доступны. Произвольные identity-заголовки прав не предоставляют.
Чужие/отсутствующие assessment и What-if дают одинаковый 404.

GET сохраняет старые model/schema versions и `Cache-Control: private, no-store`.
`?what_if_id=UUID` возвращает соответствующую сохранённую симуляцию в `selected_what_if`.
What-if работает с копией snapshot, вызывает существующий `compare_applications` и проверяет
bundle hash, model version и explanation reference hash. Несовместимая версия даёт 409.
Поля/версия/статус заявки не меняются; в истории досье появляются события аудита scoring.

## Runtime и запуск

`ai/ml_scoring/pyproject.toml` упаковывает существующие исходники без изменения ML-логики.
Backend устанавливает локальный пакет через uv. Обучение в Backend отсутствует.
LocalInferenceService загружается один раз на lifespan и сам проверяет manifest и SHA-256.
Inference выполняется в sync FastAPI handler вне event loop, с четырьмя слотами CPU на процесс.
При занятости всех слотов возвращается 503 SCORING_BUSY.

Локально из `backend/`:

```sh
uv sync --frozen
SCORING_MODELS_DIR=/absolute/path/to/approved/models uv run uvicorn main:app
```

В каталоге должны находиться готовые `manifest.json`, `credit_scoring_model.joblib`,
`input_schema.json`, `explanation_reference.json` с согласованными хешами и sklearn version.
Произвольные пользовательские joblib не принимаются. Каталог доверенный, управляется deployment.
В Compose `SCORING_MODELS_DIR` — путь на хосте, монтируемый read-only в `/models` контейнера API.
По умолчанию это `ai/ml_scoring/models`. Для сборки используется дополнительный build context
`ml_scoring`; сборка: `docker compose --env-file backend/.env -f backend/compose.yaml build api tests`.

`GET /health/scoring` возвращает 503 при отсутствии/повреждении артефактов; основной `/health`
остаётся доступным для чтения сохранённых оценок. POST возвращает Problem Details
`application/problem+json` с кодом SCORING_UNAVAILABLE. Данные оценки не фабрикуются.

RabbitMQ schema 1.0, topology, AI Service и Frontend не менялись. Пользователь указывает UUID
assessment и What-if в сообщении; существующий planner вызывает get_scoring_result.
Делегированный JWT сохраняет прежний TTL 10 минут и ограничения текущего ChatJob.

## Проверки и фактическое состояние 25 октября 2026

- Backend SQLite pytest: 79 passed, 2 skipped.
- Backend PostgreSQL pytest в изолированных временных схемах: 79 passed, 2 skipped.
- Миграции: upgrade, alembic check, downgrade, re-upgrade проверены тестами.
- AI scoring tool/orchestrator/planner: 42 теста прошли.
- Ответы assessment/What-if/Problem проверяются JSON Schema из исходного OpenAPI.
- Ruff Backend: PASS; затронутые Python-файлы отформатированы.
- Unit-тест adapter использует явно обозначенный stub только для проверки persistence, replay,
  версий, гонки изменения заявки и диапазонных ошибок. Его числа не являются ML/E2E-результатами.
- `SCORING_E2E_MODELS_DIR=/path/to/models uv run pytest -m scoring_e2e` включает настоящий
  numerical round-trip через Backend и готовую модель; при отсутствии каталога тест пропускается.
- `uv run python -m examples.scoring_e2e` выполняет настоящий HTTP-сценарий с двумя синтетическими
  пользователями, заявкой, scoring, What-if и RabbitMQ/Qwen; не использует моки и не удаляет записи.

Готовые артефакты отсутствуют в рабочем дереве и не найдены локально. Пользователь подтвердил
продолжение интеграции с честным 503 до их появления. Настоящий HTTP-запуск создал заявку
`885a3764-3e47-43b1-b785-e853f182d9ab`, затем завершился на POST scoring с
`503 SCORING_UNAVAILABLE`. Реального score, What-if и объяснения Qwen для этой заявки нет.
Значения из документации ML и unit fixtures не выдаются за E2E-результат.

Два пропуска Backend: существующий тест с внешним RabbitMQ без TEST_RABBITMQ_URL и numerical
scoring E2E без готовых артефактов. Starlette выдаёт существующее предупреждение о deprecated
httpx TestClient. Автоматические тесты AI используют существующие mocks и не засчитываются как
реальный Qwen E2E. AI workers/Qwen для этого сценария не запускались.

После получения доверенного каталога артефактов нужно перезапустить API с указанным mount,
поднять существующий AI stack и повторить оба настоящих E2E. До этого полная цепочка с числовым
inference и Qwen остаётся непроверенной. Миграция локальной БД применена, API и PostgreSQL запущены;
Docker volumes и существующие данные не удалялись. Git-ветка main; коммиты не создавались.
