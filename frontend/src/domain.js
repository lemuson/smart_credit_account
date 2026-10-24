export const purposes = {
  working_capital: "Пополнение оборотных средств",
  equipment: "Покупка оборудования",
  expansion: "Развитие бизнеса",
  refinancing: "Рефинансирование",
};
export const statuses = {
  DRAFT: "Черновик",
  SUBMITTED: "Принята",
  PRIMARY_REVIEW: "На проверке",
  NEEDS_CLARIFICATION: "Нужно уточнение",
  AUTOMATIC_ANALYSIS: "На рассмотрении",
  OFFER_READY: "Одобрена",
  OFFER_ACCEPTED: "Предложение принято",
  SIGNING: "Ожидает подписания",
  DISBURSED: "Кредит оформлен",
  REJECTED: "Отказ",
  OFFER_DECLINED: "Предложение отклонено",
};
export const documentKinds = {
  registration: "Регистрационные документы",
  financial_statements: "Финансовая отчётность",
  bank_statement: "Выписка по счёту",
  collateral: "Документы на залог",
};
export const money = (value) =>
  new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(Number(value || 0));
export const date = (value) =>
  new Date(value).toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
export function payment(amount, rate, term) {
  const r = Number(rate) / 1200;
  return r
    ? (Number(amount) * r) / (1 - (1 + r) ** -Number(term))
    : Number(amount) / Number(term);
}
export function matches(product, purpose, amount, term) {
  return (
    product.active &&
    product.purposes.includes(purpose) &&
    Number(amount) >= Number(product.min_amount) &&
    Number(amount) <= Number(product.max_amount) &&
    Number(term) >= product.min_term_months &&
    Number(term) <= product.max_term_months
  );
}
export const emptyCompany = () => ({
  name: "",
  inn: "",
  registration_date: "",
  address: "",
  industry: "",
});
export const emptyFinancials = () => ({
  annual_revenue: "",
  monthly_expenses: "0",
  monthly_debt_payments: "0",
  outstanding_debt: "0",
  credit_history: "none",
  overdue_days: 0,
  has_collateral: false,
});

export const decisionReasons = {
  BUSINESS_TOO_YOUNG: "Недостаточный срок работы бизнеса",
  COMPANY_NOT_ACTIVE: "Компания не действует",
  ACCOUNTS_BLOCKED: "Счета заблокированы",
  CURRENT_OVERDUE: "Есть текущая просрочка",
  HISTORICAL_DEFAULT: "В кредитной истории есть длительная просрочка",
  INSUFFICIENT_REVENUE: "Выручка ниже требований продукта",
  COLLATERAL_REQUIRED: "Для продукта требуется залог",
  NON_POSITIVE_PROFIT: "Недостаточная чистая прибыль",
  LOW_SCORE: "Скоринговый балл ниже порога",
  DEBT_BURDEN_EXCEEDED: "Превышена допустимая долговая нагрузка",
  APPROVED_AMOUNT_BELOW_MINIMUM: "Доступная сумма ниже минимума продукта",
};

