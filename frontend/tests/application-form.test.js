import test from "node:test";
import assert from "node:assert/strict";
import { applicationFinancials, draftData, draftFingerprint, profileDifferences } from "../src/applicationForm.js";
import { emptyCompany, emptyFinancials } from "../src/domain.js";

test("OKVED differences remain visible on transition to step 2 and exclude loan obligations", () => {
  const company = { ...emptyCompany(), industry: "63.11" };
  const finance = { ...emptyFinancials(), monthly_debt_payments: "85000", outstanding_debt: "900000" };
  const profile = { company: { ...company, industry: "62.01" }, financials: emptyFinancials() };
  assert.deepEqual(profileDifferences(company, finance, profile, 1), ["ОКВЭД"]);
  assert.deepEqual(profileDifferences(company, finance, profile, 2), ["ОКВЭД"]);
  assert.deepEqual(profileDifferences(company, finance, profile, 3), []);
});
test("autofilled defaults and monetary formatting do not count as changes", () => {
  const company = emptyCompany(), finance = emptyFinancials();
  assert.deepEqual(profileDifferences(company, finance, { company: {}, financials: {} }, 2), []);
  const before = { ...finance, annual_revenue: "24000000.00" };
  assert.equal(draftFingerprint(company, before), draftFingerprint(company, { ...before, annual_revenue: "24000000" }));
  assert.notEqual(draftFingerprint(company, before), draftFingerprint({ ...company, industry: "63.11" }, before));
});
test("application and draft payloads cannot edit profile-owned debt payments", () => {
  const company = emptyCompany(), finance = { ...emptyFinancials(), monthly_debt_payments: "999999" };
  const profile = { monthly_debt_payments: "40000", outstanding_debt: "250000" };
  assert.equal(applicationFinancials(finance, profile).monthly_debt_payments, "40000");
  assert.equal(applicationFinancials(finance, profile).outstanding_debt, "250000");
  assert.equal("monthly_debt_payments" in draftData(company, finance).financials, false);
  assert.equal("outstanding_debt" in draftData(company, finance).financials, false);
});
