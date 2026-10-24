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
