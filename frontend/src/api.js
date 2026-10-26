import { fieldLabels, scoringFeatureLabels } from "./domain.js";

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
  EXTERNAL_LIABILITIES_READ_ONLY: "Платежи и долг в других банках можно изменить только в профиле бизнеса. Откройте заявку заново после изменения профиля.",
  INVALID_APPLICATION_STATE: "Действие недоступно в текущем статусе заявки.",
  SCORING_UNAVAILABLE: "Сервис ML-скоринга временно недоступен. Проверьте готовность моделей.",
  SCORING_BUSY: "Сервер занят расчётом оценок. Повторите попытку через несколько секунд.",
  SCORING_INVALID_INPUT: "Недостаточно данных в заявке для расчёта ML-оценки. Проверьте финансовые показатели.",
  SCORING_UNSUPPORTED_RANGE: "Параметры заявки выходят за допустимый диапазон модели.",
  SCORING_NO_CHANGED_FIELDS: "Для симуляции What-if измените хотя бы один показатель.",
  SCORING_MODEL_VERSION_UNAVAILABLE: "Версия модели изменилась. Запустите скоринг заново.",
  SCORING_SCOPE_REQUIRED: "Расчёт ML-скоринга доступен только клиенту для своей организации.",
  IDEMPOTENCY_KEY_REUSED: "Конфликт параметров повторного запроса. Повторите действие.",
};
export async function api(path, { method = "GET", body, headers = {}, raw = false } = {}) {
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body && !(body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...headers,
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
    const code = data?.code || (typeof data?.detail === "object" ? data?.detail?.code : null);
    const detail = data?.detail;
    const fieldError = (x) => {
      const key = String((x.loc || [x.field]).at(-1) ?? "").split(".").at(-1);
      if (key === "inn") return messages.INVALID_INN;
      const label = fieldLabels[key] || scoringFeatureLabels?.[key] || "Поле формы";
      if (key === "registration_date") return `${label}: укажите корректную дату не позднее сегодняшней.`;
      return x.message ? `${label}: ${x.message}` : `${label}: проверьте значение.`;
    };
    const errorList = Array.isArray(detail) ? detail : Array.isArray(data?.errors) ? data.errors : detail?.errors;
    const fields = errorList?.map((x) => typeof x === "string" ? x : fieldError(x)).join("; ");
    throw new Error(
      messages[code] ||
        fields ||
        (typeof detail === "string" ? detail : null) ||
        (response.status === 401
          ? "Войдите в кабинет, чтобы продолжить."
          : `Не удалось выполнить действие (${code || response.status}).`),
    );
  }
  if (raw) return response.blob();
  return response.status === 204 ? null : response.json();
}

export async function createScoringAssessment(applicationId, expectedVersion = null) {
  const idempotencyKey = crypto.randomUUID();
  const requestId = crypto.randomUUID();
  return api("/scoring/assessments", {
    method: "POST",
    headers: {
      "Idempotency-Key": idempotencyKey,
      "X-Request-ID": requestId,
    },
    body: {
      application_id: applicationId,
      ...(expectedVersion ? { expected_application_version: expectedVersion } : {}),
    },
  });
}

export async function getScoringAssessment(assessmentId, whatIfId = null) {
  const query = whatIfId ? `?what_if_id=${encodeURIComponent(whatIfId)}` : "";
  return api(`/scoring/assessments/${assessmentId}${query}`);
}

export async function createScoringWhatIf(assessmentId, changes) {
  const idempotencyKey = crypto.randomUUID();
  const requestId = crypto.randomUUID();
  return api(`/scoring/assessments/${assessmentId}/what-if`, {
    method: "POST",
    headers: {
      "Idempotency-Key": idempotencyKey,
      "X-Request-ID": requestId,
    },
    body: { changes },
  });
}
