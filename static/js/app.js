/* Rasiko storefront: cart controls, drawer, slider, gallery, chat widget, small helpers.
   Vanilla JS so it works under a strict Content-Security-Policy (no eval, no inline handlers). */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const filters = $(".filters-panel");
  if (filters) {
    const desktop = window.matchMedia("(min-width: 1000px)");
    const syncFilters = () => { filters.open = desktop.matches; };
    syncFilters();
    desktop.addEventListener("change", syncFilters);
  }
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "";
  const post = (url, data) =>
    fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf(), Accept: "application/json", "X-Requested-With": "fetch" },
      body: data,
      credentials: "same-origin",
    });
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ---- Toast ---------------------------------------------------------------
  const toastEl = $("#toast");
  let toastTimer;
  const toast = (msg) => {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("show"), 2000);
  };

  // ---- Cart state ----------------------------------------------------------
  let cartState = {};
  try { cartState = JSON.parse(($("#cart-state") || {}).textContent || "{}") || {}; } catch (e) { cartState = {}; }
  const countEl = $("#cartCount");
  const setCount = (n) => {
    if (!countEl) return;
    countEl.textContent = n;
    countEl.hidden = !n;
    countEl.classList.remove("bump"); void countEl.offsetWidth; countEl.classList.add("bump");
  };
  const stepper = (name, q) =>
    `<div class="qty"><button type="button" data-d="-1" aria-label="Remove one box of ${esc(name)}">−</button><span aria-live="polite">${q}</span><button type="button" data-d="1" aria-label="Add one more box of ${esc(name)}">+</button></div>`;
  const addBtn = (name) => `<button class="add" type="button" aria-label="Add a box of ${esc(name)} to cart">Add box</button>`;
  const renderCtl = (ctl) => {
    const q = cartState[ctl.dataset.key] || 0;
    if (ctl.dataset.reload !== undefined) return;
    if (ctl.querySelector("a.add")) return; // out of stock "Notify me"
    ctl.innerHTML = q > 0 ? stepper(ctl.dataset.name, q) : addBtn(ctl.dataset.name);
  };
  $$(".buy__ctl").forEach(renderCtl);

  const changeQty = async (ctl, delta, mode = "add") => {
    const fd = new FormData();
    fd.append("key", ctl.dataset.key);
    fd.append("qty", delta);
    fd.append("mode", mode);
    const res = await post("/cart/update/", fd);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { toast(data.error || "Something went wrong"); return; }
    cartState[ctl.dataset.key] = data.qty;
    setCount(data.count);
    if (ctl.dataset.reload !== undefined) { refreshDrawerOrPage(); return; }
    $$(`.buy__ctl[data-key="${CSS.escape(ctl.dataset.key)}"]`).forEach(renderCtl);
    if (delta > 0) toast(data.message);
  };

  document.addEventListener("click", (e) => {
    const ctl = e.target.closest(".buy__ctl");
    if (ctl) {
      if (e.target.closest("button.add")) { changeQty(ctl, 1); return; }
      const b = e.target.closest("[data-d]");
      if (b) { changeQty(ctl, Number(b.dataset.d)); return; }
    }
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      navigator.clipboard && navigator.clipboard.writeText(copy.dataset.copy).catch(() => {});
      toast(`Coupon ${copy.dataset.copy} copied`);
    }
    if (e.target.closest("[data-open-cart]") && !e.metaKey && !e.ctrlKey) { e.preventDefault(); openDrawer(); }
    if (e.target.closest("[data-close-drawer]")) closeDrawer();
  });

  // Variant dropdown on product cards
  document.addEventListener("change", (e) => {
    const sel = e.target.closest("[data-variant-select]");
    if (sel) {
      const card = sel.closest(".card");
      const opt = sel.selectedOptions[0];
      const ctl = $(".buy__ctl", card);
      $("span[data-price]", card).textContent = opt.dataset.price;
      const per = $("div[data-per]", card);
      if (per) per.textContent = opt.dataset.per ? `${opt.dataset.per} per bottle` : "";
      const mrp = $("span[data-mrp]", card);
      if (mrp) mrp.textContent = opt.dataset.mrp || "";
      ctl.dataset.key = `v:${opt.value}`;
      if (opt.dataset.stock === "1") renderCtl(ctl);
      else ctl.innerHTML = `<button class="add" type="button" disabled>Out</button>`;
    }
    if (e.target.matches("[data-autosubmit]")) e.target.form.submit();
  });

  // ---- Drawer --------------------------------------------------------------
  const drawer = $("#drawer");
  const openDrawer = async () => {
    const res = await fetch("/cart/drawer/", { credentials: "same-origin" });
    drawer.innerHTML = await res.text();
    document.body.style.overflow = "hidden";
    const close = $("[data-close-drawer].round", drawer);
    close && close.focus();
  };
  const closeDrawer = () => { drawer.innerHTML = ""; document.body.style.overflow = ""; };
  const refreshDrawerOrPage = () => (drawer && drawer.innerHTML.trim() ? openDrawer() : location.reload());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && drawer && drawer.innerHTML) closeDrawer(); });

  // ---- Product page --------------------------------------------------------
  const pdp = $("[data-pdp-form]");
  if (pdp) {
    const sync = () => {
      const r = $("input[name=key]:checked", pdp);
      if (!r) return;
      $("[data-pdp-price]", pdp).textContent = r.dataset.price;
      $("[data-pdp-mrp]", pdp).textContent = r.dataset.mrp ? `MRP ${r.dataset.mrp}` : "";
      const per = $("[data-pdp-per]", pdp);
      if (per) per.textContent = r.dataset.per ? `${r.dataset.per} per bottle · ` : "";
      $("[data-pdp-save]", pdp).textContent = r.dataset.save ? `You save ${r.dataset.save} (Rasiko price vs MRP)` : "";
      const inStock = r.dataset.stock === "1";
      $$("button[type=submit]", pdp).forEach((b) => (b.disabled = !inStock));
      $("[data-pdp-stock]", pdp).innerHTML = !inStock
        ? '<span class="chip chip--red">Out of stock</span>'
        : r.dataset.low ? `<span class="chip chip--orange">Only ${esc(r.dataset.low)} boxes left</span>` : '<span class="chip chip--green">In stock</span>';
    };
    pdp.addEventListener("change", sync);
    pdp.addEventListener("submit", async (e) => {
      if (e.submitter && e.submitter.name === "next") return; // Buy now: normal POST, then checkout
      e.preventDefault();
      const r = $("input[name=key]:checked", pdp);
      const fd = new FormData(); fd.append("key", r.value); fd.append("qty", 1);
      const res = await post(pdp.action, fd);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { toast(data.error || "Could not add"); return; }
      cartState[r.value] = data.qty; setCount(data.count); toast(data.message);
    });
  }
  const gallery = $("[data-gallery]");
  if (gallery) {
    gallery.addEventListener("click", (e) => {
      const t = e.target.closest("[data-src]");
      if (!t) return;
      $("[data-gallery-main]", gallery).src = t.dataset.src;
      $$("[data-src]", gallery).forEach((b) => b.setAttribute("aria-pressed", b === t));
    });
  }

  // ---- Hero slider: autoplay, pause on hover/focus, swipe, dots, arrows ----
  $$("[data-slider]").forEach((hero) => {
    const track = $(".hero__track", hero);
    const slides = [...track.children];
    if (slides.length < 2) return;
    const dotsEl = $(".hero__dots", hero);
    let idx = 0, timer = null;
    dotsEl.innerHTML = slides.map((_, i) => `<button type="button" role="tab" aria-label="Slide ${i + 1}" aria-selected="${i === 0}"></button>`).join("");
    const dots = [...dotsEl.children];
    const go = (i) => {
      idx = (i + slides.length) % slides.length;
      track.style.transform = `translateX(${-idx * 100}%)`;
      slides.forEach((s, j) => {
        s.setAttribute("aria-hidden", j !== idx);
        $$("a,button", s).forEach((a) => (a.tabIndex = j === idx ? 0 : -1));
      });
      dots.forEach((d, j) => d.setAttribute("aria-selected", j === idx));
    };
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const stop = () => clearInterval(timer);
    const play = () => { if (!reduce) { stop(); timer = setInterval(() => go(idx + 1), 5500); } };
    dots.forEach((d, i) => d.addEventListener("click", () => { go(i); play(); }));
    $(".hero__arrow--prev", hero).addEventListener("click", () => { go(idx - 1); play(); });
    $(".hero__arrow--next", hero).addEventListener("click", () => { go(idx + 1); play(); });
    hero.addEventListener("mouseenter", stop); hero.addEventListener("mouseleave", play);
    hero.addEventListener("focusin", stop); hero.addEventListener("focusout", play);
    let x0 = null;
    hero.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; stop(); }, { passive: true });
    hero.addEventListener("touchend", (e) => {
      if (x0 === null) return;
      const dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 40) go(idx + (dx < 0 ? 1 : -1));
      x0 = null; play();
    });
    go(0); play();
  });

  // ---- Reveal on scroll ------------------------------------------------------
  const io = "IntersectionObserver" in window && new IntersectionObserver((entries) => {
    entries.forEach((en) => { if (en.isIntersecting) { en.target.classList.add("in"); io.unobserve(en.target); } });
  }, { rootMargin: "0px 0px -40px 0px" });
  $$(".reveal").forEach((el) => (io ? io.observe(el) : el.classList.add("in")));

  // ---- Forms: confirm, prevent double submit, auto refresh -----------------
  document.addEventListener("submit", (e) => {
    const f = e.target;
    if (f.dataset.confirm && !confirm(f.dataset.confirm)) { e.preventDefault(); return; }
    const once = $("[data-once]", f);
    if (once) setTimeout(() => { once.disabled = true; once.textContent = "Placing order…"; }, 0);
  });
  const auto = $("[data-autorefresh]");
  if (auto) setTimeout(() => location.reload(), Number(auto.dataset.autorefresh) * 1000);

  // Close search suggestions on outside click
  document.addEventListener("click", (e) => { const s = $("#suggest"); if (s && !e.target.closest(".search")) s.innerHTML = ""; });

  // ---- Help chat widget (South-East) ---------------------------------------
  const box = $("#chatbox");
  if (box) {
    const msgs = $(".chatbox__msgs", box);
    const form = $(".chatbox__form", box);
    let last = 0, mode = "bot", pollTimer = null;
    const lang = document.documentElement.lang || "en";
    const add = (m) => {
      if (m.id && m.id <= last) return;
      if (m.id) last = m.id;
      const d = document.createElement("div");
      d.className = `bubble bubble--${m.role}`;
      d.textContent = m.text;
      msgs.appendChild(d);
      msgs.scrollTop = msgs.scrollHeight;
    };
    const apply = (data) => { (data.messages || []).forEach(add); mode = data.mode || mode; schedule(); };
    const schedule = () => { clearTimeout(pollTimer); if (!box.hidden && mode === "human") pollTimer = setTimeout(poll, 4000); };
    const poll = async () => { const r = await fetch(`/help/chat/poll/?after=${last}`, { credentials: "same-origin" }); apply(await r.json()); };
    const json = (url, body) => fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body) });
    const open = () => { box.hidden = false; $("textarea,input", form).focus(); if (!last) poll(); schedule(); };
    $$("[data-chat-open]").forEach((b) => b.addEventListener("click", open));
    $("[data-chat-close]", box).addEventListener("click", () => { box.hidden = true; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = $("[name=text]", form);
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      const mine = document.createElement("div"); mine.className = "bubble bubble--user"; mine.textContent = text;
      const typing = document.createElement("div"); typing.className = "bubble bubble--system"; typing.textContent = "…";
      msgs.append(mine, typing); msgs.scrollTop = msgs.scrollHeight;
      const r = await json("/help/chat/send/", { text, lang });
      typing.remove();
      const data = await r.json().catch(() => ({}));
      if (!r.ok) { add({ role: "system", text: data.error || "Please try again." }); return; }
      mine.remove(); // replaced by the saved copy, which carries its id
      apply(data);
    });
    $("[data-chat-human]", box).addEventListener("click", async () => {
      let email = box.dataset.email;
      if (!email) { email = prompt("Your email, so our team can reply if you leave:"); if (!email) return; }
      const r = await json("/help/chat/handoff/", { email });
      apply(await r.json());
    });
    $("[data-chat-verify]", box).addEventListener("click", async () => {
      const number = prompt("Order number (e.g. RSK000123):"); if (!number) return;
      const contact = prompt("Registered mobile number or email:"); if (!contact) return;
      await json("/help/chat/verify/", { number, contact });
      const code = prompt("We emailed a 6-digit code to the registered email. Enter it:"); if (!code) return;
      const r = await json("/help/chat/verify/", { number, contact, code });
      const d = await r.json();
      add({ role: "system", text: d.verified ? "Order verified. Ask me about it!" : "That code didn't match." });
    });
  }

  // ---- Leaflet map on the address form -------------------------------------
  const mapEl = $("#map");
  if (mapEl && window.L) {
    const lat = $("#id_lat"), lng = $("#id_lng"), pin = $("#id_pincode"), out = $("#area-check");
    const store = [Number(mapEl.dataset.lat), Number(mapEl.dataset.lng)];
    const start = lat.value ? [Number(lat.value), Number(lng.value)] : store;
    const map = L.map(mapEl).setView(start, 14);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
    const icon = L.divIcon({ className: "", html: '<svg viewBox="0 0 24 24" width="36" height="36" style="color:#E53935"><path d="M12 22s8-7 8-13a8 8 0 0 0-16 0c0 6 8 13 8 13Z" fill="currentColor"/><circle cx="12" cy="9" r="3" fill="#fff"/></svg>', iconSize: [36, 36], iconAnchor: [18, 34] });
    const marker = L.marker(start, { draggable: true, icon }).addTo(map);
    L.circle(store, { radius: Number(mapEl.dataset.radius) * 1000, color: "#2FA05A", weight: 1, fillOpacity: 0.04 }).addTo(map);
    const check = async () => {
      const p = marker.getLatLng();
      lat.value = p.lat.toFixed(6); lng.value = p.lng.toFixed(6);
      if (!pin.value || pin.value.length !== 6) { out.textContent = "Enter your 6-digit pincode to check delivery."; return; }
      const fd = new FormData(); fd.append("lat", lat.value); fd.append("lng", lng.value); fd.append("pincode", pin.value);
      const r = await post("/orders/checkout/quote/", fd);
      const d = await r.json();
      out.className = d.ok ? "flash flash--success" : "flash flash--error";
      out.textContent = d.ok ? `We deliver here: about ${d.km} km, delivery ${d.eta}.` : d.message;
    };
    marker.on("dragend", check);
    map.on("click", (e) => { marker.setLatLng(e.latlng); check(); });
    pin.addEventListener("change", check);
    const locate = $("#use-location");
    locate && locate.addEventListener("click", () => navigator.geolocation && navigator.geolocation.getCurrentPosition((pos) => {
      const ll = [pos.coords.latitude, pos.coords.longitude]; marker.setLatLng(ll); map.setView(ll, 16); check();
    }, () => toast("Couldn't get your location. Drag the pin instead.")));
    if (!lat.value) { lat.value = store[0].toFixed(6); lng.value = store[1].toFixed(6); }
  }

  // PWA
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();

// Shared progressive enhancement for result loading and disabled navigation.
document.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.detail.target;
  if (target) target.setAttribute("aria-busy", "true");
});
document.addEventListener("htmx:afterRequest", (event) => {
  const target = event.detail.target;
  if (target) target.setAttribute("aria-busy", "false");
});
document.addEventListener("click", (event) => {
  if (event.target.closest('a[aria-disabled="true"]')) event.preventDefault();
});
