/* Спільні функції: мережа, форматування і побудова картки рослини. */
(function () {
  "use strict";

  // --- Банер «немає інтернету» -------------------------------------------
  const banner = document.getElementById("offline-banner");
  function syncOnline() { if (banner) banner.hidden = navigator.onLine; }
  window.addEventListener("online", syncOnline);
  window.addEventListener("offline", syncOnline);
  syncOnline();

  // --- Утиліти DOM ---------------------------------------------------------
  // el("div", {class: "x"}, "текст", child) — створює елемент без innerHTML (безпечно для тексту від ШІ).
  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v === null || v === undefined || v === false) continue;
        if (k === "class") node.className = v;
        else if (k === "html") node.innerHTML = v; // лише для наших власних SVG-іконок
        else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
        else node.setAttribute(k, v === true ? "" : v);
      }
    }
    for (const c of children.flat()) {
      if (c === null || c === undefined || c === false) continue;
      node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return node;
  }

  const nf1 = new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat("uk-UA");
  const seconds = (ms) => nf1.format((ms || 0) / 1000) + " с";
  function usd(v) {
    if (v === null || v === undefined) return "—";
    if (v === 0) return "$0";
    if (v < 0.0001) return "<$0,0001";
    return "$" + new Intl.NumberFormat("uk-UA", { maximumSignificantDigits: 2 }).format(v);
  }
  function date(iso) {
    try {
      return new Date(iso).toLocaleDateString("uk-UA", { day: "numeric", month: "long", year: "numeric" });
    } catch (_) { return ""; }
  }

  // --- Мережа: fetch з таймаутом і зрозумілими помилками --------------------
  class ApiError extends Error {
    constructor(message, kind, status, detail) {
      super(message); this.kind = kind; this.status = status; this.detail = detail;
    }
  }

  async function api(url, { method = "GET", body, timeoutMs = 20000, signal } = {}) {
    const ctrl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, timeoutMs);
    if (signal) signal.addEventListener("abort", () => ctrl.abort(), { once: true });
    let res;
    try {
      const opts = { method, signal: ctrl.signal, headers: {} };
      if (body instanceof FormData) opts.body = body;
      else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
      res = await fetch(url, opts);
    } catch (e) {
      clearTimeout(timer);
      if (e.name === "AbortError") {
        if (timedOut) throw new ApiError(
          `Сервер не відповів за ${Math.round(timeoutMs / 1000)} секунд. Якщо сервіс щойно запустився, зачекайте хвилину і спробуйте ще раз.`,
          "client_timeout", 0);
        throw new ApiError("Скасовано.", "cancelled", 0);
      }
      if (!navigator.onLine) throw new ApiError("Немає з'єднання з інтернетом. Перевірте Wi-Fi або мобільні дані.", "offline", 0);
      throw new ApiError("Не вдалося з'єднатися з сервером. Перевірте інтернет або спробуйте трохи пізніше.", "network", 0);
    }
    clearTimeout(timer);
    let data = null;
    try { data = await res.json(); } catch (_) { /* не JSON — напр. сторінка помилки хостингу */ }
    if (!res.ok || !data || data.ok === false) {
      if (data && data.error) throw new ApiError(data.error, data.kind || "server", res.status, data.detail);
      if (res.status === 413) throw new ApiError("Файл завеликий для сервера.", "too_large", 413);
      throw new ApiError(`Сервер тимчасово недоступний (код ${res.status}). Спробуйте за хвилину.`, "server", res.status);
    }
    return data;
  }

  // --- Іконки ---------------------------------------------------------------
  const ICONS = {
    watering: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M16 4c5 7 8 11.5 8 15.5A8 8 0 0 1 8 19.5C8 15.5 11 11 16 4Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12.5 20.5a3.5 3.5 0 0 0 3.5 3.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    light: '<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="5.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M16 3v4M16 25v4M3 16h4M25 16h4M6.8 6.8l2.8 2.8M22.4 22.4l2.8 2.8M6.8 25.2l2.8-2.8M22.4 9.6l2.8-2.8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    temperature: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M13 18.5V7a3 3 0 0 1 6 0v11.5a6 6 0 1 1-6 0Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><circle cx="16" cy="23" r="2.2" fill="currentColor"/><path d="M16 21V11" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    repotting: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M7 15h18l-2.2 12H9.2Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M5.5 15h21" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><path d="M16 15V9m0 0c0-3 2-5 5.5-5 0 3-2 5-5.5 5Zm0 0c0-2.5-1.8-4-4.5-4 0 2.5 1.8 4 4.5 4Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    humidity: '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 12c3-2 5-2 8 0s5 2 8 0 5-2 6-1M5 18c3-2 5-2 8 0s5 2 8 0 5-2 6-1M5 24c3-2 5-2 8 0s5 2 8 0 5-2 6-1" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    cat: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 4l3 4h8l3-4v9a7 7 0 0 1-14 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="9.5" cy="12.5" r="1" fill="currentColor"/><circle cx="14.5" cy="12.5" r="1" fill="currentColor"/></svg>',
    dog: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 6h10l3 3-2 4v2a6 6 0 0 1-12 0v-2L4 9Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="9.5" cy="12" r="1" fill="currentColor"/><circle cx="14.5" cy="12" r="1" fill="currentColor"/><path d="M11 16h2" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
  };

  const HEALTH = {
    healthy: ["chip-ok", "Здорова на вигляд"],
    problems: ["chip-warn", "Є ознаки проблем"],
    unknown: ["chip-neutral", "Стан не визначено"],
  };
  const SEVERITY = { low: "легка", medium: "помірна", high: "серйозна" };
  const TOX = { toxic: "токсична", mild: "слабко токсична", non_toxic: "безпечна", unknown: "немає даних" };
  const CARE = [
    ["watering", "Полив"], ["light", "Світло"], ["temperature", "Температура"],
    ["repotting", "Пересадка"], ["humidity", "Вологість"],
  ];

  // --- Картка-етикетка рослини -----------------------------------------------
  // data — відповідь /api/identify або запис із «Моїх рослин» (у нормалізованому вигляді).
  function renderSpecimen(data, opts = {}) {
    const r = data.result || {};
    const photo = opts.photoUrl;

    if (!r.is_plant) {
      return el("article", { class: "specimen" },
        el("div", { class: "not-plant" },
          el("h2", { class: "label-name" }, "На фото не знайдено рослину"),
          el("p", { class: "muted" }, r.photo_tip || "Сфотографуйте рослину або листок ближче, при денному світлі."),
          opts.actions || null));
    }

    const conf = Math.max(0, Math.min(100, Number(r.confidence) || 0));
    const health = HEALTH[r.health_status] || HEALTH.unknown;

    const top = el("div", { class: "specimen-top" },
      el("div", { class: "specimen-photo" }, photo ? el("img", { src: photo, alt: `Фото: ${r.common_name_uk || "рослина"}` }) : null),
      el("div", { class: "specimen-label" },
        el("div", { class: "label-frame" },
          r.family ? el("p", { class: "label-family" }, r.family) : null,
          el("h2", { class: "label-name", id: opts.titleId || null }, r.common_name_uk || "Невідома рослина"),
          r.latin_name ? el("p", { class: "label-latin" }, r.latin_name) : null,
          el("div", { class: "confidence" + (conf < 60 ? " is-low" : "") },
            el("div", { class: "confidence-track", role: "img", "aria-label": `Впевненість ${conf}%` },
              el("div", { class: "confidence-fill", style: `width:${conf}%` })),
            el("span", null, `впевненість ${conf}%`))),
        r.description ? el("p", { class: "label-desc" }, r.description) : null,
        r.photo_tip ? el("p", { class: "photo-tip" }, r.photo_tip) : null));

    // Стан
    const problems = Array.isArray(r.problems) ? r.problems : [];
    const healthSec = el("section", null,
      el("h3", { class: "section-title" }, "Стан рослини", el("span", { class: "chip " + health[0] }, health[1])),
      problems.length
        ? el("ul", { class: "problems" }, problems.map((p) =>
            el("li", { class: `problem sev-${p.severity}` },
              el("div", { class: "problem-name" }, p.name,
                el("span", { class: "chip " + (p.severity === "high" ? "chip-bad" : "chip-warn") }, SEVERITY[p.severity] || p.severity)),
              p.signs ? el("p", { class: "problem-signs" }, p.signs) : null,
              p.what_to_do ? el("p", { class: "problem-fix" }, el("strong", null, "Що робити: "), p.what_to_do) : null)))
        : el("p", { class: "no-problems" }, "Видимих ознак хвороб, шкідників чи неправильного догляду не знайдено."));

    // Догляд
    const care = r.care || {};
    const careSec = el("section", null,
      el("h3", { class: "section-title" }, "Догляд"),
      el("dl", { class: "care-grid" }, CARE.filter(([k]) => care[k]).map(([k, label]) =>
        el("div", { class: "care-item", html: ICONS[k] }, el("dt", null, label), el("dd", null, care[k])))));
    // html: ICONS + діти: el() додає дітей після innerHTML — так іконка стоїть першою.

    // Токсичність
    const tox = r.toxicity || {};
    const toxSec = el("section", null,
      el("h3", { class: "section-title" }, "Для домашніх тварин"),
      el("div", { class: "tox-row" },
        el("span", { class: `tox-pill tox-${tox.cats || "unknown"}`, html: ICONS.cat }, `Котам: ${TOX[tox.cats] || TOX.unknown}`),
        el("span", { class: `tox-pill tox-${tox.dogs || "unknown"}`, html: ICONS.dog }, `Собакам: ${TOX[tox.dogs] || TOX.unknown}`)),
      tox.note ? el("p", { class: "tox-note" }, tox.note) : null);

    const alts = Array.isArray(r.alternatives) ? r.alternatives.filter((a) => a && a.latin_name) : [];
    const altSec = alts.length ? el("section", null,
      el("h3", { class: "section-title" }, "Схожі види"),
      el("ul", { class: "alts" }, alts.map((a) => el("li", null, `${a.common_name_uk} `, el("i", null, a.latin_name), ` — ${a.confidence}%`)))) : null;

    // Технічні дані запиту
    const meta = el("dl", { class: "meta" },
      metaItem("Модель", data.model || "—"),
      metaItem("Час відповіді", data.cached ? "з кешу" : seconds(data.latency_ms)),
      data.tokens ? metaItem("Токени", nf0.format(data.tokens.total || 0)) : null,
      metaItem("Ціна на платному рівні", "≈ " + usd(data.cost_usd_paid_tier ?? data.cost_usd)),
      opts.savedAt ? metaItem("Збережено", date(opts.savedAt)) : null);

    const notices = [];
    if (data.mock) notices.push(el("p", { class: "notice" }, "Демо-відповідь: Gemini не викликався."));
    if (data.cached) notices.push(el("p", { class: "notice notice-info" }, "Це фото вже аналізувалося, тому результат узято з кешу сервера. Квоту Gemini не витрачено."));
    if (data.fallback_used) notices.push(el("p", { class: "notice" }, `Основна модель була недоступна або вичерпала ліміт, тому відповідь дала запасна: ${data.model}.`));

    return el("article", { class: "specimen" },
      top,
      el("div", { class: "specimen-body" }, healthSec, careSec, toxSec, altSec),
      notices,
      el("footer", { class: "specimen-foot" }, meta, opts.actions ? el("div", { class: "foot-actions" }, opts.actions) : null));
  }

  function metaItem(k, v) { return el("div", null, el("dt", null, k + ":"), el("dd", null, v)); }

  window.Listok = { el, api, ApiError, renderSpecimen, seconds, usd, date, nf0, HEALTH, TOX };
})();
