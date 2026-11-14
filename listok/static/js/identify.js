/* Сторінка «Визначити»: вибір фото, стиснення, запит до сервера, показ результату. */
(function () {
  "use strict";
  const { el, api, renderSpecimen } = window.Listok;
  const MAX_MB = (window.LISTOK && window.LISTOK.maxUploadMb) || 10;
  const HARD_LIMIT_MB = 40;       // більше — навіть не пробуємо стискати
  const CLIENT_MAX_SIDE = 1600;   // стискаємо в браузері: швидше на мобільному інтернеті
  const REQUEST_TIMEOUT_MS = 90000;

  const $ = (id) => document.getElementById(id);
  const form = $("identify-form"), fileInput = $("file-input"), cameraInput = $("camera-input");
  const dropzone = $("dropzone"), preview = $("preview"), dzEmpty = $("dropzone-empty");
  const submitBtn = $("submit-btn"), fileMeta = $("file-meta"), fileName = $("file-name");
  const states = { empty: $("state-empty"), loading: $("state-loading"), error: $("state-error"), result: $("state-result") };
  const resultArea = $("result-area");

  let current = null;       // { blob, name, previewUrl }
  let inflight = null;      // AbortController
  let timerId = null;

  function show(name) {
    for (const [k, node] of Object.entries(states)) node.hidden = k !== name;
    resultArea.setAttribute("aria-busy", name === "loading" ? "true" : "false");
  }

  // --- Вибір файлу ---------------------------------------------------------------
  $("pick-btn").addEventListener("click", () => fileInput.click());
  $("camera-btn").addEventListener("click", () => cameraInput.click());
  fileInput.addEventListener("change", () => fileInput.files[0] && accept(fileInput.files[0]));
  cameraInput.addEventListener("change", () => cameraInput.files[0] && accept(cameraInput.files[0]));
  $("clear-btn").addEventListener("click", clearFile);
  $("error-new-btn").addEventListener("click", () => fileInput.click());

  ["dragenter", "dragover"].forEach((t) => dropzone.addEventListener(t, (e) => {
    e.preventDefault(); dropzone.classList.add("is-dragover");
  }));
  ["dragleave", "drop"].forEach((t) => dropzone.addEventListener(t, (e) => {
    e.preventDefault(); dropzone.classList.remove("is-dragover");
  }));
  dropzone.addEventListener("drop", (e) => {
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) accept(f);
  });
  // Вставлення зображення з буфера обміну (Ctrl+V) — зручно на ноутбуці.
  window.addEventListener("paste", (e) => {
    const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
    if (item) accept(item.getAsFile());
  });

  function looksLikeImage(f) {
    return (f.type && f.type.startsWith("image/")) || /\.(jpe?g|png|webp|heic|heif|gif|bmp)$/i.test(f.name || "");
  }

  async function accept(file) {
    if (!looksLikeImage(file)) return fail("Непідходящий файл", "Можна завантажувати лише зображення: JPG, PNG, WEBP або HEIC.");
    if (file.size > HARD_LIMIT_MB * 1024 * 1024) return fail("Файл завеликий", `Розмір файлу ${(file.size / 1048576).toFixed(1)} МБ. Максимум — ${MAX_MB} МБ.`);

    let blob = await downscale(file).catch(() => null);
    if (!blob) {
      if (file.size > MAX_MB * 1024 * 1024) return fail("Файл завеликий", `Розмір файлу ${(file.size / 1048576).toFixed(1)} МБ. Максимум — ${MAX_MB} МБ.`);
      blob = file; // браузер не зміг декодувати (напр. HEIC у Chrome) — надішлемо як є, сервер розбереться
    }
    if (current && current.previewUrl) URL.revokeObjectURL(current.previewUrl);
    const previewUrl = URL.createObjectURL(blob);
    current = { blob, name: file.name || "photo.jpg", previewUrl };

    preview.src = previewUrl;
    preview.hidden = false;
    preview.onerror = () => { preview.hidden = true; dzEmpty.hidden = false; }; // HEIC без попереднього перегляду
    dzEmpty.hidden = true;
    dropzone.classList.add("has-image");
    fileName.textContent = `${current.name}, ${Math.round(blob.size / 1024)} КБ`;
    fileMeta.hidden = false;
    submitBtn.disabled = false;
    if (!states.error.hidden || !states.result.hidden) show("empty");
    submitBtn.focus({ preventScroll: true });
  }

  function clearFile() {
    if (current && current.previewUrl) URL.revokeObjectURL(current.previewUrl);
    current = null;
    fileInput.value = ""; cameraInput.value = "";
    preview.hidden = true; preview.removeAttribute("src");
    dzEmpty.hidden = false; dropzone.classList.remove("has-image");
    fileMeta.hidden = true; submitBtn.disabled = true;
    show("empty");
  }

  // Зменшення фото в браузері. Повертає JPEG Blob або null.
  async function downscale(file) {
    if (!("createImageBitmap" in window)) return null;
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, CLIENT_MAX_SIDE / Math.max(bmp.width, bmp.height));
    if (scale === 1 && file.size < 1.5 * 1024 * 1024 && /jpe?g/i.test(file.type)) { bmp.close?.(); return file; }
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bmp.width * scale);
    canvas.height = Math.round(bmp.height * scale);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height); // прозорий PNG -> білий фон
    ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
    bmp.close?.();
    return await new Promise((res) => canvas.toBlob((b) => res(b), "image/jpeg", 0.88));
  }

  // --- Запит ---------------------------------------------------------------------------
  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  $("retry-btn").addEventListener("click", () => run());
  $("cancel-btn").addEventListener("click", () => inflight && inflight.abort());

  function setStep(step) {
    const order = ["upload", "ai", "card"];
    const idx = order.indexOf(step);
    document.querySelectorAll("#loading-steps li").forEach((li, i) => {
      li.classList.toggle("is-done", i < idx);
      li.classList.toggle("is-active", i === idx);
    });
  }

  function startTimer() {
    const t0 = performance.now();
    const out = $("elapsed"), slow = $("slow-hint");
    slow.hidden = true;
    const fmt = new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    timerId = setInterval(() => {
      const s = (performance.now() - t0) / 1000;
      out.textContent = fmt.format(s);
      if (s > 1.2) setStep("ai");
      if (s > 15) slow.hidden = false;
    }, 100);
  }
  function stopTimer() { clearInterval(timerId); timerId = null; }

  async function run() {
    if (!current) { fileInput.click(); return; }
    if (inflight) return;
    const mode = form.querySelector('input[name="mode"]:checked')?.value || "flash";
    const fd = new FormData();
    fd.append("photo", current.blob, current.name.replace(/\.(heic|heif|png|webp|gif|bmp)$/i, ".jpg"));
    fd.append("mode", mode);

    show("loading"); setStep("upload"); startTimer();
    submitBtn.disabled = true;
    if (window.matchMedia("(max-width: 920px)").matches) resultArea.scrollIntoView({ behavior: "smooth", block: "start" });

    inflight = new AbortController();
    const clientT0 = performance.now();
    try {
      const data = await api("/api/identify", { method: "POST", body: fd, timeoutMs: REQUEST_TIMEOUT_MS, signal: inflight.signal });
      setStep("card");
      data.client_ms = Math.round(performance.now() - clientT0);
      renderResult(data);
    } catch (err) {
      if (err.kind === "cancelled") { show("empty"); }
      else showError(err);
    } finally {
      stopTimer(); inflight = null; submitBtn.disabled = !current;
    }
  }

  const ERROR_TITLES = {
    offline: "Немає інтернету",
    network: "Немає зв'язку з сервером",
    client_timeout: "Задовге очікування",
    timeout: "Gemini не відповів вчасно",
    quota: "Перевищено ліміт Gemini API",
    too_large: "Файл завеликий",
    too_small: "Зображення замале",
    bad_file: "Непідходящий файл",
    empty_file: "Порожній файл",
    bad_image: "Не вдалося обробити фото",
    config: "Сервіс не налаштовано",
    auth: "Проблема з ключем API",
    model: "Модель недоступна",
  };

  function fail(title, message) { showError({ kind: "local", message, _title: title }); }

  function showError(err) {
    $("error-title").textContent = err._title || ERROR_TITLES[err.kind] || "Не вдалося визначити рослину";
    $("error-message").textContent = err.message || "Спробуйте ще раз.";
    const det = $("error-detail");
    det.hidden = !err.detail;
    det.textContent = err.detail ? `Технічні деталі: ${err.detail}` : "";
    $("retry-btn").hidden = !current || ["bad_file", "too_large", "too_small", "empty_file", "local"].includes(err.kind);
    show("error");
  }

  function renderResult(data) {
    const box = states.result;
    box.replaceChildren();
    const r = data.result || {};
    let actions = null;
    if (r.is_plant) {
      const saveBtn = el("button", { type: "button", class: "btn btn-primary" }, "Зберегти в мої рослини");
      saveBtn.addEventListener("click", () => save(data, saveBtn));
      const againBtn = el("button", { type: "button", class: "btn btn-ghost", onclick: () => { clearFile(); fileInput.click(); } }, "Інше фото");
      actions = [saveBtn, againBtn];
    } else {
      actions = [el("button", { type: "button", class: "btn btn-primary", onclick: () => fileInput.click() }, "Вибрати інше фото")];
    }
    box.append(renderSpecimen(data, { photoUrl: current ? current.previewUrl : data.thumb_data_url, actions }));
    show("result");
  }

  async function save(data, btn) {
    btn.disabled = true;
    btn.textContent = "Зберігаємо…";
    const { thumb_data_url, ...analysis } = data;
    try {
      await api("/api/plants", { method: "POST", body: { analysis, thumb_data_url }, timeoutMs: 30000 });
      btn.textContent = "Збережено";
      btn.classList.add("is-done");
      btn.after(el("a", { class: "btn btn-ghost", href: "/plants" }, "Відкрити мої рослини"));
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Зберегти в мої рослини";
      const msg = el("p", { class: "notice", role: "alert" }, `Не вдалося зберегти: ${err.message}`);
      btn.closest(".specimen").querySelector(".specimen-foot").before(msg);
      setTimeout(() => msg.remove(), 9000);
    }
  }

  // Розбудити сервер, поки людина вибирає фото (важливо для Render free tier).
  fetch("/healthz", { cache: "no-store" }).catch(() => {});
})();
