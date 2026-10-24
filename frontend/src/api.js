let token = sessionStorage.getItem("credit-token") || "";
export function setToken(value) {
  token = value;
  value
    ? sessionStorage.setItem("credit-token", value)
    : sessionStorage.removeItem("credit-token");
}
const messages = {
  AI_DISABLED: "AI-помощник отключён. Проверьте настройки сервера.",
  CONVERSATION_BUSY: "Дождитесь ответа на предыдущее сообщение.",
  INVALID_CREDENTIALS: "Неверная почта или пароль.",
  EMAIL_ALREADY_EXISTS: "Эта почта уже зарегистрирована.",
  APPLICATION_VERSION_CONFLICT:
    "Заявка изменилась. Откройте её заново и повторите действие.",
  APPLICATION_INVALID:
    "Проверьте сведения и приложите все обязательные документы.",
  INVALID_INN: "Проверьте ИНН и его контрольные цифры.",
  INVALID_SIGNING_CODE: "Неверный код подтверждения.",
  FRESH_EXTERNAL_CHECKS_REQUIRED: "Сначала запустите актуальные проверки.",
  UNRESOLVED_DISCREPANCIES: "Необходимо устранить несоответствия в данных.",
  INVALID_APPLICATION_STATE: "Действие недоступно в текущем статусе заявки.",
};
export async function api(path, { method = "GET", body, raw = false } = {}) {
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body && !(body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
      },
      body:
        body instanceof FormData
          ? body
          : body
            ? JSON.stringify(body)
            : undefined,
    });
  } catch {
    throw new Error(
      "Не удалось подключиться к серверу. Проверьте подключение и повторите попытку.",
    );
  }
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      /* Non-JSON gateway response */
    }
    if (response.status === 401 && token) {
      setToken("");
      window.dispatchEvent(new Event("credit-session-expired"));
    }
    const detail = data?.detail;
    const fields = Array.isArray(detail)
      ? detail
          .map(
            (x) => `${x.loc?.filter((p) => p !== "body").join(".")}: ${x.msg}`,
          )
          .join("; ")
      : detail?.errors
          ?.map((x) =>
            typeof x === "string"
              ? x
              : `${x.field || x.code || ""} ${x.message || ""}`,
          )
          .join("; ");
    throw new Error(
      messages[detail?.code] ||
        fields ||
        (response.status === 401
          ? "Войдите в кабинет, чтобы продолжить."
          : `Не удалось выполнить действие (${detail?.code || response.status}).`),
    );
  }
  if (raw) return response.blob();
  return response.status === 204 ? null : response.json();
}
