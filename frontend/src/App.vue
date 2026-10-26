<script setup>
import {
  ref,
  reactive,
  computed,
  onMounted,
  onUnmounted,
  watch,
  nextTick,
} from "vue";
import Icon from "./components/Icon.vue";
import { applicationFinancials, draftData, draftFingerprint, externalFields, profileDifferences } from "./applicationForm.js";
import {
  api,
  setToken,
  createScoringAssessment,
  getScoringAssessment,
  createScoringWhatIf,
} from "./api";
import {
  validInn, fieldLabels, auditActions, factorLabels, discrepancyLabels, checkRows, reviewSummary,
  purposes,
  statuses,
  documentKinds,
  decisionReasons,
  money,
  date,
  payment,
  matches,
  emptyCompany,
  emptyFinancials,
  scoringFeatureLabels,
  creditHistoryLabels,
  formatFeatureValue,
} from "./domain";
const tabs = [
  { id: "home", name: "Главная", icon: "Home" },
  { id: "calculator", name: "Кредитный калькулятор", icon: "Calculator" },
  { id: "loans", name: "Мои кредиты", icon: "WalletCards" },
  { id: "assistant", name: "Чат с помощником", icon: "Sparkles" },
];
const page = ref(location.hash.slice(1) || "home"),
  user = ref(null),
  products = ref([]),
  applications = ref([]),
  loans = ref([]),
  feed = ref([]);
const loading = ref(false),
  busy = ref(false),
  error = ref(""),
  toast = ref(""),
  modal = ref(null),
  register = ref(false),
  search = ref(""),
  filter = ref("all");
const auth = reactive({ email: "", password: "" }),
  company = reactive(emptyCompany()),
  financials = reactive(emptyFinancials());
const calc = reactive({
    purpose: "working_capital",
    amount: 1500000,
    term: 24,
  }),
  selectedProduct = ref(null),
  preview = ref(null);
const current = ref(null),
  step = ref(1),
  confirmed = ref(false),
  comment = ref(""),
  syncProfile = ref(false),
  manualReview = ref(false),
  originalApplication = ref(null),
  signingCode = ref(""),
  requiredDocs = ref([]);
const drafts = ref([]), pendingProduct = ref(null), formPrefill = ref(null);
const draftSaving = ref(false), draftSaved = ref(false);
let draftTimer, draftSavePromise = null, draftHydrating = false, formEpoch = 0, draftNonce = "";
let formBaseline = "", lastSavedDraft = "";
const formFingerprint = computed(() => draftFingerprint(company, financials));
const obligations = computed(() => current.value?.credit_obligations || profile.value.credit_obligations || {});
const notifications = ref({ items: [], unread_count: 0 });
const notificationLoading = ref(false);
const contractUrl = ref("");
const contractLoading = ref(false);
let contractGeneration = 0;
const scoringAssessment = ref(null),
  scoringLoading = ref(false),
  scoringError = ref(""),
  whatIfResult = ref(null),
  whatIfLoading = ref(false),
  whatIfError = ref(""),
  activeScoringContext = ref(null);
const whatIfForm = reactive({
  annual_revenue: 1000000,
  loan_amount: 1000000,
  loan_term_months: 24,
  credit_history: "good",
  has_collateral: false,
  business_age_months: 24,
});
const chatBusy = ref(false), chatConversation = ref(null);
let chatGeneration = 0;
const chatInput = ref(""),
  chats = ref([
    {
      role: "assistant",
      text: "Здравствуйте! Я помогу разобраться в кредитовании бизнеса. Расскажите, для чего нужно финансирование, или выберите вопрос ниже.",
    },
  ]);
