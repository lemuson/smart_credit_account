import test from "node:test";
import assert from "node:assert/strict";
import { payment, matches } from "../src/domain.js";
test("annuity preview handles interest and zero-interest products", () => {
  assert.ok(Math.abs(payment("1500000", "18", 24) - 74886.15) < 1);
  assert.equal(payment("120000", 0, 12), 10000);
});
test("product matching respects inclusive limits, purpose and availability", () => {
  const p = {
    active: true,
    purposes: ["equipment"],
    min_amount: "100000",
    max_amount: "1000000",
    min_term_months: 6,
    max_term_months: 60,
  };
  assert.equal(matches(p, "equipment", 100000, 6), true);
  assert.equal(matches(p, "equipment", 1000000, 60), true);
  assert.equal(matches(p, "equipment", 1000001, 24), false);
  assert.equal(matches(p, "working_capital", 200000, 24), false);
  assert.equal(
    matches({ ...p, active: false }, "equipment", 200000, 24),
    false,
  );
});

test("INN checksum accepts legal entity and entrepreneur numbers and rejects malformed input", async () => {
  const { validInn } = await import("../src/domain.js");
  for (const inn of ["7700000009", "7707083893", "500100732259"]) assert.equal(validInn(inn), true, inn);
  for (const inn of ["7700000001", "500100732250", "0000000000", "111111111111", "770000000", "770000000x", ""]) assert.equal(validInn(inn), false, inn);
});

test("check explanations preserve adverse data and distinguish demo checks", async () => {
  const { checkRows, reviewSummary } = await import("../src/domain.js");
  const results = { fns: { status: "active", account_blocked: false, tax_debt: "0" }, bki: { current_overdue_days: 0, historical_overdue_days: 0 }, discrepancies: [] };
  assert.match(reviewSummary(results), /Расхождений.*не обнаружено/);
  assert.ok(checkRows(results).some(([label, value]) => label.includes("руководителя") && value.includes("не проверялась")));
  results.discrepancies.push("UNDERSTATED_OUTSTANDING_DEBT");
  results.fns.account_blocked = true;
  assert.match(reviewSummary(results), /Остаток долга.*ниже/);
  assert.match(reviewSummary(results), /Счета заблокированы/);
});
