import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
const base = process.env.TEST_BASE_URL || "http://127.0.0.1:15173";
const password = process.env.TEST_PASSWORD;
if (process.env.TEST_ISOLATED_DEMO !== "1" || !password) throw new Error("Requires TEST_ISOLATED_DEMO=1 and TEST_PASSWORD for a fresh isolated demo database.");
const clientEmail = process.env.TEST_CLIENT_EMAIL || `draft-flow-${Date.now()}@example.com`;
const officerEmail = process.env.TEST_OFFICER_EMAIL || "officer@example.com";
async function api(path, token, body, method = body ? "POST" : "GET") {
  const response = await fetch(`${base}/api/v1${path}`, {
    method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  assert.ok(response.ok, `${method} ${path}: ${response.status} ${await response.clone().text()}`);
  return response.json();
}
if (!process.env.TEST_CLIENT_EMAIL) await api("/auth/register", null, { email: clientEmail, password });
const clientToken = (await api("/auth/login", null, { email: clientEmail, password })).access_token;
const officerToken = (await api("/auth/login", null, { email: officerEmail, password })).access_token;
const me = await api("/auth/me", clientToken);
let initial = await api("/profile", clientToken);
await api("/profile", clientToken, {
  company: initial.company.inn ? initial.company : { name: "ООО «Демо Бизнес»", inn: "7700000009", registration_date: "2020-01-01", industry: "62.01", address: "Учебный адрес, дом 1" },
  financials: initial.financials.annual_revenue ? initial.financials : { annual_revenue: "24000000", monthly_expenses: "500000", monthly_debt_payments: "0", outstanding_debt: "0", credit_history: "good", overdue_days: 0, has_collateral: false },
  external_liabilities: { monthly_debt_payments: "40000", outstanding_debt: "250000" },
}, "PUT");
initial = await api("/profile", clientToken);
for (const [payment, debt] of [["85000", "900000"], ["15000", "100000"]]) await api("/bank/loans/import", officerToken, {
  client_id: me.id, external_reference: crypto.randomUUID(), amount: "2000000", outstanding_balance: debt,
  monthly_payment: payment, term_months: 36, annual_rate: "15", status: "active", overdue_days: 0,
  company_snapshot: initial.company, financials_snapshot: initial.financials,
});
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
async function login(email) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base);
  await page.locator(".profile-btn").click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  return page;
}
async function close(page) {
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
}
async function next(page, destination) {
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await destination.waitFor();
  await expect(page.getByRole("button", { name: /^Уведомления/ })).toBeEnabled();
}
async function openForm(page) {
  await page.getByRole("navigation").getByRole("button", { name: "Кредитный калькулятор", exact: true }).click();
  await page.getByRole("button", { name: "Оформить заявку", exact: false }).click();
  await page.getByRole("dialog").waitFor();
  await expect(page.locator(".modal-close")).toBeEnabled();
}
async function uploadAndSubmit(page) {
  for (const input of await page.locator('input[type="file"]').all()) {
    await input.setInputFiles({ name: "fixture.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nsynthetic regression fixture") });
    await expect(input).toBeEnabled();
  }
  await page.getByLabel("Подтверждаю актуальность сведений и согласие на их обработку").check();
  await page.getByRole("button", { name: "Отправить заявку", exact: true }).click();
  await page.locator(".application-heading .status").filter({ hasText: "Принята" }).waitFor();
  await expect(page.getByRole("button", { name: "Уведомления", exact: false })).toBeEnabled();
}
try {
  const client = await login(clientEmail);
  let draftCreates = 0, applicationCreates = 0;
  client.on("request", (request) => {
    if (request.method() !== "POST") return;
    if (request.url().endsWith("/client/application-drafts")) draftCreates++;
    if (request.url().endsWith("/client/applications")) applicationCreates++;
  });
  await openForm(client);
  assert.equal(draftCreates, 0);
  await next(client, client.getByLabel("Годовая выручка, ₽", { exact: true }));
  assert.equal(await client.getByLabel("Платежи по кредитам в месяц, ₽", { exact: true }).count(), 0);
  assert.equal(await client.getByText("Данные отличаются от профиля бизнеса", { exact: true }).count(), 0);
  const obligations = (await client.locator(".credit-obligations").innerText()).replace(/\s/g, "");
  assert.ok(obligations.includes("100000") && obligations.includes("40000") && obligations.includes("140000"));
  await next(client, client.getByRole("button", { name: "Отправить заявку", exact: true }));
  await close(client);
  assert.equal(draftCreates, 0);
  assert.equal(applicationCreates, 0);
  assert.deepEqual(await api("/client/application-drafts", clientToken), []);
  assert.deepEqual(await api("/client/applications", clientToken), []);

  await openForm(client);
  await client.getByLabel("ОКВЭД", { exact: true }).fill("63.11");
  await next(client, client.getByLabel("Годовая выручка, ₽", { exact: true }));
  await expect(client.locator(".profile-diff p")).toHaveText("ОКВЭД");
  assert.equal(draftCreates, 1);
  await client.screenshot({ path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-step-2-differences.png`, fullPage: true });
  await client.getByRole("button", { name: "Назад", exact: true }).click();
  await client.getByLabel("ИНН", { exact: true }).fill("770");
  await client.getByLabel("Название компании", { exact: true }).fill("Черновик с незавершённым вводом");
  await close(client);
  const [savedDraft] = await api("/client/application-drafts", clientToken);
  assert.equal(savedDraft.company.inn, "770");
  await client.reload();
  await client.locator(".profile-btn").filter({ hasText: initial.company.name }).waitFor();
  await openForm(client);
  await client.getByRole("heading", { name: "Продолжить заполнение?", exact: true }).waitFor();
  await client.getByRole("button", { name: "Создать новую заявку", exact: true }).click();
  await expect(client.getByLabel("ИНН", { exact: true })).toHaveValue(initial.company.inn);
  await close(client);
  assert.equal(draftCreates, 1);
  assert.equal((await api("/client/application-drafts", clientToken)).length, 1);
  await openForm(client);
  await client.getByRole("button", { name: "Продолжить черновик", exact: true }).click();
  await expect(client.getByLabel("ИНН", { exact: true })).toHaveValue("770");
  await client.getByLabel("ИНН", { exact: true }).fill(initial.company.inn);
  await next(client, client.getByLabel("Годовая выручка, ₽", { exact: true }));
  const diff = await client.locator(".profile-diff").innerText();
  assert.match(diff, /ОКВЭД/);
  assert.doesNotMatch(diff, /Платежи по кредитам|Остаток долга/);
  await client.getByLabel("Обновить профиль бизнеса данными этой заявки").check();
  await next(client, client.getByRole("button", { name: "Отправить заявку", exact: true }));
  await uploadAndSubmit(client);
  assert.equal(draftCreates, 1);
  const [first] = await api("/client/applications", clientToken);
  assert.equal(first.id, savedDraft.id);
  assert.deepEqual(await api("/client/application-drafts", clientToken), []);
  const syncedProfile = await api("/profile", clientToken);
  assert.equal(syncedProfile.company.industry, "63.11");
  assert.equal(Number(syncedProfile.financials.monthly_debt_payments), 40000);
  assert.equal(Number(syncedProfile.financials.outstanding_debt), 250000);

  const bank = await login(officerEmail);
  await bank.getByRole("navigation").getByRole("button", { name: /^Очередь заявок/ }).click();
  await bank.getByRole("row").filter({ hasText: first.id.slice(0, 8).toUpperCase() }).getByRole("button", { name: "Открыть заявку" }).click();
  await bank.getByRole("button", { name: "Взять в работу", exact: true }).click();
  await bank.getByRole("button", { name: "Проверить ФНС и БКИ", exact: false }).click();
  await expect(bank.getByLabel("Комментарий / заключение")).toHaveValue(/По учебным данным/);
  await bank.getByRole("button", { name: "Запустить автоанализ", exact: false }).click();
  await bank.locator(".application-heading .status").filter({ hasText: "Одобрена" }).waitFor();
  const analyzed = await api(`/client/applications/${first.id}`, clientToken);
  assert.equal(Number(analyzed.decision.metrics.existing_monthly_payments), 140000);
  assert.deepEqual(analyzed.history.map((event) => event.action), ["ASSIGNED_TO_OFFICER", "APPLICATION_SUBMITTED"]);
  await close(client);
  await client.getByRole("button", { name: /^Уведомления/ }).click();
  await client.locator(".notification-item").filter({ hasText: first.id.slice(0, 8).toUpperCase() }).first().getByRole("button", { name: "Открыть заявку" }).click();
  await client.locator(".application-heading .status").filter({ hasText: "Одобрена" }).waitFor();
  const history = client.locator(".history-section");
  assert.doesNotMatch(await history.innerText(), /Получены результаты проверки|Первичная проверка|По учебным данным|Запущен автоматический анализ|Получено решение по заявке|Одобрена/);
  assert.match(await history.locator(".history-row").first().innerText(), /Сотрудник взял/);
  await close(client);

  await openForm(client);
  await client.getByLabel("Название компании", { exact: true }).fill("Вторая заявка: самая новая");
  await next(client, client.getByLabel("Годовая выручка, ₽", { exact: true }));
  await next(client, client.getByRole("button", { name: "Отправить заявку", exact: true }));
  await uploadAndSubmit(client);
  await close(client);
  const applications = await api("/client/applications", clientToken);
  assert.equal(applications.length, 2);
  assert.equal(applications[1].id, first.id);
  await client.getByRole("navigation").getByRole("button", { name: /^Мои кредиты/ }).click();
  await expect(client.locator("tbody tr").first()).toContainText(applications[0].id.slice(0, 8).toUpperCase());
  assert.equal(await client.locator('option[value="DRAFT"]').count(), 0);
  assert.equal(applicationCreates, 0);
  assert.deepEqual(errors, []);
  console.log("PASS: no draft from autofill/open/step navigation, immediate OKVED notice on step 2, read-only/additive debt payments, partial draft persistence, resume/new chooser, same application on submit, protected profile sync, hidden analysis/approval events and newest-first lists/history");
} catch (error) {
  let index = 0;
  for (const context of browser.contexts()) for (const page of context.pages()) await page.screenshot({ path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/draft-flow-failure-${index++}.png`, fullPage: true });
  throw error;
} finally {
  await browser.close();
}
