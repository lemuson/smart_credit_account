import test from "node:test";
import assert from "node:assert/strict";

globalThis.sessionStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
const {
  api,
  createScoringAssessment,
  getScoringAssessment,
  createScoringWhatIf,
} = await import("../src/api.js");
const { formatFeatureValue, scoringFeatureLabels } = await import("../src/domain.js");

test("createScoringAssessment sends proper headers, UUIDs and body", async () => {
  let capturedUrl = "";
  let capturedOptions = {};

  globalThis.fetch = async (url, options) => {
    capturedUrl = url;
    capturedOptions = options;
    return {
      ok: true,
      status: 201,
      json: async () => ({
        assessment_id: "71000000-0000-0000-0000-000000000001",
        application_id: "88000000-0000-0000-0000-000000000001",
        score: { name: "synthetic_model_score", value: 0.74, display_percent: 74.0 },
      }),
    };
  };

  const res = await createScoringAssessment("88000000-0000-0000-0000-000000000001", 2);
  assert.equal(capturedUrl, "/api/v1/scoring/assessments");
  assert.equal(capturedOptions.method, "POST");
  assert.ok(capturedOptions.headers["Idempotency-Key"]);
  assert.ok(capturedOptions.headers["X-Request-ID"]);
  const body = JSON.parse(capturedOptions.body);
  assert.equal(body.application_id, "88000000-0000-0000-0000-000000000001");
  assert.equal(body.expected_application_version, 2);
  assert.equal(res.assessment_id, "71000000-0000-0000-0000-000000000001");
});

test("getScoringAssessment supports what_if_id query parameter", async () => {
  let capturedUrl = "";
  globalThis.fetch = async (url) => {
    capturedUrl = url;
    return {
      ok: true,
      status: 200,
      json: async () => ({ assessment_id: "71000000-0000-0000-0000-000000000001" }),
    };
  };

  await getScoringAssessment("71000000-0000-0000-0000-000000000001");
  assert.equal(capturedUrl, "/api/v1/scoring/assessments/71000000-0000-0000-0000-000000000001");

  await getScoringAssessment("71000000-0000-0000-0000-000000000001", "73000000-0000-0000-0000-000000000001");
  assert.equal(
    capturedUrl,
    "/api/v1/scoring/assessments/71000000-0000-0000-0000-000000000001?what_if_id=73000000-0000-0000-0000-000000000001"
  );
});

test("createScoringWhatIf sends changes and idempotency headers", async () => {
  let capturedUrl = "";
  let capturedOptions = {};

  globalThis.fetch = async (url, options) => {
    capturedUrl = url;
    capturedOptions = options;
    return {
      ok: true,
      status: 201,
      json: async () => ({
        what_if_id: "73000000-0000-0000-0000-000000000001",
        delta_percentage_points: 5.2,
      }),
    };
  };

  const res = await createScoringWhatIf("71000000-0000-0000-0000-000000000001", {
    loan_amount: 2000000,
    has_collateral: true,
  });

  assert.equal(capturedUrl, "/api/v1/scoring/assessments/71000000-0000-0000-0000-000000000001/what-if");
  assert.equal(capturedOptions.method, "POST");
  assert.ok(capturedOptions.headers["Idempotency-Key"]);
  assert.ok(capturedOptions.headers["X-Request-ID"]);
  const body = JSON.parse(capturedOptions.body);
  assert.deepEqual(body.changes, { loan_amount: 2000000, has_collateral: true });
  assert.equal(res.delta_percentage_points, 5.2);
});

test("scoring Problem Details errors produce readable Russian messages", async () => {
  const cases = [
    { code: "SCORING_UNAVAILABLE", expected: "Сервис ML-скоринга временно недоступен. Проверьте готовность моделей." },
    { code: "SCORING_BUSY", expected: "Сервер занят расчётом оценок. Повторите попытку через несколько секунд." },
    { code: "SCORING_NO_CHANGED_FIELDS", expected: "Для симуляции What-if измените хотя бы один показатель." },
    { code: "SCORING_SCOPE_REQUIRED", expected: "Расчёт ML-скоринга доступен только клиенту для своей организации." },
  ];

  for (const c of cases) {
    globalThis.fetch = async () => ({
      ok: false,
      status: 503,
      json: async () => ({
        type: "about:blank",
        title: "Error",
        status: 503,
        code: c.code,
        detail: "Raw technical detail",
      }),
    });
    await assert.rejects(createScoringAssessment("88000000-0000-0000-0000-000000000001"), {
      message: c.expected,
    });
  }
});

test("formatFeatureValue correctly formats currency, months and boolean features", () => {
  assert.ok(formatFeatureValue("annual_revenue", 5000000).includes("5"));
  assert.equal(formatFeatureValue("business_age_months", 36), "36 мес.");
  assert.equal(formatFeatureValue("loan_term_months", 12), "12 мес.");
  assert.equal(formatFeatureValue("has_collateral", true), "Есть залог");
  assert.equal(formatFeatureValue("has_collateral", false), "Без залога");
  assert.equal(formatFeatureValue("credit_history", "good"), "Без просрочек");
  assert.equal(formatFeatureValue("credit_history", "bad"), "Были просрочки");
});
