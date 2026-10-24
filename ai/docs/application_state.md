# Демонстрационные состояния кредитной заявки

AI Service только читает и объясняет состояние. Переходы выполняет Main Backend после проверки прав
и бизнес-правил.

```mermaid
stateDiagram-v2
  [*] --> draft
  draft --> ready_to_submit: формальная проверка пройдена
  ready_to_submit --> submitted: пользователь подтвердил отправку
  submitted --> under_review: заявка принята в обработку
  under_review --> needs_information: нужны сведения
  needs_information --> under_review: сведения предоставлены
  under_review --> approved: решение уполномоченного процесса
  under_review --> rejected: решение уполномоченного процесса
  approved --> [*]
  rejected --> [*]
```

Демонстрационная формальная валидация проверяет только заполненность и комплектность. Она не
является скорингом и не переводит заявку в `approved` или `rejected`.