export function validInn(value) {
  if (!/^(\d{10}|\d{12})$/.test(value) || new Set(value).size === 1) return false;
  const digit = (weights) => weights.reduce((sum, w, i) => sum + Number(value[i]) * w, 0) % 11 % 10;
  return value.length === 10
    ? Number(value[9]) === digit([2, 4, 10, 3, 5, 9, 4, 6, 8])
    : Number(value[10]) === digit([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) &&
      Number(value[11]) === digit([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]);
}

export const fieldLabels = {
  name: "Название компании", inn: "ИНН", registration_date: "Дата регистрации",
  address: "Юридический адрес", industry: "ОКВЭД", annual_revenue: "Годовая выручка",
  monthly_expenses: "Расходы в месяц", monthly_debt_payments: "Платежи по кредитам",
  outstanding_debt: "Остаток долга", credit_history: "Кредитная история",
  overdue_days: "Текущая просрочка", has_collateral: "Обеспечение",
};
export const auditActions = {
  DRAFT_CREATED: "Создан черновик", APPLICATION_UPDATED: "Обновлены данные заявки",
  APPLICATION_SUBMITTED: "Заявка отправлена", ASSIGNED_TO_OFFICER: "Сотрудник взял заявку в работу",
  EXTERNAL_CHECKS_COMPLETED: "Получены результаты проверки ФНС и БКИ",
  CLARIFICATION_REQUESTED: "Сотрудник запросил уточнение", CLARIFICATION_REPLIED: "Отправлен ответ сотруднику",
  PRIMARY_REVIEW_REJECTED: "Заявка отклонена сотрудником", PRIMARY_REVIEW_PASSED: "Первичная проверка завершена",
  AUTOMATIC_ANALYSIS_STARTED: "Запущен автоматический анализ", AUTOMATIC_DECISION: "Получено решение по заявке",
  OFFER_ACCEPTED: "Предложение принято", OFFER_DECLINED: "Предложение отклонено",
  CONTRACT_GENERATED: "Сформирован договор", SIGNING_CODE_REJECTED: "Неверный код подписания",
  DEMO_CONTRACT_SIGNED: "Договор подписан, кредит оформлен",
  DOCUMENT_UPLOADED: "Загружен документ", DOCUMENT_DELETED: "Удалён документ",
};
export const factorLabels = {
  BUSINESS_AGE: "Срок работы бизнеса", REVENUE_TO_LOAN: "Соотношение выручки и суммы кредита",
  PROFIT_MARGIN: "Рентабельность", CREDIT_DISCIPLINE: "Кредитная дисциплина", TAX_DISCIPLINE: "Налоговая дисциплина",
};
export const discrepancyLabels = {
  UNDERSTATED_MONTHLY_PAYMENTS: "Платежи по кредитам в заявке ниже платежей по действующим кредитам",
  UNDERSTATED_OUTSTANDING_DEBT: "Остаток долга в заявке ниже долга по действующим кредитам",
};
export function checkRows(results) {
  const f = results.fns || {}, b = results.bki || {};
  const yesNo = (value) => value == null ? "Нет данных" : value ? "Да" : "Нет";
  const days = (value) => value == null ? "Нет данных" : `${value} дн.`;
  return [
    ["ФНС: статус компании", { active: "Действует", liquidation: "Ликвидация" }[f.status] || f.status || "Нет данных"],
    ["ФНС: блокировка счетов", yesNo(f.account_blocked)],
    ["ФНС: налоговая задолженность", f.tax_debt == null ? "Нет данных" : money(f.tax_debt)],
    ["ФНС: дата регистрации", f.registration_date ? date(f.registration_date) : "Нет данных"],
    ["Проверка руководителя", "Личность руководителя не проверялась: учебные данные"],
    ["БКИ: закрытые кредиты", b.closed_loans ?? "Нет данных"],
    ["БКИ: текущая просрочка", days(b.current_overdue_days)],
    ["БКИ: максимальная прошлая просрочка", days(b.historical_overdue_days)],
    ["БКИ: ежемесячные платежи", b.monthly_payments == null ? "Нет данных" : money(b.monthly_payments)],
    ["БКИ: остаток долга", b.outstanding_debt == null ? "Нет данных" : money(b.outstanding_debt)],
  ];
}
export function reviewSummary(results) {
  const issues = (results.discrepancies || []).map((code) => discrepancyLabels[code] || code);
  if (results.fns?.status !== "active") issues.push("Компания не действует");
  if (results.fns?.account_blocked) issues.push("Счета заблокированы");
  if (Number(results.fns?.tax_debt) > 0) issues.push("Есть налоговая задолженность");
  if (Number(results.bki?.current_overdue_days) > 0) issues.push("Есть текущая просрочка");
  if (Number(results.bki?.historical_overdue_days) > 0) issues.push("В истории есть просрочки");
  return issues.length
    ? `По учебным данным ФНС и БКИ: ${issues.join("; ")}. Требуется оценка сотрудника.`
    : "По учебным данным ФНС и БКИ компания действует, счета не заблокированы, задолженность по налогам и просрочки отсутствуют. Расхождений с действующими кредитами не обнаружено. Оцените документы перед запуском автоанализа.";
}
