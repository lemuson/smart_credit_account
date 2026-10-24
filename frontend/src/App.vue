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
import { api, setToken } from "./api";
import {
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
  signingCode = ref(""),
  requiredDocs = ref([]);
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
const activeApplications = computed(() =>
  applications.value.filter(
    (a) => !["DISBURSED", "REJECTED", "OFFER_DECLINED"].includes(a.status),
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
      (filter.value === "all" || a.status === filter.value) &&
      `${a.company?.name} ${a.id} ${purposes[a.purpose]}`
        .toLowerCase()
        .includes(search.value.toLowerCase()),
  ),
);
const estimated = computed(() =>
  payment(calc.amount, available.value[0]?.annual_rate || 18, calc.term),
);
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
  const values = await Promise.all(tasks);
  applications.value = values[0];
  if (!isOfficer.value) {
    loans.value = values[1];
    feed.value = values[2].items;
  }
}
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
  user.value = null;
  profile.value = { company: {}, financials: {} };
  products.value = [];
  applications.value = [];
  loans.value = [];
  feed.value = [];
  Object.assign(company, emptyCompany());
  Object.assign(financials, emptyFinancials());
  modal.value = null;
  current.value = null;
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
    profile.value = await api("/profile", {
      method: "PUT",
      body: {
        company: { ...company },
        financials: financials.annual_revenue ? financialPayload() : null,
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
    if (!p)
      throw new Error(
        "Сначала выберите подходящий кредитный продукт в калькуляторе.",
      );
    const a = await api("/client/applications", {
      method: "POST",
      body: {
        product_id: p.id,
        purpose: calc.purpose,
        amount: String(calc.amount),
        term_months: Number(calc.term),
      },
    });
    await openApplication(a.id);
    await refresh();
  });
}
async function openApplication(id) {
  error.value = "";
  current.value = await api(
    isOfficer.value
      ? `/bank/applications/${id}/dossier`
      : `/client/applications/${id}`,
  );
  Object.assign(company, emptyCompany(), current.value.company);
  Object.assign(financials, emptyFinancials(), current.value.financials);
  requiredDocs.value =
    current.value.clarifications
      ?.filter((c) => !c.responded_at)
      .flatMap((c) => c.required_documents) || [];
  step.value = 1;
  confirmed.value = false;
  comment.value = "";
  signingCode.value = "";
  modal.value = "application";
}
async function reloadCurrent() {
  current.value = await api(
    isOfficer.value
      ? `/bank/applications/${current.value.id}/dossier`
      : `/client/applications/${current.value.id}`,
  );
  await refresh();
}
async function saveDraft() {
  await api(`/client/applications/${current.value.id}`, {
    method: "PUT",
    body: {
      expected_version: current.value.version,
      company: { ...company },
      financials: financialPayload(),
    },
  });
  await reloadCurrent();
}
async function nextStep() {
  await run(async () => {
    if (step.value === 2) await saveDraft();
    step.value++;
  });
}
async function submitApplication() {
  await run(async () => {
    await saveDraft();
    const clarification = current.value.status === "NEEDS_CLARIFICATION";
    await api(
      `/client/applications/${current.value.id}/${clarification ? "clarify" : "submit"}`,
      {
        method: "POST",
        body: {
          expected_version: current.value.version,
          confirmed: confirmed.value,
          ...(clarification ? { response: comment.value } : {}),
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
    flash("Статус заявки обновлён");
  });
}
function showSchedule(offer) {
  preview.value = offer;
  modal.value = "schedule";
}
function assistant(text = chatInput.value) {
  if (!text.trim()) return;
  chats.value.push({ role: "user", text });
  chatInput.value = "";
  let answer =
    "Для подбора кредита укажите цель, сумму и срок в кредитном калькуляторе. Подходящие продукты появятся ниже. Окончательные условия банк определит после проверки заявки.";
  if (/документ|справк|выписк/i.test(text))
    answer =
      "Обычно нужны регистрационные документы, финансовая отчётность и выписка по счёту. Точный список указан в заявке для выбранного продукта. Загрузите PDF, PNG или JPEG до 10 МБ. При залоге понадобятся документы на обеспечение.";
  else if (/статус|заявк|рассмотр/i.test(text))
    answer = user.value
      ? `В кабинете ${activeApplications.value.length} активных заявок. Откройте «Мои кредиты», чтобы посмотреть статус, замечания сотрудника и предложение банка. Если нужно уточнение, исправьте данные и отправьте их повторно.`
      : "Войдите в кабинет и откройте «Мои кредиты». Там появятся ваши заявки, статусы рассмотрения и запросы на уточнение.";
  else if (/ставк|плат[её]ж|процент/i.test(text))
    answer =
      "Предварительный платёж рассчитывается по аннуитетной схеме: равные ежемесячные платежи. Калькулятор показывает базовую ставку продукта. Индивидуальная ставка и доступная сумма появятся в предложении после оценки бизнеса.";
  else if (/подпис|оформ|код/i.test(text))
    answer =
      "После одобрения откройте предложение и график платежей, примите условия, затем проверьте договор. В этом учебном сервисе используется демо-код 123456. Реальная электронная подпись и перевод денег не выполняются.";
  chats.value.push({ role: "assistant", text: answer });
}
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
  if (e.key === "Escape") modal.value = null;
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
          aria-label="Уведомления"
          @click="
            user
              ? (navigate('loans'),
                (filter = 'all'),
                flash(
                  attention.length
                    ? `Требуют внимания: ${attention.length}`
                    : 'Новых уведомлений нет',
                ))
              : askLogin()
          "
        >
          <Icon name="Bell" /><i v-if="attention.length"></i></button
        ><button class="profile-btn" @click="user ? openProfile() : askLogin()">
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
                <span class="count">{{ applications.length }}</span>
              </h2>
              <button class="text-btn" @click="navigate('loans')">
                Все заявки <Icon name="ArrowRight" :size="17" />
              </button>
            </div>
            <template v-if="applications.length"
              ><button
                v-for="a in applications.slice(0, 3)"
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
                  <option value="all">Все статусы</option>
                  <option
                    v-for="(label, key) in statuses"
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
                ><small><span class="live-dot"></span> Справочный режим</small>
              </div>
              <button
                class="icon-btn"
                aria-label="Очистить чат"
                @click="chats = [chats[0]]"
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
                :disabled="!chatInput.trim()"
              >
                <Icon name="Send" :size="19" />
              </button>
            </form>
            <p class="chat-disclaimer">
              Локальный справочный помощник. Генеративная модель не подключена;
              ответы не являются решением банка.
            </p>
          </div>
          <aside class="panel suggestions">
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
    <div v-if="modal" class="modal-backdrop" @click.self="modal = null">
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
                : 'Профиль компании'
        "
        tabindex="-1"
      >
        <button
          class="icon-btn modal-close"
          aria-label="Закрыть"
          @click="modal = null"
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
            ><button class="primary full" :disabled="busy">
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
            >ЗАЯВКА № {{ current.id.slice(0, 8).toUpperCase() }}</span
          >
          <div class="application-heading">
            <h2>{{ purposes[current.purpose] }}</h2>
            <span :class="['status', current.status]">{{
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
                ><label
                  >Платежи по кредитам в месяц, ₽<input
                    :value="financials.monthly_debt_payments"
                    @input="
                      financials.monthly_debt_payments = $event.target.value
                    "
                    type="number"
                    min="0"
                    step="0.01"
                    required /></label
                ><label
                  >Остаток текущего долга, ₽<input
                    :value="financials.outstanding_debt"
                    @input="financials.outstanding_debt = $event.target.value"
                    type="number"
                    min="0"
                    step="0.01"
                    required /></label
                ><label
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
                <label v-if="current.status === 'NEEDS_CLARIFICATION'"
                  >Ответ сотруднику<textarea
                    v-model="comment"
                    minlength="3"
                    maxlength="4000"
                    required
                    placeholder="Какие сведения вы уточнили?"
                  /></label
                ><label class="checkbox-label confirmation"
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
                ><span class="muted small">Черновик сохранится в кабинете</span
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
                  <dt>Кредитные платежи</dt>
                  <dd>{{ money(current.financials.monthly_debt_payments) }}</dd>
                  <dt>Текущий долг</dt>
                  <dd>{{ money(current.financials.outstanding_debt) }}</dd>
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
          <section v-if="isOfficer" class="officer-actions">
            <h3>Обработка заявки</h3>
            <div
              v-for="check in current.checks"
              :key="check.id"
              class="check-result"
            >
              <strong>Проверка от {{ date(check.created_at) }}</strong>
              <pre>{{ JSON.stringify(check.results, null, 2) }}</pre>
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
            <template v-if="current.status === 'PRIMARY_REVIEW'"
              ><label
                >Комментарий / заключение<textarea
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
                  :disabled="busy"
                  @click="action('run-external-checks')"
                >
                  <Icon name="ShieldCheck" :size="17" /> Проверить ФНС и БКИ</button
                ><button
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
                    busy || comment.trim().length < 3 || !current.checks.length
                  "
                  @click="action('pass-to-auto-analysis')"
                >
                  Запустить автоанализ <Icon name="ArrowRight" :size="17" />
                </button></div
            ></template>
            <p
              v-else-if="current.status === 'NEEDS_CLARIFICATION'"
              class="muted"
            >
              Ожидаем ответ предпринимателя.
            </p>
          </section>
          <section v-if="current.decision" class="decision-section">
            <h3>Результат анализа</h3>
            <div class="schedule-summary">
              <div>
                <small>Скоринговый балл</small
                ><strong>{{ current.decision.score }} / 850</strong>
              </div>
              <div>
                <small>Категория риска</small
                ><strong>{{
                  current.decision.risk_category?.replace("CATEGORY_", "")
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
            <details v-if="isOfficer">
              <summary>Факторы оценки</summary>
              <pre>{{ JSON.stringify(current.decision.factors, null, 2) }}</pre>
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
            <details>
              <summary>Проверить сформированный договор</summary>
              <pre>{{ JSON.stringify(current.contract, null, 2) }}</pre>
            </details>
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
                >{{ statuses[event.to_status]
                }}<small>{{ date(event.created_at) }}</small></span
              >
            </div>
          </section>
        </template>
      </section>
    </div>
  </div>
</template>