const isOfficer = computed(() => user.value?.role === "BANK_OFFICER");
const profile = ref({ company: {}, financials: {} });
const companyName = computed(
  () =>
    profile.value.company.name ||
    user.value?.companies?.[0]?.name ||
    "Ваш бизнес",
);
const available = computed(() =>
  products.value.filter((p) =>
    matches(p, calc.purpose, calc.amount, calc.term),
  ),
);
const submittedApplications = computed(() => applications.value.filter((a) => a.status !== "DRAFT"));
const latestCheck = computed(() => current.value?.checks?.filter((c) => c.data_revision === current.value.data_revision).at(-1));
const profileDiff = computed(() => profileDifferences(company, financials, profile.value, step.value));
const clarificationSummary = computed(() => {
  const before = originalApplication.value;
  if (!before) return "";
  const changed = ["company", "financials"].flatMap((group) =>
    Object.entries(group === "company" ? company : financials)
      .filter(([key, value]) => {
        if (group === "financials" && externalFields.includes(key)) return false;
        const old = before[group]?.[key];
        return typeof value === "boolean" ? value !== old :
          group === "financials" && key !== "credit_history" ? Number(value) !== Number(old) : String(value) !== String(old ?? "");
      }).map(([key]) => fieldLabels[key] || key));
  const docsChanged = JSON.stringify(before.documents.map((d) => d.id)) !== JSON.stringify(current.value.documents.map((d) => d.id));
  return [changed.length ? `Изменены сведения: ${changed.join(", ")}.` : "", docsChanged ? "Обновлены документы." : ""].filter(Boolean).join(" ") || "Сведения и документы проверены, подтверждаю их актуальность.";
});
const activeApplications = computed(() =>
  applications.value.filter(
    (a) => !["DRAFT", "DISBURSED", "REJECTED", "OFFER_DECLINED"].includes(a.status),
  ),
);
const attention = computed(() =>
  applications.value.filter((a) =>
    ["NEEDS_CLARIFICATION", "OFFER_READY", "SIGNING"].includes(a.status),
  ),
);
const filtered = computed(() =>
  applications.value.filter(
    (a) =>
      (filter.value === "all" ? a.status !== "DRAFT" : a.status === filter.value) &&
      `${a.company?.name} ${a.id} ${purposes[a.purpose]}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
);
const estimated = computed(() =>
  payment(calc.amount, available.value[0]?.annual_rate || 18, calc.term),
);
const previewTotal = computed(() => preview.value?.total_payment ?? preview.value?.schedule?.reduce((sum, row) => sum + Number(row.payment), 0) ?? 0);
const editable = computed(
  () =>
    current.value &&
    ["DRAFT", "NEEDS_CLARIFICATION"].includes(current.value.status),
);
const neededDocs = computed(() => [
  ...new Set([
    ...(current.value?.product_snapshot?.required_documents || []),
    ...requiredDocs.value,
  ]),
]);
let toastTimer;
function navigate(value) {
  page.value = tabs.some((t) => t.id === value) ? value : "home";
  location.hash = page.value;
  error.value = "";
}
function flash(text) {
  toast.value = text;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.value = "";
  }, 4500);
}
async function run(fn) {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    return await fn();
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
function askLogin() {
  modal.value = "auth";
  error.value = "";
}
async function refresh() {
  if (!user.value) return;
  const tasks = isOfficer.value
    ? [api("/bank/applications/queue?limit=100")]
    : [
        api("/client/applications?limit=100"),
        api("/client/loans?limit=100"),
        api("/client/feed"),
      ];
  tasks.push(api("/notifications"));
  const values = await Promise.all(tasks);
  notifications.value = values.at(-1);
  applications.value = values[0];
  if (!isOfficer.value) {
    loans.value = values[1];
    feed.value = values[2].items;
  }
}
async function openNotifications() {
  if (!user.value) return askLogin();
  modal.value = "notifications";
  await run(async () => { notifications.value = await api("/notifications"); });
}
async function markNotificationsRead(ids = [], all = false) {
  notifications.value = await api("/notifications/read", {
    method: "POST", body: { ids, all },
  });
}
async function readNotification(item) {
  await run(async () => {
    await markNotificationsRead([item.id]);
    await openApplication(item.application_id);
  });
}
async function moreNotifications() {
  notificationLoading.value = true;
  try {
    const next = await api(`/notifications?offset=${notifications.value.items.length}`);
    notifications.value = {
      unread_count: next.unread_count,
      items: [...notifications.value.items, ...next.items],
    };
  } catch (e) { error.value = e.message; }
  finally { notificationLoading.value = false; }
}
function releaseContract() {
  contractGeneration++;
  if (contractUrl.value) URL.revokeObjectURL(contractUrl.value);
  contractUrl.value = "";
  contractLoading.value = false;
}
async function loadContract() {
  releaseContract();
  if (!current.value?.contract) return;
  const generation = contractGeneration;
  contractLoading.value = true;
  try {
    const blob = await api(`/${isOfficer.value ? "bank" : "client"}/applications/${current.value.id}/contract/pdf`, { raw: true });
    if (generation === contractGeneration) contractUrl.value = URL.createObjectURL(blob);
  } catch (e) { if (generation === contractGeneration) error.value = e.message; }
  finally { if (generation === contractGeneration) contractLoading.value = false; }
}
watch(() => modal.value === "application" && current.value?.contract
  ? `${current.value.id}:${current.value.contract.sha256}` : null,
  (key) => key ? loadContract() : releaseContract());
onUnmounted(releaseContract);

async function loadSession() {
  user.value = await api("/auth/me");
  if (user.value.role === "ADMIN") {
    setToken("");
    user.value = null;
    throw new Error(
      "Этот кабинет предназначен для предпринимателей и кредитных сотрудников. Администрирование доступно через API и CLI backend.",
    );
  }
  if (!isOfficer.value) {
    const p = await api("/profile");
    profile.value = p;
    Object.assign(company, emptyCompany(), p.company);
    Object.assign(financials, emptyFinancials(), p.financials);
  }
  products.value = await api("/catalog/products?limit=100");
  await refresh();
}
async function authenticate() {
  await run(async () => {
    if (register.value)
      await api("/auth/register", { method: "POST", body: auth });
    const result = await api("/auth/login", { method: "POST", body: auth });
    setToken(result.access_token);
    await loadSession();
    auth.password = "";
    modal.value = null;
    flash("Вы вошли в кабинет");
  });
}
function logout() {
  setToken("");
  auth.email = "";
  auth.password = "";
  register.value = false;
  filter.value = "all";
  user.value = null;
  profile.value = { company: {}, financials: {} };
  products.value = [];
  applications.value = [];
  loans.value = [];
  feed.value = [];
  notifications.value = { items: [], unread_count: 0 };
  Object.assign(company, emptyCompany());
  Object.assign(financials, emptyFinancials());
  modal.value = null;
  current.value = null;
  formEpoch++;
  clearTimeout(draftTimer);
  drafts.value = [];
  navigate("home");
}
function openProfile() {
  Object.assign(company, emptyCompany(), profile.value.company);
  Object.assign(financials, emptyFinancials(), profile.value.financials);
  error.value = "";
  modal.value = "profile";
}
function financialPayload() {
  return {
    ...financials,
    ...Object.fromEntries(
      [
        "annual_revenue",
        "monthly_expenses",
        "monthly_debt_payments",
        "outstanding_debt",
      ].map((key) => [key, String(financials[key])]),
    ),
  };
}
async function saveProfile() {
  await run(async () => {
    if (!validInn(company.inn)) throw new Error("Проверьте ИНН: нужны 10 или 12 цифр с корректными контрольными цифрами.");
    profile.value = await api("/profile", {
      method: "PUT",
      body: {
        company: { ...company },
        financials: financials.annual_revenue ? financialPayload() : null,
        external_liabilities: Object.fromEntries(externalFields.map((key) => [key, String(financials[key] || "0")])),
      },
    });
    modal.value = null;
    flash("Профиль компании сохранён");
  });
}
async function calculate() {
  if (!user.value) return askLogin();
  await run(async () => {
    const p = selectedProduct.value || available.value[0];
    if (!p)
      throw new Error(
        "Нет продуктов для выбранных условий. Измените сумму или срок.",
      );
    preview.value = await api("/catalog/calculate-preview", {
      method: "POST",
      body: {
        product_id: p.id,
        amount: String(calc.amount),
        term_months: Number(calc.term),
      },
    });
    modal.value = "schedule";
  });
}
async function createApplication(product) {
  if (!user.value) return askLogin();
  await run(async () => {
    const p = product || available.value[0];
    if (!p) throw new Error("Сначала выберите подходящий кредитный продукт в калькуляторе.");
    const [freshProfile, savedDrafts, prefill] = await Promise.all([api("/profile"), api("/client/application-drafts"), api("/client/application-drafts/prefill")]);
    profile.value = freshProfile;
    drafts.value = savedDrafts;
    formPrefill.value = prefill;
    pendingProduct.value = p;
    if (savedDrafts.length) modal.value = "draft-choice";
    else await startNewForm(p);
  });
}
async function prepareForm(application) {
  formEpoch++;
  clearTimeout(draftTimer);
  draftHydrating = true;
  current.value = application;
  Object.assign(company, emptyCompany(), application.company);
  Object.assign(financials, emptyFinancials(), application.financials);
  if (!isOfficer.value && ["DRAFT", "NEEDS_CLARIFICATION"].includes(application.status)) {
    for (const key of externalFields) financials[key] = profile.value.financials[key] || "0";
  }
  requiredDocs.value = application.clarifications?.filter((c) => !c.responded_at).flatMap((c) => c.required_documents) || [];
  originalApplication.value = JSON.parse(JSON.stringify(application));
  syncProfile.value = false;
  manualReview.value = false;
  step.value = 1;
  confirmed.value = false;
  comment.value = latestCheck.value ? reviewSummary(latestCheck.value.results) : "";
  signingCode.value = "";
  draftNonce = application.id || crypto.randomUUID();
  modal.value = "application";
  scoringAssessment.value = null;
  whatIfResult.value = null;
  scoringError.value = "";
  whatIfError.value = "";
  if (application.id && !isOfficer.value) {
    const lastScoring = application.history?.filter((e) => e.action === "scoring.assessment").at(-1);
    if (lastScoring?.details?.resource_id) {
      loadSavedScoring(lastScoring.details.resource_id);
    }
  }
  await nextTick();
  formBaseline = lastSavedDraft = formFingerprint.value;
  draftSaved.value = !!application.id;
  draftHydrating = false;
}
function initWhatIfFromAssessment(assessment) {
  const factors = assessment?.explanation?.factors || [];
  const getVal = (feat) => factors.find((f) => f.feature === feat)?.input_value;
  whatIfForm.annual_revenue = Number(getVal("annual_revenue") ?? current.value?.financials?.annual_revenue ?? 1000000);
  whatIfForm.loan_amount = Number(getVal("loan_amount") ?? current.value?.amount ?? 1000000);
  whatIfForm.loan_term_months = Number(getVal("loan_term_months") ?? current.value?.term_months ?? 24);
  whatIfForm.credit_history = getVal("credit_history") ?? current.value?.financials?.credit_history ?? "good";
  whatIfForm.has_collateral = Boolean(getVal("has_collateral") ?? current.value?.financials?.has_collateral ?? false);
  whatIfForm.business_age_months = Number(getVal("business_age_months") ?? 24);
}
async function loadSavedScoring(assessmentId) {
  scoringLoading.value = true;
  scoringError.value = "";
  try {
    const res = await getScoringAssessment(assessmentId);
    scoringAssessment.value = res;
    initWhatIfFromAssessment(res);
    activeScoringContext.value = {
      assessment_id: res.assessment_id,
      display_percent: res.score?.display_percent,
      application_id: current.value?.id,
      what_if_id: null,
    };
  } catch (e) {
    scoringError.value = e.message;
  } finally {
    scoringLoading.value = false;
  }
}
async function runScoring() {
  if (!current.value?.id) return;
  scoringLoading.value = true;
  scoringError.value = "";
  whatIfResult.value = null;
  whatIfError.value = "";
  try {
    const res = await createScoringAssessment(current.value.id, current.value.version);
    scoringAssessment.value = res;
    initWhatIfFromAssessment(res);
    activeScoringContext.value = {
      assessment_id: res.assessment_id,
      display_percent: res.score?.display_percent,
      application_id: current.value.id,
      what_if_id: null,
    };
    flash("Кредитный рейтинг успешно рассчитан");
    await reloadCurrent();
  } catch (e) {
    scoringError.value = e.message;
  } finally {
    scoringLoading.value = false;
  }
}
async function runWhatIf() {
  if (!scoringAssessment.value?.assessment_id) return;
  whatIfLoading.value = true;
  whatIfError.value = "";
  try {
    const originalFactors = scoringAssessment.value.explanation?.factors || [];
    const getOrig = (feat) => originalFactors.find((f) => f.feature === feat)?.input_value;
    const changes = {};
    if (Number(whatIfForm.annual_revenue) !== Number(getOrig("annual_revenue"))) {
      changes.annual_revenue = Number(whatIfForm.annual_revenue);
    }
    if (Number(whatIfForm.loan_amount) !== Number(getOrig("loan_amount"))) {
      changes.loan_amount = Number(whatIfForm.loan_amount);
    }
    if (Number(whatIfForm.loan_term_months) !== Number(getOrig("loan_term_months"))) {
      changes.loan_term_months = Number(whatIfForm.loan_term_months);
    }
    if (whatIfForm.credit_history !== getOrig("credit_history")) {
      changes.credit_history = whatIfForm.credit_history;
    }
    if (Boolean(whatIfForm.has_collateral) !== Boolean(getOrig("has_collateral"))) {
      changes.has_collateral = Boolean(whatIfForm.has_collateral);
    }
    if (Number(whatIfForm.business_age_months) !== Number(getOrig("business_age_months"))) {
      changes.business_age_months = Number(whatIfForm.business_age_months);
    }
    if (!Object.keys(changes).length) {
      throw new Error("Измените хотя бы один показатель для симуляции What-if.");
    }
    const res = await createScoringWhatIf(scoringAssessment.value.assessment_id, changes);
    whatIfResult.value = res;
    if (activeScoringContext.value) {
      activeScoringContext.value.what_if_id = res.what_if_id;
    }
    flash("Симуляция What-if рассчитана");
  } catch (e) {
    whatIfError.value = e.message;
  } finally {
    whatIfLoading.value = false;
  }
}
async function askAiAboutScoring(mode = "explain") {
  const aid = scoringAssessment.value?.assessment_id || activeScoringContext.value?.assessment_id;
  if (!aid) return;
  const percent = scoringAssessment.value?.score?.display_percent?.toFixed(1) ||
    activeScoringContext.value?.display_percent?.toFixed(1) || "";
  let query = "";
  if (mode === "explain") {
    query = `Почему моя ML-оценка ${aid} равна ${percent}%? Какие факторы больше всего повлияли?`;
  } else if (mode === "improve") {
    query = `Что можно изменить в параметрах заявки, чтобы повысить кредитный рейтинг по оценке ${aid}?`;
  } else if (mode === "what_if") {
    const wid = whatIfResult.value?.what_if_id || activeScoringContext.value?.what_if_id;
    if (wid) {
      const delta = whatIfResult.value ? (whatIfResult.value.delta_percentage_points > 0 ? `+${whatIfResult.value.delta_percentage_points.toFixed(1)}` : whatIfResult.value.delta_percentage_points.toFixed(1)) : "";
      query = `Что изменилось в сохранённом What-if оценки ${aid} и симуляции ${wid}? ${delta ? 'Почему дельта составила ' + delta + ' процентных пункта?' : ''}`.trim();
    }
  } else if (typeof mode === "string" && mode.startsWith("factor:")) {
    const featureName = mode.split(":")[1];
    const label = scoringFeatureLabels[featureName] || featureName;
    query = `Объясни, как фактор "${label}" повлиял на мою ML-оценку ${aid} и что означает его вклад в logit?`;
  }
  if (query) {
    modal.value = null;
    navigate("assistant");
    await nextTick();
    await assistant(query);
  }
}
async function startNewForm(product) {
  await prepareForm({
    id: null, status: "DRAFT", version: null, product_id: product.id,
    product_snapshot: product, purpose: calc.purpose, amount: String(calc.amount),
    term_months: Number(calc.term), company: { ...formPrefill.value.company },
    financials: { ...formPrefill.value.financials }, source_loan_id: formPrefill.value.source_loan_id,
    documents: [], checks: [], clarifications: [], history: [],
    credit_obligations: formPrefill.value.credit_obligations,
  });
}
async function openApplication(id) {
  error.value = "";
  const [application, freshProfile] = await Promise.all([
    api(isOfficer.value ? `/bank/applications/${id}/dossier` : `/client/applications/${id}`),
    isOfficer.value ? null : api("/profile"),
  ]);
  if (freshProfile) profile.value = freshProfile;
  await prepareForm(application);
}
async function persistDraft(force = false) {
  clearTimeout(draftTimer);
  if (!current.value || current.value.status !== "DRAFT") return;
  if (draftSavePromise) {
    await draftSavePromise;
    return persistDraft(force);
  }
  const epoch = formEpoch;
  const fingerprint = formFingerprint.value;
  if ((!current.value.id && !force && fingerprint === formBaseline) ||
      (current.value.id && fingerprint === lastSavedDraft)) return;
  const payload = draftData(company, financials);
  const application = current.value;
  draftSaving.value = true;
  draftSavePromise = (async () => {
    let result = application;
    if (!result.id) result = await api("/client/application-drafts", {
      method: "POST", body: {
        draft_id: draftNonce, product_id: application.product_id, purpose: application.purpose,
        source_loan_id: application.source_loan_id || null,
        amount: application.amount, term_months: application.term_months, ...payload,
      },
    });
    result = await api(`/client/application-drafts/${result.id}`, {
      method: "PUT", body: { expected_version: result.version, ...payload },
    });
    if (epoch === formEpoch) {
      current.value = result;
      lastSavedDraft = fingerprint;
      draftSaved.value = true;
    }
  })();
  try { await draftSavePromise; }
  finally { draftSavePromise = null; draftSaving.value = false; }
  if (epoch === formEpoch && formFingerprint.value !== lastSavedDraft) await persistDraft(force);
}
watch(formFingerprint, () => {
  if (draftHydrating || modal.value !== "application" || current.value?.status !== "DRAFT") return;
  draftSaved.value = false;
  clearTimeout(draftTimer);
  draftTimer = setTimeout(() => persistDraft().catch((e) => { error.value = e.message; }), 650);
});
async function closeModal() {
  if (busy.value) return;
  if (modal.value === "application" && current.value?.status === "DRAFT") {
    let saved = false;
    await run(async () => { await persistDraft(); saved = true; });
    if (!saved) return;
  }
  modal.value = null;
}
onUnmounted(() => { clearTimeout(draftTimer); formEpoch++; });
async function reloadCurrent() {
  current.value = await api(
    isOfficer.value
      ? `/bank/applications/${current.value.id}/dossier`
      : `/client/applications/${current.value.id}`,
  );
  await refresh();
}
async function saveDraft(section) {
  if (current.value.status === "DRAFT") return persistDraft();
  await api(`/client/applications/${current.value.id}`, {
    method: "PUT", body: {
      expected_version: current.value.version,
      ...(section !== "financials" ? { company: { ...company } } : {}),
      ...(section !== "company" ? { financials: applicationFinancials(financials, profile.value.financials) } : {}),
    },
  });
  await reloadCurrent();
}
async function nextStep() {
  await run(async () => {
    if (step.value === 1 && !validInn(company.inn)) throw new Error("Проверьте ИНН: нужны 10 или 12 цифр с корректными контрольными цифрами.");
    await api("/client/application-drafts/validate", {
      method: "POST", body: step.value === 1
        ? { company: { ...company } }
        : { financials: applicationFinancials(financials, profile.value.financials) },
    });
    await saveDraft(step.value === 1 ? "company" : "financials");
    step.value++;
  });
}
async function submitApplication() {
  await run(async () => {
    if (current.value.status === "DRAFT") await persistDraft(true);
    await api(`/client/applications/${current.value.id}`, {
      method: "PUT", body: { expected_version: current.value.version,
        company: { ...company }, financials: applicationFinancials(financials, profile.value.financials) },
    });
    await reloadCurrent();
    if (syncProfile.value) {
      await api(`/client/applications/${current.value.id}/sync-profile`, {
        method: "POST", body: { expected_version: current.value.version },
      });
      profile.value = await api("/profile");
    }
    const clarification = current.value.status === "NEEDS_CLARIFICATION";
    await api(
      `/client/applications/${current.value.id}/${clarification ? "clarify" : "submit"}`,
      {
        method: "POST",
        body: {
          expected_version: current.value.version,
          confirmed: confirmed.value,
          ...(clarification ? { response: [clarificationSummary.value, comment.value.trim()].filter(Boolean).join("\n\n") } : {}),
        },
      },
    );
    await reloadCurrent();
    flash("Заявка отправлена на рассмотрение");
  });
}
async function upload(event, kind) {
  const file = event.target.files[0];
  if (!file) return;
  await run(async () => {
    if (
      !["application/pdf", "image/png", "image/jpeg"].includes(file.type) ||
      file.size > 10485760
    )
      throw new Error("Выберите PDF, PNG или JPEG размером до 10 МБ.");
    if (current.value.status === "DRAFT") await persistDraft(true);
    const body = new FormData();
    body.append("kind", kind);
    body.append("expected_version", current.value.version);
    body.append("file", file);
    await api(`/client/applications/${current.value.id}/documents`, {
      method: "POST",
      body,
    });
    await reloadCurrent();
    flash("Документ загружен");
  });
  event.target.value = "";
}
async function removeDocument(doc) {
  await run(async () => {
    await api(
      `/client/applications/${current.value.id}/documents/${doc.id}?expected_version=${current.value.version}`,
      { method: "DELETE" },
    );
    await reloadCurrent();
  });
}
async function download(doc) {
  await run(async () => {
    const blob = await api(
      `/${isOfficer.value ? "bank" : "client"}/applications/${current.value.id}/documents/${doc.id}`,
      { raw: true },
    );
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = doc.filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}
async function action(name) {
  await run(async () => {
    const body = { expected_version: current.value.version };
    if (
      [
        "request-clarification",
        "reject-primary",
        "pass-to-auto-analysis",
      ].includes(name)
    )
      body.comment = comment.value;
    if (name === "request-clarification") {
      body.required_documents = requiredDocs.value;
      body.required_fields = [];
    }
    if (name === "sign") {
      body.code = signingCode.value;
      body.contract_sha256 = current.value.contract.sha256;
    }
    await api(
      `/${isOfficer.value ? "bank" : "client"}/applications/${current.value.id}/${name}`,
      { method: "POST", body },
    );
    await reloadCurrent();
    if (name === "run-external-checks" && latestCheck.value) comment.value = reviewSummary(latestCheck.value.results);
    flash("Статус заявки обновлён");
  });
}
function showSchedule(offer) {
  preview.value = offer;
  modal.value = "schedule";
}
function resetChat() {
  chatGeneration++;
  chatBusy.value = false;
  chatConversation.value = null;
  chats.value = [chats.value[0]];
  if (user.value) sessionStorage.removeItem(`credit-chat-${user.value.id}`);
}
async function pollChat(requestId, generation) {
  chatBusy.value = true;
  try {
    while (generation === chatGeneration) {
      const job = await api(`/chat/requests/${requestId}`);
      if (generation !== chatGeneration) return;
      if (job.result) {
        chats.value.push({ role: "assistant", text: job.result.answer });
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  } catch (e) {
    if (generation === chatGeneration) error.value = e.message;
  } finally {
    if (generation === chatGeneration) chatBusy.value = false;
  }
}
async function assistant(text = chatInput.value) {
  if (!text.trim() || chatBusy.value) return;
  if (!user.value) {
    error.value = "Войдите в кабинет, чтобы обратиться к AI-помощнику.";
    return;
  }
  const generation = chatGeneration;
  chatBusy.value = true;
  try {
    if (!chatConversation.value) {
      const created = await api("/chat/conversations", { method: "POST" });
      if (generation !== chatGeneration) return;
      chatConversation.value = created.conversation_id;
      sessionStorage.setItem(`credit-chat-${user.value.id}`, chatConversation.value);
    }
    const requestId = crypto.randomUUID();
    const job = await api(`/chat/conversations/${chatConversation.value}/messages`, {
      method: "POST", body: { request_id: requestId, message: text.trim() },
    });
    if (generation !== chatGeneration) return;
    chats.value.push({ role: "user", text: job.message });
    chatInput.value = "";
    await pollChat(requestId, generation);
  } catch (e) {
    if (generation === chatGeneration) error.value = e.message;
  } finally {
    if (generation === chatGeneration) chatBusy.value = false;
  }
}
watch(() => user.value?.id, async (id) => {
  chatGeneration++;
  const generation = chatGeneration;
  chatBusy.value = false;
  chats.value = [chats.value[0]];
  chatConversation.value = id ? sessionStorage.getItem(`credit-chat-${id}`) : null;
  if (!chatConversation.value) return;
  try {
    const jobs = await api(`/chat/conversations/${chatConversation.value}/messages`);
    if (generation !== chatGeneration) return;
    for (const job of jobs) {
      chats.value.push({ role: "user", text: job.message });
      if (job.result) chats.value.push({ role: "assistant", text: job.result.answer });
    }
    const pending = jobs.find((job) => !job.result);
    if (pending) await pollChat(pending.request_id, generation);
  } catch (e) {
    if (generation === chatGeneration) error.value = e.message;
  }
});
onUnmounted(() => { chatGeneration++; });

function onHash() {
  const next = location.hash.slice(1);
  page.value = tabs.some((t) => t.id === next) ? next : "home";
}
let previousFocus;
watch(modal, async (value, old) => {
  if (value && !old) previousFocus = document.activeElement;
  document.body.style.overflow = value ? "hidden" : "";
  await nextTick();
  if (value)
    document
      .querySelector('.modal input:not([type="file"]), .modal button')
      ?.focus();
  else previousFocus?.focus();
});
function onKey(e) {
  if (e.key === "Escape") closeModal();
  if (e.key === "Tab" && modal.value) {
    const nodes = [
      ...document.querySelectorAll(
        ".modal button:not(:disabled), .modal input:not(:disabled), .modal select, .modal textarea, .modal summary",
      ),
    ].filter((node) => node.getClientRects().length);
    const first = nodes[0],
      last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last?.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first?.focus();
    }
  }
}
function expired() {
  logout();
  askLogin();
  error.value = "Сессия истекла. Войдите снова.";
}
onMounted(async () => {
  window.addEventListener("hashchange", onHash);
  window.addEventListener("keydown", onKey);
  window.addEventListener("credit-session-expired", expired);
  if (sessionStorage.getItem("credit-token")) {
    loading.value = true;
    try {
      await loadSession();
    } catch (e) {
      error.value = e.message;
      setToken("");
      user.value = null;
    } finally {
      loading.value = false;
    }
  }
});
onUnmounted(() => {
  clearTimeout(toastTimer);
  document.body.style.overflow = "";
  window.removeEventListener("hashchange", onHash);
  window.removeEventListener("keydown", onKey);
  window.removeEventListener("credit-session-expired", expired);
});
</script>

<template>
  <div class="app-shell">
    <header class="header">
      <button
        class="brand"
        @click="navigate('home')"
        aria-label="Альфа-Бизнес, главная"
      >
        <span class="alfa-mark">А<span></span></span
        ><span>альфа<span class="brand-light">бизнес</span></span>
      </button>
      <span class="header-divider"></span
      ><span class="header-caption">Кредитный кабинет</span>
      <div class="header-right">
        <span class="secure"
          ><Icon name="ShieldCheck" :size="15" /> Защищённое соединение</span
        ><button
          class="icon-btn notification"
          :disabled="loading || busy"
          :aria-label="`Уведомления${notifications.unread_count ? ': непрочитанных ' + notifications.unread_count : ''}`"
          @click="openNotifications"
        >
          <Icon name="Bell" /><i v-if="notifications.unread_count"></i></button>
        <button class="profile-btn" @click="user ? openProfile() : askLogin()">
          <span class="avatar">{{ user ? companyName.slice(0, 1) : "Б" }}</span
          ><span>{{
            user
              ? isOfficer
                ? "Сотрудник банка"
                : companyName
              : "Личный кабинет"
          }}</span
          ><Icon name="ChevronDown" :size="15" />
        </button>
      </div>
    </header>
    <nav class="navigation" aria-label="Главная навигация">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :class="{ active: page === tab.id }"
        @click="navigate(tab.id)"
      >
        <Icon :name="tab.icon" :size="18" />{{
          tab.id === "loans" && isOfficer ? "Очередь заявок" : tab.name
        }}<span v-if="tab.id === 'assistant'" class="new-label">AI</span
        ><span
          v-if="tab.id === 'loans' && attention.length"
          class="nav-count"
          >{{ attention.length }}</span
        >
      </button>
    </nav>
    <main>
      <div v-if="error && !modal" class="alert error" role="alert">
        {{ error
        }}<button
          class="icon-btn"
          aria-label="Закрыть ошибку"
          @click="error = ''"
        >
          <Icon name="X" :size="16" />
        </button>
      </div>
      <div v-if="loading" class="loading">Загружаем ваш кабинет…</div>
      <template v-else-if="page === 'home'">
        <div class="page-heading">
          <div>
            <div class="eyebrow">БОЛЬШЕ ВОЗМОЖНОСТЕЙ ДЛЯ ВАШЕГО ДЕЛА</div>
            <h1>
              {{ user ? "Хороший день для роста" : "Ваш бизнес. Новый уровень"
              }}<span class="red-dot">.</span>
            </h1>
            <p>Финансирование, которое помогает двигаться вперёд.</p>
          </div>
          <span class="date-chip"
            ><span class="live-dot"></span> Всё под контролем</span
          >
        </div>
        <section class="hero">
          <div class="hero-copy">
            <span class="tag"
              ><span class="live-dot"></span> КРЕДИТЫ ДЛЯ БИЗНЕСА</span
            >
            <h2>Ваши планы.<br />Наша поддержка.</h2>
            <p>
              На новые идеи, большие заказы<br />и следующий шаг в развитии
              бизнеса.
            </p>
            <button class="primary" @click="navigate('calculator')">
              Подобрать кредит <Icon name="ArrowUpRight" :size="19" />
            </button>
            <div class="hero-note">
              <Icon name="ShieldCheck" :size="14" /> Онлайн. Без визита в
              отделение.
            </div>
          </div>
          <div class="hero-art" aria-hidden="true">
            <div class="orbit orbit-one"></div>
            <div class="orbit orbit-two"></div>
            <div class="art-grid"></div>
            <div class="glass-card">
              <span class="card-brand">А<span>БИЗНЕС</span></span>
              <div class="chip"></div>
              <span class="card-number">•••• &nbsp; •••• &nbsp; 2026</span>
              <div class="card-bottom">
                <span>БОЛЬШЕ ВОЗМОЖНОСТЕЙ</span
                ><Icon name="ArrowUpRight" :size="28" />
              </div>
            </div>
            <div class="growth-block">
              <Icon name="TrendingUp" :size="44" />
            </div>
            <div class="art-caption">
              <span class="live-dot"></span> Инвестиции в ваше будущее
            </div>
            <span class="floating-plus plus-one">+</span
            ><span class="floating-plus plus-two">+</span>
          </div>
        </section>
        <section class="quick-grid">
          <button @click="navigate('calculator')">
            <span class="quick-icon red"
              ><Icon name="Calculator" :size="23" /></span
            ><span
              ><strong>Рассчитать кредит</strong
              ><small>Подберите комфортный платёж</small></span
            ><Icon name="ArrowUpRight" :size="20" /></button
          ><button @click="navigate('loans')">
            <span class="quick-icon purple"
              ><Icon name="WalletCards" :size="23" /></span
            ><span
              ><strong>{{ isOfficer ? "Очередь заявок" : "Мои заявки" }}</strong
              ><small>{{
                user
                  ? `${activeApplications.length} в работе`
                  : "Весь процесс — в одном месте"
              }}</small></span
            ><Icon name="ArrowUpRight" :size="20" /></button
          ><button @click="navigate('assistant')">
            <span class="quick-icon green"
              ><Icon name="Sparkles" :size="23" /></span
            ><span
              ><strong>Помощник для бизнеса</strong
              ><small>Ответы на вопросы о кредитах</small></span
            ><Icon name="ArrowUpRight" :size="20" />
          </button>
        </section>
        <section class="dashboard-grid">
          <div class="panel applications-panel">
            <div class="section-heading">
              <h2>
                {{ isOfficer ? "Заявки на обработку" : "Мои заявки" }}
                <span class="count">{{ submittedApplications.length }}</span>
              </h2>
              <button class="text-btn" @click="navigate('loans')">
                Все заявки <Icon name="ArrowRight" :size="17" />
              </button>
            </div>
            <template v-if="submittedApplications.length"
              ><button
                v-for="a in submittedApplications.slice(0, 3)"
                :key="a.id"
                class="application-row"
                @click="run(() => openApplication(a.id))"
              >
                <span class="document-icon"><Icon name="FileText" /></span
                ><span class="row-main"
                  ><strong>{{ purposes[a.purpose] }}</strong
                  ><small
                    >№ {{ a.id.slice(0, 8).toUpperCase() }} ·
                    {{ date(a.created_at) }}</small
                  ></span
                ><span class="row-end"
                  ><strong>{{ money(a.amount) }}</strong
                  ><span :class="['status', a.status]">{{
                    statuses[a.status]
                  }}</span></span
                ><Icon name="ChevronRight" :size="18" /></button
            ></template>
            <div v-else class="empty-state">
              <span class="empty-illustration"
                ><Icon name="FileText" :size="34" /><span>+</span></span
              >
              <h3>Большие планы начинаются с заявки</h3>
              <p>
                Подберите финансирование под задачи бизнеса.<br />Мы будем рядом
                на каждом этапе.
              </p>
              <button class="secondary" @click="navigate('calculator')">
                Подобрать кредит <Icon name="Plus" :size="17" />
              </button>
            </div>
            <div class="panel-foot">
              <Icon name="ShieldCheck" :size="16" /> Данные компании заполнятся
              автоматически из профиля
            </div>
          </div>
          <aside class="panel steps-panel">
            <span class="mini-label">ВСЁ ПРОЩЕ, ЧЕМ КАЖЕТСЯ</span>
            <h2>От идеи до<br />финансирования</h2>
            <div
              v-for="(s, i) in [
                ['Выберите условия', 'Сумма, срок и цель кредита'],
                ['Заполните заявку', 'Данные бизнеса и документы'],
                ['Получите решение', 'Отслеживайте статус онлайн'],
              ]"
              :key="s[0]"
              class="process-step"
            >
              <span>{{ String(i + 1).padStart(2, "0") }}</span>
              <div>
                <strong>{{ s[0] }}</strong>
                <p>{{ s[1] }}</p>
              </div>
            </div>
            <button class="text-btn" @click="navigate('assistant')">
              Помочь разобраться? <Icon name="ArrowUpRight" :size="17" />
            </button>
          </aside>
        </section>
        <section class="insights">
          <div class="section-heading">
            <h2>Полезно для вашего дела</h2>
            <span class="muted small">РАЗВИВАЕМ БИЗНЕС ВМЕСТЕ</span>
          </div>
          <div class="insight-grid">
            <button
              class="insight-card"
              @click="
                navigate('assistant');
                assistant('Какие документы нужны для кредита?');
              "
            >
              <span class="article-icon lavender"
                ><Icon name="FileText" :size="28"
              /></span>
              <div>
                <span class="mini-label">ПОДГОТОВКА</span>
                <h3>
                  {{ feed[0]?.title || "Какие документы нужны для кредита" }}
                </h3>
                <p>
                  {{
                    feed[0]?.text || "Собрали всё необходимое в одном списке"
                  }}
                </p>
              </div>
              <Icon name="ArrowUpRight" /></button
            ><button class="insight-card" @click="navigate('calculator')">
              <span class="article-icon peach"
                ><Icon name="TrendingUp" :size="28"
              /></span>
              <div>
                <span class="mini-label">ВОЗМОЖНОСТИ</span>
                <h3>Планы на рост? Посчитаем вместе</h3>
                <p>Узнайте предварительный платёж за пару минут</p>
              </div>
              <Icon name="ArrowUpRight" />
            </button>
          </div>
        </section>
      </template>
      <template v-else-if="page === 'calculator'">
        <div class="page-heading">
          <div>
            <div class="eyebrow">ФИНАНСИРОВАНИЕ ПОД ВАШИ ЗАДАЧИ</div>
            <h1>Кредитный калькулятор</h1>
            <p>Найдите баланс между возможностями и планами.</p>
          </div>
        </div>
        <section class="calculator-layout">
          <form class="panel calculator-form" @submit.prevent="calculate">
            <h2>Что нужно вашему бизнесу?</h2>
            <label
              >Цель кредита<select
                v-model="calc.purpose"
                @change="selectedProduct = null"
              >
                <option
                  v-for="(label, key) in purposes"
                  :key="key"
                  :value="key"
                >
                  {{ label }}
                </option>
              </select></label
            ><label
              >Сумма кредита <span class="input-unit">₽</span
              ><input
                v-model="calc.amount"
                type="number"
                min="10000"
                max="1000000000"
                step="1000"
                required
                @input="selectedProduct = null" /></label
            ><input
              v-model="calc.amount"
              class="range"
              aria-label="Сумма кредита, ползунок"
              type="range"
              min="100000"
              max="10000000"
              step="50000"
            />
            <div class="range-labels">
              <span>100 тыс. ₽</span><span>10 млн ₽</span>
            </div>
            <label
              >Срок кредита <span class="input-unit">месяцев</span
              ><input
                v-model="calc.term"
                type="number"
                min="1"
                max="360"
                required
                @input="selectedProduct = null" /></label
            ><input
              v-model="calc.term"
              class="range"
              aria-label="Срок кредита, ползунок"
              type="range"
              min="6"
              max="60"
              step="6"
            />
            <div class="range-labels">
              <span>6 месяцев</span><span>5 лет</span>
            </div>
            <button class="text-btn" type="submit" :disabled="busy">
              <Icon name="FileText" :size="17" /> Посмотреть график платежей
            </button>
          </form>
          <aside class="panel calculation-result">
            <span class="mini-label">ПРЕДВАРИТЕЛЬНЫЙ РАСЧЁТ</span>
            <p>Ежемесячный платёж</p>
            <div class="big-number">{{ money(estimated) }}</div>
            <div class="result-line">
              <span>Сумма кредита</span
              ><strong>{{ money(calc.amount) }}</strong>
            </div>
            <div class="result-line">
              <span>Срок</span><strong>{{ calc.term }} мес.</strong>
            </div>
            <div class="result-line">
              <span>Базовая ставка</span
              ><strong>{{ available[0]?.annual_rate || 18 }}% годовых</strong>
            </div>
            <div class="result-line"><span>Переплата по процентам</span><strong>{{ money(estimated * Number(calc.term) - Number(calc.amount)) }}</strong></div>
            <div class="result-line"><span>Общая сумма выплат</span><strong>{{ money(estimated * Number(calc.term)) }}</strong></div>
            <button
              class="primary full"
              :disabled="
                busy ||
                isOfficer ||
                (user && !available.length) ||
                !Number(calc.amount) ||
                !Number(calc.term)
              "
              @click="createApplication()"
            >
              Оформить заявку <Icon name="ArrowRight" :size="18" /></button
            ><small
              >Расчёт предварительный. Итоговые условия будут доступны после
              рассмотрения заявки. Учебный сервис.</small
            >
          </aside>
        </section>
        <section class="product-section">
          <div class="section-heading">
            <h2>
              Подходящие продукты
              <span class="count">{{ available.length }}</span>
            </h2>
            <button v-if="!user" class="text-btn" @click="askLogin">
              Войти для подбора <Icon name="ArrowRight" :size="17" />
            </button>
          </div>
          <div v-if="!available.length" class="panel compact-empty">
            <Icon name="Search" />
            <p>
              {{
                user
                  ? "По этим условиям продукты не найдены. Попробуйте изменить сумму или срок."
                  : "Войдите в кабинет, чтобы увидеть актуальный каталог банка и отправить заявку."
              }}
            </p>
          </div>
          <div v-else class="product-grid">
            <article
              v-for="p in available"
              :key="p.id"
              class="panel product-card"
            >
              <span class="tag">ДЛЯ ВАШЕГО БИЗНЕСА</span>
              <h2>{{ p.name.replace("Демо: ", "") }}</h2>
              <p>
                {{
                  p.collateral_required
                    ? "С обеспечением"
                    : "Без обязательного залога"
                }}
              </p>
              <div class="product-numbers">
                <div>
                  <small>Ставка от</small><strong>{{ p.annual_rate }}%</strong>
                </div>
                <div>
                  <small>До</small><strong>{{ money(p.max_amount) }}</strong>
                </div>
              </div>
              <button
                class="secondary full"
                :disabled="busy || isOfficer"
                @click="createApplication(p)"
              >
                Выбрать продукт <Icon name="ArrowUpRight" :size="18" />
              </button>
            </article>
          </div>
        </section>
      </template>
      <template v-else-if="page === 'loans'">
        <div class="page-heading">
          <div>
            <div class="eyebrow">ВАШЕ ФИНАНСИРОВАНИЕ</div>
            <h1>{{ isOfficer ? "Очередь заявок" : "Мои кредиты и заявки" }}</h1>
            <p>
              {{
                isOfficer
                  ? "Проверяйте сведения, запрашивайте уточнения и запускайте анализ."
                  : "От первой заявки до последнего шага — всё здесь."
              }}
            </p>
          </div>
          <button
            v-if="!isOfficer"
            class="primary"
            @click="navigate('calculator')"
          >
            <Icon name="Plus" :size="18" /> Новая заявка</button
          ><button
            v-else
            class="secondary"
            :disabled="busy"
            @click="run(refresh)"
          >
            <Icon name="RefreshCw" :size="18" /> Обновить
          </button>
        </div>
        <div v-if="!user" class="panel empty-state">
          <Icon name="WalletCards" :size="40" />
          <h2>Ваши кредиты в одном месте</h2>
          <p>Войдите, чтобы увидеть заявки и историю финансирования.</p>
          <button class="primary" @click="askLogin">Войти в кабинет</button>
        </div>
        <template v-else
          ><div class="loan-summary">
            <div class="panel">
              <span>Заявок в работе</span
              ><strong>{{ activeApplications.length }}</strong
              ><Icon name="FileText" />
            </div>
            <div class="panel">
              <span>Требуют внимания</span
              ><strong>{{ attention.length }}</strong
              ><Icon name="Bell" />
            </div>
            <div class="panel">
              <span>{{
                isOfficer ? "Всего заявок" : "Остаток по кредитам"
              }}</span
              ><strong>{{
                isOfficer
                  ? applications.length
                  : money(
                      loans.reduce(
                        (sum, l) => sum + Number(l.outstanding_balance),
                        0,
                      ),
                    )
              }}</strong
              ><Icon name="WalletCards" />
            </div>
          </div>
          <section class="panel list-panel">
            <div class="list-toolbar">
              <h2>Заявки</h2>
              <div>
                <label class="search-input"
                  ><Icon name="Search" :size="17" /><input
                    v-model="search"
                    placeholder="Найти заявку"
                    aria-label="Поиск заявки" /></label
                ><select v-model="filter" aria-label="Статус заявки">
                  <option value="all">Отправленные заявки</option>
                  <option
                    v-for="(label, key) in Object.fromEntries(Object.entries(statuses).filter(([key]) => key !== 'DRAFT'))"
                    :key="key"
                    :value="key"
                  >
                    {{ label }}
                  </option></select
                ><button
                  class="icon-btn"
                  aria-label="Обновить заявки"
                  :disabled="busy"
                  @click="run(refresh)"
                >
                  <Icon name="RefreshCw" :size="18" />
                </button>
              </div>
            </div>
            <div class="table-scroll">
              <table v-if="filtered.length">
                <thead>
                  <tr>
                    <th>Заявка / цель</th>
                    <th>Сумма</th>
                    <th>Срок</th>
                    <th>Статус</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="a in filtered"
                    :key="a.id"
                    @click="run(() => openApplication(a.id))"
                  >
                    <td>
                      <strong>{{
                        isOfficer
                          ? a.company?.name || "Новая компания"
                          : purposes[a.purpose]
                      }}</strong
                      ><small
                        >№ {{ a.id.slice(0, 8).toUpperCase() }} ·
                        {{ date(a.created_at) }}</small
                      >
                    </td>
                    <td>{{ money(a.amount) }}</td>
                    <td>{{ a.term_months }} мес.</td>
                    <td>
                      <span :class="['status', a.status]">{{
                        statuses[a.status]
                      }}</span>
                    </td>
                    <td>
                      <button
                        class="icon-btn"
                        aria-label="Открыть заявку"
                        :disabled="busy"
                        @click.stop="run(() => openApplication(a.id))"
                      >
                        <Icon name="ChevronRight" :size="18" />
                      </button>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="compact-empty">
                <Icon name="FileText" />
                <p>
                  {{
                    applications.length
                      ? "Заявки по выбранным условиям не найдены."
                      : "Заявок пока нет. Начните с кредитного калькулятора."
                  }}
                </p>
              </div>
            </div>
          </section>
          <section v-if="!isOfficer" class="product-section">
            <h2>Кредитная история</h2>
            <div v-if="!loans.length" class="panel compact-empty">
              <Icon name="Clock3" />
              <p>Здесь появятся оформленные и завершённые кредиты.</p>
            </div>
            <div v-else class="product-grid">
              <article
                v-for="loan in loans"
                :key="loan.id"
                class="panel product-card"
              >
                <span
                  class="status"
                  :class="loan.status === 'active' ? 'DISBURSED' : ''"
                  >{{
                    loan.status === "active" ? "Действующий" : "Закрыт"
                  }}</span
                >
                <h2>{{ money(loan.amount) }}</h2>
                <div class="result-line">
                  <span>Остаток долга</span
                  ><strong>{{ money(loan.outstanding_balance) }}</strong>
                </div>
                <div class="result-line">
                  <span>Ежемесячный платёж</span
                  ><strong>{{ money(loan.monthly_payment) }}</strong>
                </div>
                <div class="result-line">
                  <span>Ставка / срок</span
                  ><strong
                    >{{ loan.annual_rate }}% /
                    {{ loan.term_months }} мес.</strong
                  >
                </div>
                <button
                  v-if="loan.application_id"
                  class="text-btn"
                  @click="run(() => openApplication(loan.application_id))"
                >
                  Посмотреть оформление <Icon name="ArrowRight" :size="16" />
                </button>
              </article>
            </div></section
        ></template>
      </template>
      <template v-else-if="page === 'assistant'"
        ><div class="page-heading">
          <div>
            <div class="eyebrow">РАЗБЕРЁМСЯ ВМЕСТЕ</div>
            <h1>Помощник для бизнеса <span class="ai-heading">AI</span></h1>
            <p>О кредитах, документах и следующих шагах простыми словами.</p>
          </div>
        </div>
        <section class="chat-layout">
          <div class="panel chat-panel">
            <div class="chat-header">
              <span class="quick-icon green"><Icon name="Sparkles" /></span>
              <div>
                <strong>Альфа-помощник</strong
                ><small><span class="live-dot"></span> {{ chatBusy ? "Готовит ответ…" : "AI-помощник" }}</small>
              </div>
              <button
                class="icon-btn"
                aria-label="Очистить чат"
                @click="resetChat"
                :disabled="chatBusy"
              >
                <Icon name="RefreshCw" :size="18" />
              </button>
            </div>
            <div class="chat-messages" aria-live="polite">
              <div
                v-for="(message, i) in chats"
                :key="i"
                :class="['message', message.role]"
              >
                <span v-if="message.role === 'assistant'" class="message-icon"
                  ><Icon name="Sparkles" :size="17"
                /></span>
                <div>{{ message.text }}</div>
              </div>
            </div>
            <form class="chat-form" @submit.prevent="assistant()">
              <input
                v-model="chatInput"
                aria-label="Сообщение помощнику"
                placeholder="Спросите о кредитовании бизнеса…"
                maxlength="2000"
              /><button
                class="primary"
                aria-label="Отправить сообщение"
                :disabled="!chatInput.trim() || chatBusy"
              >
                <Icon name="Send" :size="19" />
              </button>
            </form>
            <p class="chat-disclaimer">
              AI может ошибаться. Ответы носят справочный характер и не являются решением банка.
            </p>
          </div>
          <aside class="panel suggestions">
            <div v-if="activeScoringContext" class="scoring-chat-context">
              <div class="scoring-context-header">
                <span class="quick-icon"><Icon name="Gauge" :size="16" /></span>
                <div>
                  <small>ML-ОЦЕНКА ЗАЯВКИ</small>
                  <strong>Вероятность {{ activeScoringContext.display_percent?.toFixed(1) }}%</strong>
                </div>
              </div>
              <button class="scoring-context-query" @click="askAiAboutScoring('explain')">
                <span>Почему оценка {{ activeScoringContext.display_percent?.toFixed(1) }}%?</span>
                <Icon name="ArrowUpRight" :size="14" />
              </button>
              <button class="scoring-context-query" @click="askAiAboutScoring('improve')">
                <span>Как повысить рейтинг?</span>
                <Icon name="ArrowUpRight" :size="14" />
              </button>
              <button v-if="activeScoringContext.what_if_id" class="scoring-context-query" @click="askAiAboutScoring('what_if')">
                <span>Что изменилось в What-if?</span>
                <Icon name="ArrowUpRight" :size="14" />
              </button>
            </div>
            <span class="mini-label">С ЧЕГО НАЧНЁМ?</span>
            <h2>Частые вопросы</h2>
            <button
              v-for="q in [
                'Какие документы нужны для кредита?',
                'Как рассчитывается платёж?',
                'Как узнать статус заявки?',
                'Как подписать договор?',
              ]"
              :key="q"
              @click="assistant(q)"
            >
              {{ q }}<Icon name="ArrowUpRight" :size="17" />
            </button>
            <div class="assistant-note">
              <Icon name="ShieldCheck" />
              <p>
                Решение по кредиту принимается после проверки данных и оценки
                бизнеса.
              </p>
            </div>
          </aside>
        </section></template
      >
      <footer>
        <span
          ><span class="footer-brand">А</span> ©
          {{ new Date().getFullYear() }} Альфа-Бизнес</span
        ><span>Учебный проект · Демонстрационное кредитование</span
        ><button class="text-btn" @click="navigate('assistant')">
          <Icon name="CircleHelp" :size="16" /> Нужна помощь?
        </button>
      </footer>
    </main>
    <Transition name="toast"
      ><div v-if="toast" class="toast-message" role="status">
        <Icon name="CheckCircle2" :size="20" />{{ toast }}
      </div></Transition
    >
    <div v-if="modal" class="modal-backdrop" @click.self="closeModal">
      <section
        :class="[
          'modal',
          { wide: modal === 'application' || modal === 'schedule' },
        ]"
        role="dialog"
        aria-modal="true"
        :aria-label="
          modal === 'auth'
            ? 'Вход в кабинет'
            : modal === 'application'
              ? 'Кредитная заявка'
              : modal === 'schedule'
                ? 'График платежей'
                : modal === 'notifications' ? 'Уведомления' : modal === 'draft-choice' ? 'Продолжить заполнение' : 'Профиль компании'
        "
        tabindex="-1"
      >
        <button
          class="icon-btn modal-close"
          :disabled="busy"
          aria-label="Закрыть"
          @click="closeModal"
        >
          <Icon name="X" />
        </button>
        <div v-if="error" class="alert error" role="alert">{{ error }}</div>
        <template v-if="modal === 'auth'"
          ><span class="alfa-mark auth-logo">А<span></span></span>
          <h2>
            {{ register ? "Начнём с вашего бизнеса" : "Рады видеть вас" }}
          </h2>
          <p class="muted">
            {{
              register
                ? "Создайте аккаунт предпринимателя"
                : "Войдите в кредитный кабинет"
            }}
          </p>
          <form class="form-stack" @submit.prevent="authenticate">
            <label
              >Электронная почта<input
                v-model="auth.email"
                type="email"
                autocomplete="username"
                required
                placeholder="you@company.ru" /></label
            ><label
              >Пароль<input
                v-model="auth.password"
                type="password"
                :autocomplete="register ? 'new-password' : 'current-password'"
                :minlength="register ? 10 : 1"
                maxlength="128"
                required
                :placeholder="
                  register ? 'Не менее 10 символов' : 'Введите пароль'
                " /></label
            ><button class="primary full" :disabled="busy">
              {{ busy ? "Подождите…" : register ? "Создать аккаунт" : "Войти"
              }}<Icon name="ArrowRight" :size="18" /></button
            ><button
              class="text-btn centered"
              type="button"
              @click="
                register = !register;
                error = '';
              "
            >
              {{
                register
                  ? "Уже есть аккаунт? Войти"
                  : "Впервые здесь? Зарегистрироваться"
              }}
            </button>
          </form></template
        >
        <template v-else-if="modal === 'draft-choice'">
          <h2>Продолжить заполнение?</h2>
          <p class="muted">У вас есть сохранённые данные. Можно продолжить черновик или заполнить новую заявку.</p>
          <article v-for="draft in drafts" :key="draft.id" class="notification-item">
            <strong>{{ draft.company.name || 'Незавершённое заполнение' }}</strong>
            <p>{{ purposes[draft.purpose] }} · {{ money(draft.amount) }} · {{ draft.term_months }} мес.</p>
            <p class="muted small">Сохранено {{ date(draft.updated_at) }}</p>
            <button class="secondary" :disabled="busy" @click="run(() => openApplication(draft.id))">Продолжить черновик</button>
          </article>
          <button class="primary full" :disabled="busy" @click="run(() => startNewForm(pendingProduct))">Создать новую заявку</button>
        </template>
        <template v-else-if="modal === 'notifications'">
          <h2>Уведомления</h2>
          <div class="notification-toolbar">
            <span class="muted small">Непрочитанных: {{ notifications.unread_count }}</span>
            <button class="text-btn" :disabled="busy || !notifications.unread_count" @click="run(() => markNotificationsRead([], true))">Прочитать все</button>
          </div>
          <p v-if="!notifications.items.length" class="muted">Уведомлений пока нет.</p>
          <article v-for="item in notifications.items" :key="item.id" :class="['notification-item', { unread: !item.read }]">
            <strong>{{ item.title }}</strong>
            <p class="muted small">Заявка № {{ item.application_id.slice(0, 8).toUpperCase() }} · {{ statuses[item.status] }} · {{ date(item.created_at) }}</p>
            <div class="action-buttons">
              <button class="text-btn" :disabled="busy" @click="readNotification(item)">Открыть заявку</button>
              <button v-if="!item.read" class="text-btn" :disabled="busy" @click="run(() => markNotificationsRead([item.id]))">Отметить прочитанным</button>
              <span v-else class="muted small">Прочитано</span>
            </div>
          </article>
          <button v-if="notifications.items.length && notifications.items.length % 50 === 0" class="secondary" :disabled="notificationLoading" @click="moreNotifications">Показать ещё</button>
        </template>
        <template v-else-if="modal === 'profile'"
          ><h2>{{ isOfficer ? "Профиль сотрудника" : "Моя компания" }}</h2>
          <p class="muted">
            {{ user.email }} ·
            {{ isOfficer ? "Сотрудник банка" : "Предприниматель" }}
          </p>
          <form
            v-if="!isOfficer"
            class="form-stack"
            @submit.prevent="saveProfile"
          >
            <label
              >Название компании<input
                v-model="company.name"
                required
                maxlength="250" /></label
            ><label
              >ИНН<input
                v-model="company.inn"
                required
                pattern="[0-9]{10}|[0-9]{12}"
                maxlength="12"
                inputmode="numeric" /></label
            ><label
              >Дата регистрации<input
                v-model="company.registration_date"
                type="date"
                :max="new Date().toLocaleDateString('en-CA')"
                required /></label
            ><label
              >Юридический адрес<input
                v-model="company.address"
                required
                minlength="3" /></label
            ><label
              >ОКВЭД<input
                v-model="company.industry"
                placeholder="62.01"
                required
                minlength="2" /></label
            ><label>Платежи по кредитам других банков в месяц, ₽<input v-model="financials.monthly_debt_payments" type="number" min="0" step="0.01" required /></label>
            <label>Остаток долга в других банках, ₽<input v-model="financials.outstanding_debt" type="number" min="0" step="0.01" required /></label>
            <p class="muted small">Обязательства перед этим банком учитываются автоматически и не входят в эти поля.</p>
            <button class="primary full" :disabled="busy">
              Сохранить данные
            </button>
          </form>
          <button class="text-btn logout" @click="logout">
            <Icon name="LogOut" :size="18" /> Выйти из кабинета
          </button></template
        >
        <template v-else-if="modal === 'schedule'"
          ><span class="eyebrow">УСЛОВИЯ ФИНАНСИРОВАНИЯ</span>
          <h2>График платежей</h2>
          <div class="schedule-summary">
            <div>
              <small>Сумма</small><strong>{{ money(preview.amount) }}</strong>
            </div>
            <div>
              <small>Ставка</small><strong>{{ preview.annual_rate }}%</strong>
            </div>
            <div>
              <small>Платёж в месяц</small
              ><strong>{{ money(preview.monthly_payment) }}</strong>
            </div>
          </div>
          <div class="result-line"><span>Переплата по процентам</span><strong>{{ money(Number(previewTotal) - Number(preview.amount)) }}</strong></div>
          <div class="result-line"><span>Общая сумма выплат</span><strong>{{ money(previewTotal) }}</strong></div>
          <p class="muted small">
            Демонстрационный расчёт. Условия не являются публичной офертой.
          </p>
          <div class="table-scroll schedule-table">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Платёж</th>
                  <th>Основной долг</th>
                  <th>Проценты</th>
                  <th>Остаток</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(row, i) in preview.schedule" :key="i">
                  <td>{{ date(row.due_date) }}</td>
                  <td>{{ money(row.payment) }}</td>
                  <td>{{ money(row.principal) }}</td>
                  <td>{{ money(row.interest) }}</td>
                  <td>{{ money(row.balance) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <button
            v-if="current"
            class="secondary"
            @click="modal = 'application'"
          >
            Вернуться к заявке
          </button></template
        >
        <template v-else-if="modal === 'application' && current"
          ><span class="eyebrow"
            >{{ current.status === 'DRAFT' ? 'ЗАПОЛНЕНИЕ ЗАЯВКИ' : 'ЗАЯВКА № ' + current.id.slice(0, 8).toUpperCase() }}</span
          >
          <div class="application-heading">
            <h2>{{ purposes[current.purpose] }}</h2>
            <span v-if="current.status !== 'DRAFT'" :class="['status', current.status]">{{
              statuses[current.status]
            }}</span>
          </div>
          <div class="schedule-summary">
            <div>
              <small>Сумма</small><strong>{{ money(current.amount) }}</strong>
            </div>
            <div>
              <small>Срок</small><strong>{{ current.term_months }} мес.</strong>
            </div>
            <div>
              <small>Продукт</small
              ><strong class="small">{{
                current.product_snapshot.name
              }}</strong>
            </div>
          </div>
          <div
            v-for="c in current.clarifications?.filter((c) => !c.responded_at)"
            :key="c.id"
            class="alert warning"
          >
            <Icon name="CircleHelp" />
            <div>
              <strong>Запрос на уточнение</strong>
              <p>{{ c.comment }}</p>
              <small v-if="c.required_fields.length"
                >Поля: {{ c.required_fields.join(", ") }}</small
              >
              <p v-if="c.required_documents.length">
                Документы:
                {{
                  c.required_documents.map((k) => documentKinds[k]).join(", ")
                }}
              </p>
            </div>
          </div>
          <template v-if="editable && !isOfficer"
            ><div class="wizard-steps">
              <button
                v-for="(label, i) in ['Компания', 'Финансы', 'Документы']"
                :key="label"
                :class="{ active: step === i + 1, done: step > i + 1 }"
                @click="i + 1 < step ? (step = i + 1) : null"
              >
                <span>{{ i + 1 }}</span
                >{{ label }}
              </button>
            </div>
            <form @submit.prevent="step < 3 ? nextStep() : submitApplication()">
              <div v-if="profileDiff.length" class="alert warning profile-diff" role="status">
                <div><strong>Данные отличаются от профиля бизнеса</strong>
                  <p>{{ profileDiff.join(", ") }}</p>
                  <label class="checkbox-label"><input v-model="syncProfile" type="checkbox" />Обновить профиль бизнеса данными этой заявки</label>
                </div>
              </div>
              <div v-if="step === 1" class="form-grid">
                <label
                  >Название компании<input
                    v-model="company.name"
                    required
                    maxlength="250" /></label
                ><label
                  >ИНН<input
                    v-model="company.inn"
                    required
                    pattern="[0-9]{10}|[0-9]{12}"
                    maxlength="12"
                    inputmode="numeric" /></label
                ><label
                  >Дата регистрации<input
                    v-model="company.registration_date"
                    type="date"
                    :max="new Date().toLocaleDateString('en-CA')"
                    required /></label
                ><label
                  >ОКВЭД<input
                    v-model="company.industry"
                    required
                    minlength="2"
                    placeholder="62.01" /></label
                ><label class="span-2"
                  >Юридический адрес<input
                    v-model="company.address"
                    minlength="3"
                    required
                /></label>
              </div>
              <div v-if="step === 2" class="form-grid">
                <label
                  >Годовая выручка, ₽<input
                    :value="financials.annual_revenue"
                    @input="financials.annual_revenue = $event.target.value"
                    type="number"
                    min="0.01"
                    step="0.01"
                    required /></label
                ><label
                  >Расходы в месяц, ₽<input
                    :value="financials.monthly_expenses"
                    @input="financials.monthly_expenses = $event.target.value"
                    type="number"
                    min="0"
                    step="0.01"
                    required /></label
                ><div class="span-2 credit-obligations">
                  <h3>Текущие кредитные обязательства</h3>
                  <dl>
                    <dt>Платежи по кредитам этого банка</dt><dd>{{ money(obligations.bank_monthly_payments) }} / мес.</dd>
                    <dt>Дополнительные платежи другим банкам</dt><dd>{{ money(obligations.external_monthly_payments) }} / мес.</dd>
                    <dt>Итого текущие платежи</dt><dd>{{ money(obligations.total_monthly_payments) }} / мес.</dd>
                    <dt>Остаток долга в этом банке</dt><dd>{{ money(obligations.bank_outstanding_debt) }}</dd>
                    <dt>Остаток долга в других банках</dt><dd>{{ money(obligations.external_outstanding_debt) }}</dd>
                  </dl>
                  <p class="muted small">Платежи этого банка учитываются автоматически. Сведения о других банках можно изменить только в профиле бизнеса.</p>
                </div>
                <label
                  >Кредитная история<select v-model="financials.credit_history">
                    <option value="none">Нет кредитной истории</option>
                    <option value="good">Без просрочек</option>
                    <option value="average">Были небольшие задержки</option>
                    <option value="bad">Были просрочки</option>
                  </select></label
                ><label
                  >Текущая просрочка, дней<input
                    v-model.number="financials.overdue_days"
                    type="number"
                    min="0"
                    max="3650"
                    required /></label
                ><label class="checkbox-label span-2"
                  ><input v-model="financials.has_collateral" type="checkbox" />
                  Есть имущество для залога</label
                >
              </div>
              <div v-if="step === 3">
                <p class="muted small">
                  PDF, PNG или JPEG, до 10 МБ на файл. Не более 20 файлов.
                </p>
                <div v-for="kind in neededDocs" :key="kind" class="upload-row">
                  <div>
                    <Icon name="FileText" /><strong>{{
                      documentKinds[kind]
                    }}</strong
                    ><span
                      v-if="current.documents.some((d) => d.kind === kind)"
                      class="status DISBURSED"
                      >Загружено</span
                    >
                  </div>
                  <label class="secondary upload-button"
                    ><Icon name="Upload" :size="16" /> Загрузить<input
                      type="file"
                      accept="application/pdf,image/png,image/jpeg"
                      :disabled="busy"
                      @change="upload($event, kind)"
                  /></label>
                </div>
                <div
                  v-for="doc in current.documents"
                  :key="doc.id"
                  class="file-row"
                >
                  <button type="button" class="text-btn" @click="download(doc)">
                    <Icon name="Download" :size="15" />{{
                      doc.filename
                    }}</button
                  ><button
                    type="button"
                    class="icon-btn"
                    aria-label="Удалить документ"
                    :disabled="busy"
                    @click="removeDocument(doc)"
                  >
                    <Icon name="X" :size="16" />
                  </button>
                </div>
                <div v-if="current.status === 'NEEDS_CLARIFICATION'">
                  <p class="muted small">Ответ сотруднику: {{ clarificationSummary }}</p>
                  <label>Дополнение к ответу (необязательно)<textarea v-model="comment" minlength="3" maxlength="3000" placeholder="Поясните изменения, если это необходимо" /></label>
                </div>
                <label class="checkbox-label confirmation"
                  ><input v-model="confirmed" type="checkbox" required />
                  Подтверждаю актуальность сведений и согласие на их
                  обработку</label
                >
              </div>
              <div class="wizard-actions">
                <button
                  v-if="step > 1"
                  type="button"
                  class="secondary"
                  @click="step--"
                >
                  Назад</button
                ><span class="muted small">{{ draftSaving ? 'Сохраняем черновик…' : draftSaved ? 'Черновик сохранён' : 'Изменённые данные сохранятся автоматически' }}</span
                ><button
                  class="primary"
                  :disabled="busy || (step === 3 && !confirmed)"
                >
                  {{
                    busy
                      ? "Сохраняем…"
                      : step < 3
                        ? "Продолжить"
                        : "Отправить заявку"
                  }}<Icon name="ArrowRight" :size="17" />
                </button>
              </div></form
          ></template>
          <template v-else
            ><div class="dossier-grid">
              <section>
                <h3>Данные компании</h3>
                <dl>
                  <dt>Компания</dt>
                  <dd>{{ current.company.name || "Не указана" }}</dd>
                  <dt>ИНН</dt>
                  <dd>{{ current.company.inn || "—" }}</dd>
                  <dt>Регистрация</dt>
                  <dd>{{ current.company.registration_date || "—" }}</dd>
                  <dt>Адрес</dt>
                  <dd>{{ current.company.address || "—" }}</dd>
                  <dt>ОКВЭД</dt>
                  <dd>{{ current.company.industry || "—" }}</dd>
                </dl>
              </section>
              <section>
                <h3>Финансовые показатели</h3>
                <dl>
                  <dt>Годовая выручка</dt>
                  <dd>{{ money(current.financials.annual_revenue) }}</dd>
                  <dt>Расходы / месяц</dt>
                  <dd>{{ money(current.financials.monthly_expenses) }}</dd>
                  <dt>Платежи в этом банке</dt><dd>{{ money(obligations.bank_monthly_payments) }}</dd>
                  <dt>Платежи другим банкам</dt><dd>{{ money(obligations.external_monthly_payments) }}</dd>
                  <dt>Итого текущие платежи</dt><dd>{{ money(obligations.total_monthly_payments) }}</dd>
                  <dt>Текущий долг всего</dt><dd>{{ money(obligations.total_outstanding_debt) }}</dd>
                  <dt>Обеспечение</dt>
                  <dd>
                    {{
                      current.financials.has_collateral
                        ? "Есть имущество для залога"
                        : "Без залога"
                    }}
                  </dd>
                  <dt>Кредитная история</dt>
                  <dd>
                    {{
                      {
                        good: "Без просрочек",
                        average: "Небольшие задержки",
                        bad: "Были просрочки",
                        none: "Нет истории",
                      }[current.financials.credit_history] || "—"
                    }}
                  </dd>
                  <dt>Просрочка</dt>
                  <dd>{{ current.financials.overdue_days || 0 }} дн.</dd>
                </dl>
              </section>
            </div>
            <h3>Документы</h3>
            <p v-if="!current.documents.length" class="muted small">
              Документы не загружены
            </p>
            <div
              v-for="doc in current.documents"
              :key="doc.id"
              class="file-row"
            >
              <span>{{ documentKinds[doc.kind] }}</span
              ><button class="text-btn" @click="download(doc)">
                <Icon name="Download" :size="16" />{{ doc.filename }}
              </button>
            </div></template
          >
          <section v-if="isOfficer && current.clarifications?.some((c) => c.responded_at)">
            <h3>Ответы на уточнения</h3>
            <div v-for="c in current.clarifications.filter((c) => c.responded_at)" :key="c.id" class="check-result"><strong>{{ c.comment }}</strong><p>{{ c.response }}</p><small>{{ date(c.responded_at) }}</small></div>
          </section>
          <section v-if="isOfficer" class="officer-actions">
            <h3>Обработка заявки</h3>
            <div
              v-for="check in current.checks"
              :key="check.id"
              class="check-result"
            >
              <strong>Проверка от {{ date(check.created_at) }}</strong>
              <p class="muted small">Учебные источники: имитация ФНС и БКИ, без обращения к государственным реестрам и бюро.</p>
              <p v-if="check.data_revision !== current.data_revision" class="alert warning">Результаты устарели после изменения данных. Запустите проверку повторно.</p>
              <dl><template v-for="[label, value] in checkRows(check.results)" :key="label"><dt>{{ label }}</dt><dd>{{ value }}</dd></template></dl>
              <p v-for="code in check.results.discrepancies" :key="code" class="alert warning">{{ discrepancyLabels[code] || code }}</p>
            </div>
            <div v-if="current.status === 'SUBMITTED'" class="action-buttons">
              <button
                class="primary"
                :disabled="busy"
                @click="action('take-to-work')"
              >
                Взять в работу
              </button>
            </div>
            <template v-if="current.status === 'PRIMARY_REVIEW'">
              <button class="secondary" :disabled="busy" @click="action('run-external-checks')"><Icon name="ShieldCheck" :size="17" /> Проверить ФНС и БКИ</button>
              <p v-if="!latestCheck" class="muted small">Получите актуальные данные ФНС и БКИ, чтобы подготовить заключение.</p>
              <button v-if="!latestCheck && !manualReview" class="secondary" @click="manualReview = true">Запросить уточнение или отклонить до получения проверок</button>
              <template v-if="latestCheck || manualReview"><label
                >{{ latestCheck ? 'Комментарий / заключение' : 'Вопрос клиенту / причина отказа' }}<textarea
                  v-model="comment"
                  minlength="3"
                  maxlength="4000"
                  placeholder="Результат проверки или запрос клиенту"
                />
              </label>
              <div class="checklist">
                <label
                  v-for="(label, kind) in documentKinds"
                  :key="kind"
                  class="checkbox-label"
                  ><input
                    v-model="requiredDocs"
                    type="checkbox"
                    :value="kind"
                  />{{ label }}</label
                >
              </div>
              <div class="action-buttons">
                <button
                  class="secondary"
                  :disabled="busy || comment.trim().length < 3"
                  @click="action('request-clarification')"
                >
                  Запросить уточнение</button
                ><button
                  class="secondary danger"
                  :disabled="busy || comment.trim().length < 3"
                  @click="action('reject-primary')"
                >
                  Отклонить</button
                ><button
                  class="primary"
                  :disabled="
                    busy || comment.trim().length < 3 || !latestCheck || !!latestCheck.results.discrepancies?.length
                  "
                  @click="action('pass-to-auto-analysis')"
                >
                  Запустить автоанализ <Icon name="ArrowRight" :size="17" />
                </button></div></template
            ></template>
            <p
              v-else-if="current.status === 'NEEDS_CLARIFICATION'"
              class="muted"
            >
              Ожидаем ответ предпринимателя.
            </p>
          </section>
          <section v-if="!isOfficer && current.id" class="scoring-section">
            <div class="scoring-header">
              <div>
                <span class="eyebrow">ML ИНТЕЛЛЕКТУАЛЬНЫЙ АНАЛИЗ</span>
                <h3><Icon name="Gauge" :size="22" /> Кредитный рейтинг и вероятность одобрения</h3>
              </div>
              <button
                v-if="scoringAssessment"
                class="secondary"
                :disabled="scoringLoading"
                @click="runScoring"
              >
                <Icon name="RotateCcw" :size="16" /> Пересчитать оценку
              </button>
            </div>

            <div v-if="scoringError" class="alert warning">
              <Icon name="CircleHelp" />
              <div>
                <strong>Не удалось рассчитать скоринг</strong>
                <p>{{ scoringError }}</p>
                <button class="secondary small" :disabled="scoringLoading" @click="runScoring">
                  Повторить попытку
                </button>
              </div>
            </div>

            <div v-if="!scoringAssessment && !scoringLoading && !scoringError" class="scoring-empty-state">
              <span class="quick-icon"><Icon name="Zap" :size="28" /></span>
              <h4>Узнайте вероятность одобрения кредита</h4>
              <p>
                Интеллектуальная ML-модель мгновенно оценит заявку по 6 финансовым показателям бизнеса,
                покажет факторы влияния и позволит смоделировать симуляцию What-if.
              </p>
              <button class="primary" :disabled="scoringLoading" @click="runScoring">
                <Icon name="Zap" :size="18" /> Рассчитать кредитный рейтинг
              </button>
            </div>

            <div v-if="scoringLoading" class="scoring-empty-state">
              <span class="live-dot"></span>
              <h4>Выполняем ML-скоринг заявки…</h4>
              <p>Анализируем выручку, срок бизнеса, кредитную историю и рассчитываем вклад признаков.</p>
            </div>

            <template v-if="scoringAssessment">
              <div class="scoring-hero">
                <div class="scoring-score-box">
                  <span class="eyebrow">ВЕРОЯТНОСТЬ ОДОБРЕНИЯ</span>
                  <div
                    :class="[
                      'scoring-score-value',
                      scoringAssessment.score.display_percent >= 70
                        ? 'high'
                        : scoringAssessment.score.display_percent >= 40
                          ? 'medium'
                          : 'low',
                    ]"
                  >
                    {{ scoringAssessment.score.display_percent.toFixed(1) }}%
                  </div>
                  <div class="scoring-progress-track">
                    <div
                      :class="[
                        'scoring-progress-fill',
                        scoringAssessment.score.display_percent >= 70
                          ? 'high'
                          : scoringAssessment.score.display_percent >= 40
                            ? 'medium'
                            : 'low',
                      ]"
                      :style="{ width: Math.min(100, Math.max(0, scoringAssessment.score.display_percent)) + '%' }"
                    ></div>
                  </div>
                  <span
                    :class="[
                      'scoring-level-badge',
                      scoringAssessment.score.display_percent >= 70
                        ? 'high'
                        : scoringAssessment.score.display_percent >= 40
                          ? 'medium'
                          : 'low',
                    ]"
                  >
                    {{
                      scoringAssessment.score.display_percent >= 70
                        ? "Высокая вероятность"
                        : scoringAssessment.score.display_percent >= 40
                          ? "Умеренная вероятность"
                          : "Повышенный риск"
                    }}
                  </span>
                </div>
                <div class="scoring-info">
                  <div class="scoring-meta-tags">
                    <span class="scoring-tag">Модель: {{ scoringAssessment.model?.model_id || 'logistic_regression' }}</span>
                    <span class="scoring-tag">Версия: {{ scoringAssessment.model?.model_version || '1.0' }}</span>
                    <span class="scoring-tag">ID: {{ scoringAssessment.assessment_id.slice(0, 8) }}…</span>
                  </div>
                  <p class="muted small">
                    {{ scoringAssessment.limitations_warning || "Демонстрационная оценка на базе синтетической модели. Не является решением банка." }}
                  </p>
                  <div class="scoring-ai-callout">
                    <div>
                      <strong>Хотите подробный разбор этой оценки?</strong>
                      <p>AI-помощник объяснит логику модели, вклад каждого фактора и даст рекомендации.</p>
                    </div>
                    <button class="btn-ai-sparkle" @click="askAiAboutScoring('explain')">
                      <Icon name="Sparkles" :size="16" /> Объяснить с AI
                    </button>
                  </div>
                </div>
              </div>

              <!-- Factors (Explainable AI) -->
              <div class="scoring-subheading">
                <span>Факторы, повлиявшие на скоринг (XAI)</span>
                <small class="muted">6 признаков · Вклад в скоринговый лоджит</small>
              </div>
              <div class="factors-grid">
                <div
                  v-for="factor in scoringAssessment.explanation?.factors || []"
                  :key="factor.feature"
                  class="factor-card"
                >
                  <div class="factor-top">
                    <span class="factor-name">{{ factor.display_name || scoringFeatureLabels[factor.feature] || factor.feature }}</span>
                    <span class="factor-rank">#{{ factor.rank }}</span>
                  </div>
                  <div class="factor-values">
                    <div>
                      <small class="muted">Значение: </small>
                      <span class="factor-val-current">{{ formatFeatureValue(factor.feature, factor.input_value) }}</span>
                    </div>
                    <span :class="['factor-effect-badge', factor.direction]">
                      <Icon v-if="factor.direction === 'positive'" name="TrendingUp" :size="14" />
                      <Icon v-else-if="factor.direction === 'negative'" name="TrendingDown" :size="14" />
                      <Icon v-else name="Info" :size="14" />
                      {{
                        factor.direction === "positive"
                          ? `+${factor.logit_contribution.toFixed(2)} logit`
                          : factor.direction === "negative"
                            ? `${factor.logit_contribution.toFixed(2)} logit`
                            : "нейтрально"
                      }}
                    </span>
                  </div>
                  <button class="factor-ask-btn" @click="askAiAboutScoring(`factor:${factor.feature}`)">
                    Спросить AI об этом факторе <Icon name="ArrowRight" :size="12" />
                  </button>
                </div>
              </div>

              <!-- What-if Simulator -->
              <div class="what-if-panel">
                <div class="what-if-header">
                  <div>
                    <h4><Icon name="SlidersHorizontal" :size="18" /> Симулятор What-if («Что если?»)</h4>
                    <small class="muted">Проверьте, как изменится вероятность при изменении условий без редактирования самой заявки</small>
                  </div>
                </div>
                <div class="what-if-grid">
                  <label>
                    Годовая выручка, ₽
                    <input v-model.number="whatIfForm.annual_revenue" type="number" min="100000" step="50000" />
                  </label>
                  <label>
                    Запрашиваемая сумма, ₽
                    <input v-model.number="whatIfForm.loan_amount" type="number" min="100000" step="50000" />
                  </label>
                  <label>
                    Срок кредита, мес.
                    <select v-model.number="whatIfForm.loan_term_months">
                      <option :value="6">6 месяцев</option>
                      <option :value="12">12 месяцев</option>
                      <option :value="18">18 месяцев</option>
                      <option :value="24">24 месяца</option>
                      <option :value="36">36 месяцев</option>
                      <option :value="48">48 месяцев</option>
                      <option :value="60">60 месяцев</option>
                    </select>
                  </label>
                  <label>
                    Кредитная история
                    <select v-model="whatIfForm.credit_history">
                      <option value="good">Без просрочек</option>
                      <option value="average">Были небольшие задержки</option>
                      <option value="bad">Были просрочки</option>
                      <option value="none">Нет кредитной истории</option>
                    </select>
                  </label>
                  <label>
                    Срок работы бизнеса, мес.
                    <input v-model.number="whatIfForm.business_age_months" type="number" min="0" max="600" />
                  </label>
                  <label class="checkbox-label">
                    <input v-model="whatIfForm.has_collateral" type="checkbox" />
                    Есть имущество для залога
                  </label>
                </div>
                <div class="what-if-actions">
                  <button class="primary" :disabled="whatIfLoading" @click="runWhatIf">
                    <Icon name="SlidersHorizontal" :size="16" /> {{ whatIfLoading ? "Считаем симуляцию…" : "Смоделировать What-if" }}
                  </button>
                </div>

                <div v-if="whatIfError" class="alert warning" style="margin-top: 14px;">
                  <Icon name="CircleHelp" />
                  <p>{{ whatIfError }}</p>
                </div>

                <div v-if="whatIfResult" class="what-if-result-card">
                  <div class="what-if-comparison">
                    <div class="what-if-metric">
                      <small>Текущая вероятность</small>
                      <strong>{{ whatIfResult.original?.score?.display_percent?.toFixed(1) }}%</strong>
                    </div>
                    <div
                      :class="[
                        'what-if-delta',
                        whatIfResult.delta_percentage_points > 0
                          ? 'positive'
                          : whatIfResult.delta_percentage_points < 0
                            ? 'negative'
                            : 'neutral',
                      ]"
                    >
                      <Icon v-if="whatIfResult.delta_percentage_points > 0" name="TrendingUp" :size="20" />
                      <Icon v-else-if="whatIfResult.delta_percentage_points < 0" name="TrendingDown" :size="20" />
                      {{ whatIfResult.delta_percentage_points > 0 ? '+' : '' }}{{ whatIfResult.delta_percentage_points.toFixed(1) }} п.п.
                    </div>
                    <div class="what-if-metric">
                      <small>Смоделированная</small>
                      <strong style="color: #38bdf8;">{{ whatIfResult.alternative?.score?.display_percent?.toFixed(1) }}%</strong>
                    </div>
                  </div>
                  <div class="scoring-ai-callout" style="margin-top: 8px;">
                    <p class="small muted">
                      {{ whatIfResult.limitations_warning || "Симуляция носит ориентировочный характер и не изменяет параметры вашей реальной заявки." }}
                    </p>
                    <button class="btn-ai-sparkle" @click="askAiAboutScoring('what_if')">
                      <Icon name="Sparkles" :size="15" /> Объяснить симуляцию с AI
                    </button>
                  </div>
                </div>
              </div>
            </template>
          </section>
          <section v-if="current.decision" class="decision-section">
            <h3>Результат анализа</h3>
            <div class="schedule-summary">
              <div>
                <small>Скоринговый балл</small
                ><strong>{{ current.decision.score == null ? 'Не рассчитывался' : current.decision.score + ' / 850' }}</strong>
              </div>
              <div>
                <small>Категория риска</small
                ><strong>{{
                  current.decision.risk_category?.replace("CATEGORY_", "").replace("REJECT_D", "D") || "Не определена"
                }}</strong>
              </div>
              <div>
                <small>Решение</small
                ><strong>{{
                  current.decision.outcome === "APPROVE" ? "Одобрено" : "Отказ"
                }}</strong>
              </div>
            </div>
            <p v-if="current.decision.reasons?.length" class="alert warning">
              Причины:
              {{
                current.decision.reasons
                  .map((code) => decisionReasons[code] || code)
                  .join("; ")
              }}
            </p>
            <p class="muted small">Балл характеризует риск. Решение также учитывает обязательные требования продукта и долговую нагрузку.</p>
            <dl v-if="current.decision.metrics">
              <dt>Срок работы бизнеса</dt><dd>{{ current.decision.metrics.business_age_months }} мес.</dd>
              <dt>Чистая прибыль в месяц</dt><dd>{{ money(current.decision.metrics.monthly_net_profit) }}</dd>
              <dt>Долговая нагрузка</dt><dd>{{ current.decision.metrics.debt_burden == null ? 'Не рассчитывается при неположительной прибыли' : (Number(current.decision.metrics.debt_burden) * 100).toFixed(1) + '%' }}</dd>
              <dt>Допустимая нагрузка</dt><dd>{{ (Math.min(Number(current.decision.policy_snapshot?.max_burden ?? .7), Number(current.product_snapshot.max_debt_burden)) * 100).toFixed(1) }}%</dd>
            </dl>
            <details v-if="isOfficer && current.decision.factors?.length">
              <summary>Факторы оценки</summary>
              <dl><template v-for="factor in current.decision.factors" :key="factor.code"><dt>{{ factorLabels[factor.code] || factor.code }}</dt><dd>{{ factor.points > 0 ? '+' : '' }}{{ factor.points }} баллов</dd></template></dl>
            </details>
          </section>
          <section v-if="current.offer" class="offer-section">
            <h3>Предложение банка</h3>
            <div class="schedule-summary">
              <div>
                <small>Одобренная сумма</small
                ><strong>{{ money(current.offer.amount) }}</strong>
              </div>
              <div>
                <small>Ставка</small
                ><strong>{{ current.offer.annual_rate }}%</strong>
              </div>
              <div>
                <small>Платёж / месяц</small
                ><strong>{{ money(current.offer.monthly_payment) }}</strong>
              </div>
            </div>
            <div class="action-buttons">
              <button class="secondary" @click="showSchedule(current.offer)">
                График платежей</button
              ><template v-if="!isOfficer && current.status === 'OFFER_READY'"
                ><button
                  class="secondary"
                  :disabled="busy"
                  @click="action('offer/decline')"
                >
                  Отказаться от предложения</button
                ><button
                  class="primary"
                  :disabled="busy"
                  @click="action('offer/accept')"
                >
                  Принять предложение
                </button></template
              >
            </div>
          </section>
          <section v-if="current.contract" class="contract-section">
            <h3>Кредитный договор</h3>
            <p class="muted small">
              Демонстрационное оформление. Реальная подпись и перевод денег не
              выполняются.
            </p>
            <p v-if="contractLoading" class="muted">Формируем предпросмотр PDF…</p>
            <template v-if="contractUrl">
              <iframe class="contract-preview" :src="contractUrl" title="Предпросмотр кредитного договора в PDF"></iframe>
              <div class="action-buttons">
                <a class="secondary" :href="contractUrl" :download="`contract-${current.id}.pdf`">Скачать договор в PDF</a>
                <a class="text-btn" :href="contractUrl" target="_blank" rel="noopener">Открыть PDF в новой вкладке</a>
              </div>
            </template>
            <button v-else-if="!contractLoading" class="secondary" @click="loadContract">Повторить загрузку PDF</button>
            <form
              v-if="!isOfficer && current.status === 'SIGNING'"
              class="sign-form"
              @submit.prevent="action('sign')"
            >
              <label
                >Код подтверждения (демо: 123456)<input
                  v-model="signingCode"
                  inputmode="numeric"
                  pattern="[0-9]{6}"
                  maxlength="6"
                  required
                  placeholder="000000" /></label
              ><button class="primary" :disabled="busy">
                Подтвердить оформление
              </button>
            </form>
            <div v-if="current.status === 'DISBURSED'" class="alert success">
              <Icon name="CheckCircle2" /> Кредит оформлен в демонстрационном
              режиме
            </div>
          </section>
          <section v-if="current.history?.length" class="history-section">
            <h3>История заявки</h3>
            <div
              v-for="event in current.history"
              :key="event.id"
              class="history-row"
            >
              <span class="live-dot"></span
              ><span
                ><span>{{ auditActions[event.action] || 'Изменение заявки' }}</span>
                <small>{{ statuses[event.to_status] }} · {{ date(event.created_at) }}</small>
                <small v-if="event.details.comment">{{ event.details.comment }}</small></span
              >
            </div>
          </section>
        </template>
      </section>
    </div>
  </div>
</template>
