import { emptyCompany, emptyFinancials, fieldLabels } from "./domain.js";

export const externalFields = ["monthly_debt_payments", "outstanding_debt"];
export const editableFinancialFields = ["annual_revenue", "monthly_expenses", "credit_history", "overdue_days", "has_collateral"];

function canonical(value) {
  const raw = String(value ?? "");
  if (!/^-?\d+(\.\d+)?$/.test(raw)) return raw;
  const [integer, fraction = ""] = raw.split(".");
  const whole = integer.replace(/^(-?)0+(?=\d)/, "$1");
  const tail = fraction.replace(/0+$/, "");
  return tail ? `${whole}.${tail}` : whole;
}
export function draftData(company, financials) {
  return {
    company: Object.fromEntries(Object.keys(emptyCompany()).map((key) => [key, String(company[key] ?? "")])),
    financials: Object.fromEntries(editableFinancialFields.map((key) => [key,
      key === "has_collateral" ? !!financials[key] : String(financials[key] ?? ""),
    ])),
  };
}
export function draftFingerprint(company, financials) {
  const data = draftData(company, financials);
  for (const key of ["annual_revenue", "monthly_expenses", "overdue_days"]) data.financials[key] = canonical(data.financials[key]);
  return JSON.stringify(data);
}
export function applicationFinancials(financials, profileFinancials = {}) {
  return {
    ...financials,
    annual_revenue: String(financials.annual_revenue),
    monthly_expenses: String(financials.monthly_expenses),
    ...Object.fromEntries(externalFields.map((key) => [key, String(profileFinancials[key] || "0")])),
  };
}
export function profileDifferences(company, financials, profile, step) {
  if (step > 2) return [];
  const baseCompany = { ...emptyCompany(), ...profile.company };
  const baseFinancials = { ...emptyFinancials(), ...profile.financials };
  return [
    ...Object.keys(baseCompany).filter((key) => String(company[key] ?? "") !== String(baseCompany[key] ?? "")),
    ...(step === 2 ? editableFinancialFields.filter((key) => canonical(financials[key]) !== canonical(baseFinancials[key])) : []),
  ].map((key) => fieldLabels[key] || key);
}
