import { chromium, expect } from "@playwright/test";
import assert from "node:assert/strict";
const base = process.env.TEST_BASE_URL || "http://127.0.0.1:15173";
const officerEmail = process.env.TEST_OFFICER_EMAIL;
const officerPassword = process.env.TEST_PASSWORD;
if (!officerEmail || !officerPassword) throw new Error("Set TEST_OFFICER_EMAIL and TEST_PASSWORD for an isolated demo backend.");
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
async function newPage() {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base);
  return page;
}
async function auth(page, email, password, register = false) {
  await page.locator(".profile-btn").click();
  if (register) await page.getByRole("button", { name: "Впервые здесь? Зарегистрироваться" }).click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: register ? "Создать аккаунт" : "Войти", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
}
async function close(page) { await page.getByRole("button", { name: "Закрыть", exact: true }).click(); }
async function next(page) {
  await page.getByRole("button", { name: "Продолжить", exact: true }).click();
  await page.waitForFunction(() => ![...document.querySelectorAll("button")].some((b) => b.textContent.includes("Сохраняем")));
}
try {
  const client = await newPage();
  await auth(client, `regression-${Date.now()}@example.com`, "Regression-demo-2026!", true);
  await client.getByRole("button", { name: "Кредитный калькулятор", exact: true }).click();
  assert.ok(await client.getByText("Переплата по процентам", { exact: true }).isVisible());
  await client.getByRole("button", { name: "Посмотреть график платежей", exact: false }).click();
  assert.doesNotMatch(await client.getByRole("dialog").innerText(), /не\s*число|NaN/i);
  await close(client);
  await client.getByRole("button", { name: "Оформить заявку", exact: false }).click();
  const dialog = client.getByRole("dialog");
  const draftResponse = client.waitForResponse((response) => response.url().endsWith("/client/application-drafts") && response.request().method() === "POST");
  await client.getByLabel("Название компании", { exact: true }).fill("ООО Регрессионная проверка");
  await client.getByLabel("ИНН", { exact: true }).fill("7700000001");
  await client.getByLabel("Дата регистрации", { exact: true }).fill("2020-01-15");
  await client.getByLabel("ОКВЭД", { exact: true }).fill("62.01");
  await client.getByLabel("Юридический адрес", { exact: true }).fill("Учебный адрес, дом 1");
  await next(client);
  assert.ok(await client.getByLabel("ИНН", { exact: true }).isVisible());
  assert.match(await dialog.innerText(), /Проверьте ИНН/);
  assert.doesNotMatch(await dialog.innerText(), /checksum|body.company/);
  await client.getByLabel("ИНН", { exact: true }).fill("7700000009");
  assert.ok(await client.getByText("Данные отличаются от профиля бизнеса", { exact: true }).isVisible());
  await client.getByLabel("Обновить профиль бизнеса данными этой заявки").check();
  await next(client);
  const applicationId = (await (await draftResponse).json()).id.slice(0, 8).toUpperCase();
  await client.getByLabel("Годовая выручка, ₽", { exact: true }).fill("24000000");
  await client.getByLabel("Расходы в месяц, ₽", { exact: true }).fill("500000");
  assert.ok(await client.getByText("Данные отличаются от профиля бизнеса", { exact: true }).isVisible());
  await next(client);
  assert.equal(await client.getByText("Данные отличаются от профиля бизнеса", { exact: true }).count(), 0);
  for (const input of await client.locator("input[type=file]").all()) {
    await input.setInputFiles({ name: "test.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\nsynthetic fixture") });
    await client.waitForFunction(() => !document.querySelector("input[type=file]")?.disabled);
  }
  assert.equal(await client.getByText("Создан черновик", { exact: true }).count(), 0);
  assert.equal(await client.getByText("Загружен документ", { exact: true }).count(), 0);
  assert.equal(await client.getByText("Обновлены данные заявки", { exact: true }).count(), 0);
  // Drafts are helper state, offered when reopening the form, rather than application rows.
  await close(client);
  await client.getByRole("button", { name: "Мои кредиты", exact: true }).click();
  assert.equal(await client.getByRole("row").filter({ hasText: applicationId }).count(), 0);
  assert.equal(await client.getByLabel("Статус заявки").locator('option[value="DRAFT"]').count(), 0);
  await client.getByRole("navigation").getByRole("button", { name: "Кредитный калькулятор", exact: true }).click();
  await client.getByRole("button", { name: "Оформить заявку", exact: false }).click();
  await client.getByRole("button", { name: "Продолжить черновик", exact: true }).click();
  await client.getByLabel("Обновить профиль бизнеса данными этой заявки").check();
  await next(client);
  await next(client);
  await client.getByLabel("Подтверждаю актуальность сведений и согласие на их обработку").check();
  await client.getByRole("button", { name: "Отправить заявку", exact: true }).click();
  await client.locator(".application-heading .status").filter({ hasText: "Принята" }).waitFor();
  await close(client);
  const previousHash = new URL(client.url()).hash;
  await client.getByRole("button", { name: /^Уведомления/ }).click();
  await client.getByRole("heading", { name: "Уведомления", exact: true }).waitFor();
  assert.equal(new URL(client.url()).hash, previousHash);
  await client.getByRole("button", { name: "Прочитать все", exact: true }).click();
  await client.getByText("Непрочитанных: 0", { exact: true }).waitFor();
  await close(client);
  await client.reload();
  await client.locator(".profile-btn").filter({ hasText: "ООО Регрессионная проверка" }).waitFor();
  await client.getByRole("button", { name: /^Уведомления/ }).click();
  await client.getByText("Непрочитанных: 0", { exact: true }).waitFor();
  await close(client);
  await client.locator(".profile-btn").click();
  assert.equal(await client.getByLabel("Название компании", { exact: true }).inputValue(), "ООО Регрессионная проверка");
  await close(client);
  const bank = await newPage();
  await auth(bank, officerEmail, officerPassword);
  await bank.getByRole("button", { name: /^Уведомления/ }).click();
  await bank.getByRole("button", { name: "Прочитать все", exact: true }).click();
  await bank.getByText("Непрочитанных: 0", { exact: true }).waitFor();
  await close(bank);
  await bank.reload();
  await bank.locator(".profile-btn").filter({ hasText: "Сотрудник банка" }).waitFor();
  await bank.getByRole("button", { name: /^Уведомления/ }).click();
  await bank.getByText("Непрочитанных: 0", { exact: true }).waitFor();
  await close(bank);
  await bank.getByRole("navigation").getByRole("button", { name: /^Очередь заявок/ }).click();
  const openBank = async () => bank.getByRole("row").filter({ hasText: applicationId }).getByRole("button", { name: "Открыть заявку" }).click();
  await openBank();
  await bank.getByRole("button", { name: "Взять в работу", exact: true }).click();
  await bank.getByRole("button", { name: "Проверить ФНС и БКИ", exact: false }).waitFor();
  assert.equal(await bank.getByLabel("Комментарий / заключение").count(), 0);
  await bank.getByRole("button", { name: "Проверить ФНС и БКИ", exact: false }).click();
  await bank.getByLabel("Комментарий / заключение").waitFor();
  await expect(bank.getByLabel("Комментарий / заключение")).toHaveValue(/По учебным данным/);
  assert.ok(await bank.getByText("ФНС: статус компании", { exact: true }).isVisible());
  assert.equal(await bank.locator(".check-result pre").count(), 0);
  await bank.getByLabel("Комментарий / заключение").fill("Уточните годовую выручку.");
  await bank.getByRole("button", { name: "Запросить уточнение", exact: true }).click();
  await bank.locator(".application-heading .status").filter({ hasText: "Нужно уточнение" }).waitFor();
  await client.getByRole("navigation").getByRole("button", { name: /^Мои кредиты/ }).click();
  await client.getByLabel("Статус заявки").selectOption("all");
  await client.getByRole("button", { name: "Обновить заявки" }).click();
  await client.getByRole("row").filter({ hasText: applicationId }).getByRole("button", { name: "Открыть заявку" }).click();
  await next(client);
  await client.getByLabel("Годовая выручка, ₽", { exact: true }).fill("25000000");
  await next(client);
  await client.getByLabel("Подтверждаю актуальность сведений и согласие на их обработку").check();
  await client.getByRole("button", { name: "Отправить заявку", exact: true }).click();
  await client.locator(".application-heading .status").filter({ hasText: "На проверке" }).waitFor();
  assert.equal(await client.getByText("Создан черновик", { exact: true }).count(), 0);
  await close(bank);
  await bank.getByRole("button", { name: "Обновить", exact: true }).click();
  await openBank();
  assert.match(await bank.getByRole("dialog").innerText(), /Изменены сведения: Годовая выручка/);
  assert.match(await bank.getByRole("dialog").innerText(), /Результаты устарели/);
  await bank.getByRole("button", { name: "Проверить ФНС и БКИ", exact: false }).click();
  await bank.getByRole("button", { name: "Запустить автоанализ", exact: false }).click();
  await bank.locator(".application-heading .status").filter({ hasText: "Одобрена" }).waitFor();
  await bank.getByText("Факторы оценки", { exact: true }).click();
  assert.ok(await bank.getByText("Кредитная дисциплина", { exact: true }).isVisible());
  assert.equal(await bank.locator(".decision-section pre").count(), 0);
  await close(client);
  await client.getByRole("button", { name: /^Уведомления/ }).click();
  await client.locator(".notification-item").filter({ hasText: applicationId }).first().getByRole("button", { name: "Открыть заявку", exact: true }).click();
  await client.locator(".application-heading .status").filter({ hasText: "Одобрена" }).waitFor();
  for (const text of ["Получено решение по заявке", "Получены результаты проверки ФНС и БКИ", "Первичная проверка завершена", "Запущен автоматический анализ", "Загружен документ", "Обновлены данные заявки"]) {
    assert.equal(await client.getByText(text, { exact: true }).count(), 0);
  }
  const pdfResponse = client.waitForResponse((response) => response.url().endsWith("/contract/pdf"));
  await client.getByRole("button", { name: "Принять предложение", exact: true }).click();
  const pdf = await pdfResponse;
  assert.equal(pdf.headers()["content-type"], "application/pdf");
  await client.locator("iframe.contract-preview").waitFor();
  assert.match(await client.locator("iframe.contract-preview").getAttribute("src"), /^blob:/);
  assert.equal(await client.locator(".contract-section pre").count(), 0);
  const [download] = await Promise.all([
    client.waitForEvent("download"),
    client.getByRole("link", { name: "Скачать договор в PDF", exact: true }).click(),
  ]);
  assert.match(download.suggestedFilename(), /^contract-.*\.pdf$/);
  await download.saveAs(`${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-contract-regression.pdf`);
  await client.locator("iframe.contract-preview").scrollIntoViewIfNeeded();
  // Chromium's built-in PDF viewer paints asynchronously after the frame loads.
  await client.waitForTimeout(2000);
  await client.screenshot({ path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-contract-preview.png`, fullPage: true });
  await close(client);
  await client.locator(".profile-btn").click();
  await client.getByRole("button", { name: "Выйти из кабинета", exact: false }).click();
  await client.locator(".profile-btn").click();
  assert.equal(await client.getByLabel("Электронная почта").inputValue(), "");
  assert.equal(await client.getByLabel("Пароль", { exact: true }).inputValue(), "");
  assert.deepEqual(errors, []);
  console.log("PASS: INN on step 1, overpayment, one resumable draft, filtered newest-first history, draft chooser, early profile differences, persistent notifications for both roles, officer checks, clarification, scoring, PDF preview/download and logout reset");
} catch (error) {
  let index = 0;
  for (const context of browser.contexts()) for (const page of context.pages()) {
    await page.screenshot({ path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-regression-failure-${index++}.png`, fullPage: true });
  }
  throw error;
} finally {
  await browser.close();
}
