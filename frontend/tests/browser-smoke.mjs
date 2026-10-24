import { chromium } from "@playwright/test";
import assert from "node:assert/strict";
const browser = await chromium.launch({
  ...(process.env.CHROME_PATH
    ? { executablePath: process.env.CHROME_PATH }
    : { channel: "chrome" }),
  headless: true,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const failures = [];
page.on("pageerror", (e) => failures.push(e.message));
await page.goto(process.env.TEST_BASE_URL || "http://127.0.0.1:5173");
await page
  .getByRole("heading", { name: "Ваш бизнес. Новый уровень." })
  .waitFor();
await page.screenshot({
  path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-home-desktop.png`,
  fullPage: true,
});
await page
  .getByRole("button", { name: "Кредитный калькулятор", exact: true })
  .click();
await page
  .getByRole("heading", { name: "Кредитный калькулятор", exact: true })
  .waitFor();
await page.getByRole("button", { name: "Оформить заявку" }).click();
await page.getByRole("dialog").waitFor();
await page
  .getByRole("button", { name: "Впервые здесь? Зарегистрироваться" })
  .click();
const email = `frontend-smoke-${Date.now()}@example.com`;
await page.getByLabel("Электронная почта").fill(email);
await page.getByLabel("Пароль", { exact: true }).fill("Frontend-test-2026!");
await page
  .getByRole("button", { name: "Создать аккаунт", exact: true })
  .click();
await page.getByRole("dialog").waitFor({ state: "hidden" });
await page.getByRole("button", { name: "Оформить заявку" }).click();
await page.getByRole("dialog").waitFor();
await page
  .getByLabel("Название компании", { exact: true })
  .fill("ООО Тест интерфейса");
await page.getByLabel("ИНН", { exact: true }).fill("7700000009");
await page.getByLabel("Дата регистрации", { exact: true }).fill("2020-01-15");
await page.getByLabel("ОКВЭД", { exact: true }).fill("62.01");
await page
  .getByLabel("Юридический адрес", { exact: true })
  .fill("Москва, Тестовая улица, 1");
await page.getByRole("button", { name: "Продолжить", exact: true }).click();
await page.getByLabel("Годовая выручка, ₽", { exact: true }).fill("24000000");
await page.getByLabel("Расходы в месяц, ₽", { exact: true }).fill("500000");
await page.getByRole("button", { name: "Продолжить", exact: true }).click();
await page
  .getByText("PDF, PNG или JPEG, до 10 МБ на файл. Не более 20 файлов.")
  .waitFor();
for (const input of await page.locator("input[type=file]").all()) {
  await input.setInputFiles({
    name: "test-document.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from(
      "%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF",
    ),
  });
  await page
    .getByRole("button", { name: "Отправить заявку", exact: true })
    .waitFor();
  await page.waitForFunction(
    () => !document.querySelector("input[type=file]")?.disabled,
  );
}
await page
  .getByLabel("Подтверждаю актуальность сведений и согласие на их обработку")
  .check();
await page
  .getByRole("button", { name: "Отправить заявку", exact: true })
  .click();
await page
  .getByText("Заявка отправлена на рассмотрение", { exact: true })
  .waitFor();
assert.equal(await page.getByRole("alert").count(), 0);
await page.getByRole("button", { name: "Закрыть", exact: true }).click();
await page.getByRole("button", { name: "Мои кредиты", exact: true }).click();
await page.getByRole("cell", { name: "Принята", exact: true }).waitFor();
await page.screenshot({
  path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-loans-desktop.png`,
  fullPage: true,
});
await page
  .getByRole("button", { name: "Чат с помощником", exact: false })
  .click();
await page
  .getByRole("button", { name: "Какие документы нужны для кредита?" })
  .click();
await page
  .getByText("Обычно нужны регистрационные документы", { exact: false })
  .waitFor();
await page.setViewportSize({ width: 390, height: 844 });
await page.getByRole("button", { name: "Главная", exact: true }).click();
await page.screenshot({
  path: `${process.env.TEST_ARTIFACT_DIR || "/tmp"}/credit-home-mobile.png`,
  fullPage: true,
});
assert.ok(
  await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  ),
  "Mobile viewport must not overflow",
);
assert.deepEqual(failures, []);
console.log(
  "PASS: registration, calculator, company, financials, document uploads, submission, list, assistant, mobile layout; email:",
  email,
);
await browser.close();
