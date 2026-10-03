/* Rasiko dashboard: small helpers, charts, live new-order alerts, map editor. No inline scripts (strict CSP). */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "";
  const toastEl = $("#toast");
  const toast = (msg) => {
    if (!toastEl) return;
    toastEl.textContent = msg; toastEl.classList.add("show");
    clearTimeout(toast.t); toast.t = setTimeout(() => toastEl.classList.remove("show"), 2500);
  };

  document.body.addEventListener("htmx:configRequest", (e) => { e.detail.headers["X-CSRFToken"] = csrf(); });
  document.addEventListener("change", (e) => {
    if (e.target.matches("[data-autosubmit]")) e.target.form.submit();
    if (e.target.matches("[data-check-all]")) $$('input[name="ids"]').forEach((c) => (c.checked = e.target.checked));
  });
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) e.preventDefault();
    if (f.matches("[data-bulk]") && $('select[name="action"]', f).value === "delete" && !confirm("Remove the selected products from the shop?")) e.preventDefault();
  });
  document.addEventListener("click", (e) => {
    const c = e.target.closest("[data-confirm-click]");
    if (c && !confirm(c.dataset.confirmClick)) { e.preventDefault(); return; }
    const copy = e.target.closest("[data-copy]");
    if (copy) { navigator.clipboard && navigator.clipboard.writeText(copy.dataset.copy); toast("Copied"); }
    if (e.target.closest("[data-print]")) window.print();
  });
  $$("[data-autoscroll]").forEach((el) => (el.scrollTop = el.scrollHeight));

  // ---- Drag to reorder (product photos, hero slides) ------------------------
  const sortable = (box, onDone) => {
    let dragged = null;
    box.addEventListener("dragstart", (e) => { dragged = e.target.closest(".sortable-item"); dragged && dragged.classList.add("dragging"); });
    box.addEventListener("dragend", () => { if (dragged) { dragged.classList.remove("dragging"); dragged = null; onDone(); } });
    box.addEventListener("dragover", (e) => {
      e.preventDefault();
      const over = e.target.closest(".sortable-item");
      if (!dragged || !over || over === dragged) return;
      const r = over.getBoundingClientRect();
      const after = box.dataset.sortable ? e.clientX > r.left + r.width / 2 : e.clientY > r.top + r.height / 2;
      over.parentNode.insertBefore(dragged, after ? over.nextSibling : over);
    });
  };
  $$("[data-sortable]").forEach((box) => {
    const input = $(`input[name="${box.dataset.sortable}"]`);
    sortable(box, () => { input.value = $$(".sortable-item", box).map((i) => i.dataset.id).join(","); });
  });
  $$("[data-sortable-post]").forEach((box) => {
    sortable(box, async () => {
      const fd = new FormData(); fd.append("order", $$(".sortable-item", box).map((i) => i.dataset.id).join(","));
      const r = await fetch(box.dataset.sortablePost, { method: "POST", body: fd, headers: { "X-CSRFToken": csrf() }, credentials: "same-origin" });
      toast(r.ok ? "Order saved" : "Could not save the order");
    });
  });

  // ---- Hero slide preview before upload -------------------------------------
  $$("input[data-preview]").forEach((inp) => inp.addEventListener("change", () => {
    const f = inp.files[0]; if (!f) return;
    const box = $(`[data-preview-box="${inp.dataset.preview}"]`);
    const img = new Image(); img.alt = ""; img.src = URL.createObjectURL(f);
    const fit = $("#id_fit"); img.style.objectFit = inp.dataset.preview === "mobile" ? "cover" : (fit && fit.value === "cover" ? "cover" : "contain");
    img.onload = () => { if (img.naturalWidth < 1200 && inp.dataset.preview === "desktop") toast(`This photo is only ${img.naturalWidth}px wide; 1920px looks sharper.`); };
    box.innerHTML = ""; box.appendChild(img);
  }));
  const fx = $("#id_focal_x"), fy = $("#id_focal_y");
  [fx, fy].forEach((el) => el && el.addEventListener("input", () => $$("[data-preview-box] img").forEach((i) => (i.style.objectPosition = `${fx.value}% ${fy.value}%`))));
  const fitSel = $("#id_fit");
  fitSel && fitSel.addEventListener("change", () => { const i = $('[data-preview-box="desktop"] img'); if (i) i.style.objectFit = fitSel.value === "cover" ? "cover" : "contain"; });

  // ---- Charts ---------------------------------------------------------------
  const dataEl = $("#chart-data");
  if (dataEl && window.Chart) {
    const d = JSON.parse(dataEl.textContent);
    const P = { green: "#2FA05A", deep: "#1B6E42", orange: "#FB8C00", red: "#E53935", gold: "#FFC107", maroon: "#7A1E2C", brown: "#6D4C41", pink: "#F48FB1" };
    Chart.defaults.color = "#6D4C41"; Chart.defaults.font.family = "Nunito Sans, system-ui, sans-serif"; Chart.defaults.borderColor = "#F3E3CC";
    const rupee = (v) => "₹" + Number(v).toLocaleString("en-IN");
    const make = (name, cfg) => { const c = $(`[data-chart="${name}"]`); if (c) new Chart(c, { ...cfg, options: { maintainAspectRatio: false, ...cfg.options } }); };
    make("daily", { type: "bar", data: { labels: d.daily.labels, datasets: [
      { type: "line", label: "Sales", data: d.daily.revenue, borderColor: P.green, backgroundColor: "rgba(47,160,90,.12)", fill: true, tension: .3, yAxisID: "y" },
      { type: "bar", label: "Orders", data: d.daily.orders, backgroundColor: "rgba(251,140,0,.55)", borderRadius: 6, yAxisID: "y1" }] },
      options: { scales: { y: { ticks: { callback: rupee } }, y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { precision: 0 } } } } });
    make("top", { type: "bar", data: { labels: d.top.labels, datasets: [{ label: "Sales", data: d.top.values, backgroundColor: P.orange, borderRadius: 6 }] },
      options: { indexAxis: "y", plugins: { legend: { display: false } }, scales: { x: { ticks: { callback: rupee } } } } });
    make("cats", { type: "doughnut", data: { labels: d.cats.labels, datasets: [{ data: d.cats.values, backgroundColor: [P.green, P.orange, P.red, P.gold, P.maroon, P.deep, P.pink, P.brown] }] },
      options: { plugins: { legend: { position: "right" } } } });
  }

  // ---- Live alerts: new orders ring a bell, new chat messages show a toast ----
  if (document.body.dataset.ws) {
    let ctx;
    const ding = () => {
      try {
        ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
        [880, 1320].forEach((f, i) => {
          const o = ctx.createOscillator(), g = ctx.createGain();
          o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
          g.gain.setValueAtTime(0.25, ctx.currentTime + i * 0.18); g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.18 + 0.35);
          o.start(ctx.currentTime + i * 0.18); o.stop(ctx.currentTime + i * 0.18 + 0.4);
        });
      } catch (e) { /* sound blocked until the page is clicked once */ }
    };
    document.addEventListener("click", () => { if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) {} } }, { once: true });
    let tries = 0;
    const connect = () => {
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/dashboard/`);
      ws.onopen = () => (tries = 0);
      ws.onmessage = (ev) => {
        const m = JSON.parse(ev.data);
        if (m.type === "new_order") {
          ding(); toast("New order received!");
          document.title = "● New order · " + document.title.replace(/^● New order · /, "");
          if (location.pathname.endsWith("/orders/") || $("#recent-orders")) setTimeout(() => location.reload(), 1500);
        } else if (m.type === "chat_message") {
          toast("Help chat: " + m.text);
          if ($("#support-list") || $("[data-autoscroll]")) setTimeout(() => location.reload(), 800);
        }
      };
      ws.onclose = (e) => { if (e.code !== 4403 && tries < 20) setTimeout(connect, Math.min(30000, 1000 * 2 ** tries++)); };
    };
    if ("WebSocket" in window) connect();
  }

  // ---- Delivery area map editor ---------------------------------------------
  const mapEl = $("#area-map");
  if (mapEl && window.L) {
    const lat = $("#id_store_lat"), lng = $("#id_store_lng"), radius = $("#id_radius_km"), poly = $("#id_polygon_json");
    const start = [Number(lat.value), Number(lng.value)];
    const map = L.map(mapEl).setView(start, 12);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
    const icon = L.divIcon({ className: "", html: '<svg viewBox="0 0 24 24" width="36" height="36" style="color:#E53935"><path d="M12 22s8-7 8-13a8 8 0 0 0-16 0c0 6 8 13 8 13Z" fill="currentColor"/><circle cx="12" cy="9" r="3" fill="#fff"/></svg>', iconSize: [36, 36], iconAnchor: [18, 34] });
    const shop = L.marker(start, { draggable: true, icon, title: "Shop" }).addTo(map);
    const circle = L.circle(start, { radius: Number(radius.value) * 1000, color: "#2FA05A", weight: 2, fillOpacity: 0.05 }).addTo(map);
    let pts = []; try { pts = JSON.parse(poly.value || "[]"); } catch (e) { pts = []; }
    const shape = L.polygon(pts, { color: "#FB8C00", weight: 2, fillOpacity: 0.08 }).addTo(map);
    const save = () => { poly.value = JSON.stringify(pts); shape.setLatLngs(pts); };
    shop.on("dragend", () => { const p = shop.getLatLng(); lat.value = p.lat.toFixed(6); lng.value = p.lng.toFixed(6); circle.setLatLng(p); });
    radius.addEventListener("input", () => circle.setRadius(Number(radius.value || 0) * 1000));
    map.on("click", (e) => { pts.push([Number(e.latlng.lat.toFixed(6)), Number(e.latlng.lng.toFixed(6))]); save(); });
    $("[data-poly-undo]").addEventListener("click", () => { pts.pop(); save(); });
    $("[data-poly-clear]").addEventListener("click", () => { pts = []; save(); });
    if (pts.length > 2) map.fitBounds(shape.getBounds(), { padding: [20, 20] });
  }
})();
