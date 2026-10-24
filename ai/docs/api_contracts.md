# HTTP контракты Mock Backend

Все данные синтетические. Интерактивная OpenAPI-схема доступна на `/docs`, JSON — на
`/openapi.json`. Заголовки локального демо:

```text
Authorization: Bearer demo-user-token
X-Service-Token: development-service-token
X-User-ID: 20000000-0000-0000-0000-000000000001
X-Organization-ID: 10000000-0000-0000-0000-000000000001
X-Request-ID: <request UUID>
```

## Профиль

`GET /api/v1/profile`

```json
{
  "user_id": "20000000-0000-0000-0000-000000000001",
  "organization_id": "10000000-0000-0000-0000-000000000001",
  "legal_form": "ИП",
  "industry": "розничная торговля",
  "business_age_months": 30,
  "annual_revenue": "7200000.00",
  "region": "Москва",
  "is_demo": true
}
```

## Подбор продуктов

`GET /api/v1/credit-products/search?purpose=покупка%20оборудования&amount=2000000&term_months=24`

Ответ: `{"items": [...]}`. Каждый элемент содержит `product_id`, имя, диапазоны суммы и срока,
демонстрационную ставку, `match_reasons` и `is_demo`. Подбор полностью детерминирован в backend;
LLM только объясняет результат.

## Детали и документы

- `GET /api/v1/credit-products/{product_id}` возвращает полную карточку.
- `GET /api/v1/credit-products/{product_id}/required-documents` возвращает
  `{"items": [{"code": "...", "name": "...", "required": true}]}`.

Неизвестный продукт возвращает 404.

## Статус и валидация заявки

- `GET /api/v1/applications/{application_id}/status` возвращает `status`, `status_label` и
  `next_action`.
- `POST /api/v1/applications/{application_id}/validate` не изменяет данные и возвращает `valid`,
  массив `issues`, `decision: null` и `is_demo: true`.

Демонстрационная заявка пользователя 1:
`30000000-0000-0000-0000-000000000001`. Заявка организации 2 скрывается от пользователя 1
ответом 404.

## Ошибки

```json
{"detail": "Application not found"}
```

- 400 — отсутствует доверенный контекст или параметры невалидны;
- 401 — пользовательский или сервисный credential не принят;
- 403 — идентичность не соответствует организации;
- 404 — ресурс отсутствует или недоступен этой организации;
- 422 — ошибка валидации FastAPI/Pydantic;
- 5xx — временная серверная ошибка.

