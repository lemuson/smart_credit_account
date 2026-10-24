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
