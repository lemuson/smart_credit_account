import test from "node:test";
import assert from "node:assert/strict";

globalThis.sessionStorage = { getItem: () => null };
const { api } = await import("../src/api.js");

test("INN errors from both FastAPI validation envelopes have a readable Russian message", async () => {
  for (const detail of [
    [{ loc: ["body", "company", "inn"], msg: "Value error, invalid INN checksum" }],
    { code: "INVALID_INPUT", errors: [{ field: "body.company.inn", message: "Value error, invalid INN checksum" }] },
  ]) {
    globalThis.fetch = async () => ({ ok: false, status: 422, json: async () => ({ detail }) });
    await assert.rejects(api("/profile"), { message: "Проверьте ИНН и его контрольные цифры." });
  }
});
