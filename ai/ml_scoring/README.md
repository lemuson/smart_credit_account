# Синтетический датасет кредитных заявок

Изолированный ML-модуль генерирует 20 000 демонстрационных заявок по формулам из
`docs/dataset_design.md`. Он не импортируется AI Service и не меняет его runtime-контракты.

## Установка ML-зависимостей

Из корня репозитория:

```bash
uv sync --group dev --group ml
```

Pandas, NumPy, Matplotlib и PyYAML находятся в отдельной группе `ml`, а не в runtime-зависимостях
AI Service.

## Генерация

```bash
.venv/bin/python ml_scoring/scripts/generate_dataset.py
```

Команда создаёт train/validation/test размером 14 000/3 000/3 000 строк и metadata в
`ml_scoring/data/`. Перед сохранением выполняется hard validation. Конфигурация и seeds находятся
в `configs/generator_v1.yaml`.

## Анализ и отчёт

```bash
.venv/bin/python ml_scoring/scripts/analyze_dataset.py
```

Команда повторно читает CSV, проверяет split, выполняет EDA, fairness-аудит, monotonic tests и
пять дополнительных генераций для проверки устойчивости. Графики сохраняются в
`reports/figures/`, итоговый текст — в `docs/dataset_validation.md`.

## Тесты и линтер

```bash
.venv/bin/pytest ml_scoring/tests
.venv/bin/ruff check ml_scoring
```

## Обучение моделей

```bash
.venv/bin/python ml_scoring/scripts/train_models.py
```

Pipeline обучает Logistic Regression и ограниченный набор CatBoost, использует раздельные части
validation для model selection, обучения калибратора и выбора калибровки, после чего один раз
оценивает зафиксированные варианты на test. Конфигурация находится в
`configs/training_v1.yaml`, сравнение — в `reports/model_comparison.md`, Model Card — в
`docs/model_card.md`.

## Локальный inference с объяснением

```bash
.venv/bin/python ml_scoring/scripts/predict.py \
  --annual-revenue 5000000 \
  --credit-history good \
  --business-age-months 48 \
  --loan-amount 3000000 \
  --has-collateral true \
  --loan-term-months 24 \
  --age 40
```

Команда проверяет SHA-256 bundle, input schema и train-reference, строго валидирует анкету и
выводит JSON с демонстрационной ML-оценкой, шестью сгруппированными факторами и диагностикой
точного восстановления logit. Классификационный порог не используется как решение по заявке.

What-if с повторным вызовом модели:

```bash
.venv/bin/python ml_scoring/scripts/predict.py \
  --annual-revenue 5000000 \
  --credit-history average \
  --business-age-months 36 \
  --loan-amount 3000000 \
  --has-collateral false \
  --loan-term-months 24 \
  --what-if-loan-amount 1500000
```

Результат содержит исходную и альтернативную оценки и разницу в процентных пунктах. Это модельная
симуляция, а не причинная рекомендация. Значения вне области генератора завершаются статусом
`unsupported_range` и не получают процентную оценку. Joblib-файлы нельзя загружать из внешних или
недоверенных источников.

Reference для объяснений воспроизводится только из train:

```bash
.venv/bin/python ml_scoring/scripts/build_explanation_reference.py
```

Подробный контракт и формулы: `docs/inference_design.md`.

Возраст хранится для проверки допустимости и исследовательского fairness-аудита, но отсутствует в
ML feature allow-list и не используется в latent score. `approved` — результат синтетической
Bernoulli-симуляции, а не банковское решение.
