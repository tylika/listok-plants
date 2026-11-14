/* Сторінка «Мої рослини»: список, статистика, перегляд і видалення. */
(function () {
  "use strict";
  const { el, api, renderSpecimen, seconds, date, HEALTH } = window.Listok;
  const $ = (id) => document.getElementById(id);
  const grid = $("plant-grid"), dialog = $("plant-dialog"), dialogBody = $("dialog-body");
  let items = [];
  let filter = "all";

  async function load() {
    $("plants-loading").hidden = false;
    $("plants-error").hidden = true;
    try {
      const data = await api("/api/plants", { timeoutMs: 70000 });
      items = data.items || [];
      renderStats(data.stats);
      render();
    } catch (err) {
      $("plants-error-msg").textContent = err.message;
      $("plants-error").hidden = false;
    } finally {
      $("plants-loading").hidden = true;
    }
  }
  $("plants-retry").addEventListener("click", load);

  function renderStats(s) {
    const has = s && s.total > 0;
    $("stats").hidden = !has;
    $("filters").hidden = !has;
    $("health-bar").hidden = !has;
    $("plants-empty").hidden = has;
    if (!has) return;
    $("st-total").textContent = s.total;
    $("st-problems").textContent = s.with_problems;
    $("st-healthy").textContent = s.healthy;
    $("st-toxic").textContent = s.toxic_to_pets;
    $("st-latency").textContent = s.avg_latency_ms ? seconds(s.avg_latency_ms) : "—";
    $("hb-ok").style.width = (100 * s.healthy / s.total) + "%";
    $("hb-warn").style.width = (100 * s.with_problems / s.total) + "%";
  }

  document.querySelectorAll(".seg").forEach((b) => b.addEventListener("click", () => {
    filter = b.dataset.filter;
    document.querySelectorAll(".seg").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    render();
  }));

  function render() {
    const list = items.filter((p) => filter === "all" || (filter === "problems" ? p.has_problems : p.is_toxic_to_pets));
    grid.replaceChildren(...list.map(tile));
    if (items.length && !list.length) {
      grid.append(el("li", { class: "plants-empty", style: "grid-column:1/-1" }, "У цьому фільтрі рослин немає."));
    }
  }

  function tile(p) {
    const h = HEALTH[p.has_problems ? "problems" : (p.health_status || "healthy")] || HEALTH.unknown;
    const chips = [el("span", { class: "chip " + h[0] }, p.has_problems ? "Є проблеми" : h[1])];
    if (p.is_toxic_to_pets) chips.push(el("span", { class: "chip chip-bad" }, "Небезпечна для тварин"));

    const open = el("button", { type: "button", class: "tile-open", "aria-label": `Відкрити картку: ${p.common_name}` },
      el("div", { class: "tile-photo" }, p.thumb_url ? el("img", { src: p.thumb_url, alt: "", loading: "lazy" }) : null),
      el("div", { class: "tile-body" },
        el("span", { class: "tile-name" }, p.common_name),
        p.latin_name ? el("span", { class: "tile-latin" }, p.latin_name) : null,
        el("div", { class: "tile-chips" }, chips)));
    open.addEventListener("click", () => openDialog(p));

    const foot = el("div", { class: "tile-foot" }, el("span", null, date(p.created_at)));
    const del = el("button", { type: "button", class: "del-btn" }, "Видалити");
    del.addEventListener("click", () => confirmDelete(p, foot, del));
    foot.append(del);
    return el("li", { class: "plant-tile" }, open, foot);
  }

  // Двоетапне видалення без системного вікна confirm().
  function confirmDelete(p, foot, delBtn) {
    const box = el("span", { class: "del-confirm" },
      el("button", { type: "button", class: "del-btn yes" }, "Так, видалити"),
      el("button", { type: "button", class: "del-btn" }, "Ні"));
    const [yes, no] = box.children;
    delBtn.replaceWith(box);
    no.focus();
    no.addEventListener("click", () => box.replaceWith(delBtn));
    yes.addEventListener("click", async () => {
      yes.disabled = no.disabled = true; yes.textContent = "Видаляємо…";
      try {
        await api(`/api/plants/${p.id}`, { method: "DELETE" });
        await load();
      } catch (err) {
        box.replaceWith(delBtn);
        delBtn.textContent = "Помилка, ще раз?";
        delBtn.title = err.message;
      }
    });
  }

  function openDialog(p) {
    const data = {
      result: p.result || {},
      model: p.model,
      latency_ms: p.latency_ms,
      cost_usd_paid_tier: p.cost_usd === null || p.cost_usd === undefined ? null : Number(p.cost_usd),
    };
    dialogBody.replaceChildren(renderSpecimen(data, { photoUrl: p.thumb_url, savedAt: p.created_at, titleId: "dialog-title" }));
    if (typeof dialog.showModal === "function") dialog.showModal(); else dialog.setAttribute("open", "");
    dialog.scrollTop = 0;
  }
  $("dialog-close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });

  load();
})();
