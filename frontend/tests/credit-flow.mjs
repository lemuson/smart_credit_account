import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
const base = process.env.TEST_BASE_URL || "http://127.0.0.1:8080";
const email = process.env.TEST_CLIENT_EMAIL;
const officer = process.env.TEST_OFFICER_EMAIL;
const password = process.env.TEST_PASSWORD;
if (!email || !officer || !password)
  throw new Error(
    "Set TEST_CLIENT_EMAIL, TEST_OFFICER_EMAIL and TEST_PASSWORD for synthetic test users.",
  );
const browser = await chromium.launch({ channel: "chrome", headless: true });
const errors = [];
async function login(email) {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base);
  await page
    .getByRole("button", { name: "Личный кабинет", exact: false })
    .click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  return page;
}
const bank = await login(officer);
await bank.getByRole("navigation").getByRole("button", { name: /^Очередь заявок/ }).click();
const targetRow = bank
  .getByRole("row")
  .filter({ hasText: "ООО Тест интерфейса" })
  .filter({ hasText: "Принята" })
  .first();
const applicationId = (await targetRow.innerText()).match(/№ ([A-F0-9]+)/)[1];
await targetRow.getByRole("button", { name: "Открыть заявку" }).click();
await bank.getByRole("button", { name: "Взять в работу", exact: true }).click();
await bank.getByRole("button", { name: "Проверить ФНС и БКИ", exact: false }).click();
await bank.getByLabel("Комментарий / заключение").waitFor();
await bank
  .getByLabel("Комментарий / заключение")
  .fill("Уточните финансовые сведения и подтвердите их актуальность.");
await bank
  .getByRole("button", { name: "Запросить уточнение", exact: true })
  .click();
await bank
  .locator(".application-heading .status")
  .filter({ hasText: "Нужно уточнение" })
  .waitFor();
const client = await login(email);
await client.getByRole("button", { name: /^Мои кредиты/ }).click();
await client
  .getByRole("button", { name: "Открыть заявку", exact: true })
  .click();
await client.getByRole("button", { name: "Продолжить", exact: true }).click();
await client.getByRole("button", { name: "Продолжить", exact: true }).click();
await client
  .getByLabel("Дополнение к ответу (необязательно)")
  .fill("Сведения проверены, финансовые показатели актуальны.");
await client
  .getByLabel("Подтверждаю актуальность сведений и согласие на их обработку")
  .check();
await client
  .getByRole("button", { name: "Отправить заявку", exact: true })
  .click();
await client
  .locator(".application-heading .status")
  .filter({ hasText: "На проверке" })
  .waitFor();
await bank.getByRole("button", { name: "Закрыть", exact: true }).click();
await bank.getByRole("button", { name: "Обновить", exact: true }).click();
await bank
  .getByRole("row")
  .filter({ hasText: applicationId })
  .getByRole("button", { name: "Открыть заявку" })
  .click();
await bank
  .getByRole("button", { name: "Проверить ФНС и БКИ", exact: false })
  .click();
await bank.getByText("Проверка от", { exact: false }).waitFor();
await bank
  .getByLabel("Комментарий / заключение")
  .fill("Данные полные, несоответствий нет. Рекомендуется одобрение.");
await bank
  .getByRole("button", { name: "Запустить автоанализ", exact: false })
  .click();
await bank
  .locator(".application-heading .status")
  .filter({ hasText: "Одобрена" })
  .waitFor();
await bank.screenshot({
  path: "/tmp/credit-officer-dossier.png",
  fullPage: true,
});
await client.getByRole("button", { name: "Закрыть", exact: true }).click();
await client.getByRole("button", { name: "Обновить заявки" }).click();
await client
  .getByRole("button", { name: "Открыть заявку", exact: true })
  .click();
await client
  .getByRole("button", { name: "График платежей", exact: true })
  .click();
await client
  .getByRole("heading", { name: "График платежей", exact: true })
  .waitFor();
assert.ok(!(await client.getByRole("cell", { name: "Invalid Date" }).count()));
await client
  .getByRole("button", { name: "Вернуться к заявке", exact: true })
  .click();
await client
  .getByRole("button", { name: "Принять предложение", exact: true })
  .click();
await client.locator("iframe.contract-preview").waitFor();
await client.getByLabel("Код подтверждения (демо: 123456)").fill("123456");
await client
  .getByRole("button", { name: "Подтвердить оформление", exact: true })
  .click();
await client
  .getByText("Кредит оформлен в демонстрационном режиме", { exact: true })
  .waitFor();
await client.screenshot({ path: "/tmp/credit-disbursed.png", fullPage: true });
assert.deepEqual(errors, []);
console.log(
  "PASS: officer assignment, clarification request/reply, FNS/BKI checks, automatic scoring, offer schedule, acceptance, contract, demo signature and DISBURSED state",
);
await browser.close();
