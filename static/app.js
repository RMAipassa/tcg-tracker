const $ = (sel) => document.querySelector(sel);
const STORES = { bescards: "Bescards", tcgcompany: "TCG Company", intertoys: "Intertoys" };
const GAMES = { pokemon: "Pokémon", mtg: "Magic", naruto: "Naruto" };
const KINDS = {
  new: ["🆕 New", "#5865F2"],
  restock: ["✅ Back in stock", "#16a34a"],
  price_drop: ["📉 Price drop", "#e67e22"],
  target: ["🎯 Target hit", "#e91e63"],
};

const euro = (cents) => (cents == null ? "?" : "€" + (cents / 100).toFixed(2).replace(".", ","));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + " min ago";
  if (s < 86400) return Math.floor(s / 3600) + " h ago";
  return Math.floor(s / 86400) + " d ago";
}

function toast(msg) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove("show"), 3000);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body && typeof options.body !== "string" ? JSON.stringify(options.body) : options.body,
  });
  if (res.status === 401 && path !== "/api/login") {
    $("#login").showModal();
    throw new Error("Not logged in");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

const image = (src) => (src ? `<img src="${esc(src)}" alt="" loading="lazy">` : `<div class="noimg"></div>`);
const stock = (inStock) => (inStock ? `<span class="stock-in">In stock</span>` : `<span class="stock-out">Sold out</span>`);

// --- Alerts ---------------------------------------------------------------
let alertType = "";

async function loadAlerts() {
  const events = await api("/api/events?limit=150" + (alertType ? "&type=" + alertType : ""));
  $("#alerts").innerHTML = events.length
    ? events.map((e) => {
        const [label, color] = KINDS[e.type];
        let price = euro(e.new_price_cents);
        if (e.type === "price_drop") price = `<s>${euro(e.old_price_cents)}</s> ${price}`;
        if (e.type === "target") price += ` <small>(target ${euro(e.old_price_cents)})</small>`;
        return `<li><a href="${esc(e.url)}" target="_blank" rel="noopener">${image(e.image)}</a>
          <div class="body"><a href="${esc(e.url)}" target="_blank" rel="noopener">
            <div class="kind" style="color:${color}">${label}</div>
            <div class="title">${esc(e.title)}</div>
            <div class="meta"><span class="price">${price}</span> · ${STORES[e.store] || e.store} · ${ago(e.ts)}</div>
          </a></div></li>`;
      }).join("")
    : `<li class="empty">No alerts yet. The first scan only records what's in stock; changes after that show up here.</li>`;
}

$("#alert-filter").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  alertType = btn.dataset.type;
  document.querySelectorAll("#alert-filter button").forEach((b) => b.classList.toggle("on", b === btn));
  loadAlerts();
});

// --- Products ---------------------------------------------------------------
let game = "";
let searchTimer;

async function loadProducts() {
  const params = new URLSearchParams({ q: $("#search").value, game, in_stock: $("#stock-only").checked, limit: 300 });
  const products = await api("/api/products?" + params);
  $("#products").innerHTML = products.length
    ? products.map((p) => `<li><a href="${esc(p.url)}" target="_blank" rel="noopener">${image(p.image)}</a>
        <div class="body"><a href="${esc(p.url)}" target="_blank" rel="noopener">
          <div class="title">${esc(p.title)}</div>
          <div class="meta"><span class="price">${euro(p.price_cents)}</span> · ${stock(p.in_stock)} · ${STORES[p.store] || p.store}</div>
        </a></div>
        <button class="remove" title="Add to watchlist" data-url="${esc(p.url)}">＋</button></li>`).join("")
    : `<li class="empty">Nothing found.</li>`;
}

$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadProducts, 250);
});
$("#stock-only").addEventListener("change", loadProducts);
$("#game-filter").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (!btn) return;
  game = btn.dataset.game;
  document.querySelectorAll("#game-filter button").forEach((b) => b.classList.toggle("on", b === btn));
  loadProducts();
});
$("#products").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-url]");
  if (!btn) return;
  const target = prompt("Target price in € (leave empty for restock alerts only):");
  if (target === null) return;
  await addWatch(btn.dataset.url, target);
});

// --- Watchlist --------------------------------------------------------------
async function addWatch(url, target) {
  try {
    const res = await api("/api/watchlist", {
      method: "POST",
      body: { url, target_price: target ? parseFloat(String(target).replace(",", ".")) : null },
    });
    toast(`Watching: ${res.title} (${euro(res.price_cents)})`);
    loadWatchlist();
    return true;
  } catch (err) {
    toast(err.message);
    return false;
  }
}

async function loadWatchlist() {
  const items = await api("/api/watchlist");
  $("#watchlist").innerHTML = items.length
    ? items.map((w) => {
        const hit = w.target_price_cents != null && w.price_cents != null && w.price_cents <= w.target_price_cents;
        return `<li>${image(w.image)}
          <div class="body"><a href="${esc(w.url)}" target="_blank" rel="noopener">
            <div class="title">${esc(w.title || w.url)}</div>
            <div class="meta"><span class="price" ${hit ? 'style="color:var(--ok)"' : ""}>${euro(w.price_cents)}</span>
              ${w.target_price_cents != null ? `→ target ${euro(w.target_price_cents)}` : ""} · ${stock(w.in_stock)} · ${STORES[w.store] || w.store}</div>
          </a></div>
          <button class="remove" data-id="${w.id}" title="Remove">✕</button></li>`;
      }).join("")
    : `<li class="empty">Your watchlist is empty.</li>`;
}

$("#watch-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const btn = form.querySelector("button");
  btn.disabled = true;
  if (await addWatch(form.url.value, form.target.value)) form.reset();
  btn.disabled = false;
});
$("#watchlist").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-id]");
  if (!btn || !confirm("Remove from watchlist?")) return;
  await api("/api/watchlist/" + btn.dataset.id, { method: "DELETE" });
  loadWatchlist();
});

// --- Settings / status --------------------------------------------------------
async function loadStatus() {
  const s = await api("/api/status");
  const last = s.stores.map((r) => r.last_ok).filter(Boolean).sort().pop();
  $("#status-line").textContent = s.running ? "Scanning…" : `${s.in_stock}/${s.products} in stock` + (last ? ` · ${ago(last)}` : "");
  $("#stores").innerHTML = s.stores.map((r) => `<tr><td><b>${esc(r.label)}</b></td>
    <td>${r.product_count ?? "–"} products<br><small>${r.last_ok ? "OK " + ago(r.last_ok) : "never OK"}</small></td>
    <td class="err">${esc(r.last_error || "")}</td></tr>`).join("") || "<tr><td>First scan in progress…</td></tr>";
}

$("#run-now").addEventListener("click", async () => {
  await api("/api/run", { method: "POST" });
  toast("Scan started");
  setTimeout(loadStatus, 1500);
});
$("#logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

// --- Push notifications -----------------------------------------------------
function urlBase64ToUint8Array(base64) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

async function pushState() {
  const el = $("#push-state");
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    el.textContent = /iPhone|iPad/.test(navigator.userAgent) && !standalone
      ? "On iPhone: tap Share → “Add to Home Screen”, open the app from your home screen and enable notifications there."
      : "This browser does not support push notifications.";
    $("#push-enable").disabled = true;
    return;
  }
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  el.textContent = sub ? "Enabled on this device ✅" : Notification.permission === "denied"
    ? "Notifications are blocked for this site in your browser settings."
    : "Not enabled on this device yet.";
  $("#push-enable").textContent = sub ? "Re-register device" : "Enable on this device";
}

$("#push-enable").addEventListener("click", async () => {
  try {
    if ((await Notification.requestPermission()) !== "granted") throw new Error("Permission not granted");
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/key");
    const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
    await api("/api/push/subscribe", { method: "POST", body: sub.toJSON() });
    toast("Notifications enabled");
  } catch (err) {
    toast(err.message);
  }
  pushState();
});
$("#push-test").addEventListener("click", async () => {
  const res = await api("/api/push/test", { method: "POST" });
  toast(`Test sent to ${res.sent}/${res.devices} device(s)`);
});

// --- Navigation & boot --------------------------------------------------------
const loaders = { alerts: loadAlerts, products: loadProducts, watchlist: loadWatchlist, settings: () => { loadStatus(); pushState(); } };

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  loaders[name]().catch(() => {});
}

document.querySelector("nav").addEventListener("click", (ev) => {
  const btn = ev.target.closest("button");
  if (btn) showTab(btn.dataset.tab);
});

$("#login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    await api("/api/login", { method: "POST", body: { password: ev.target.password.value } });
    $("#login").close();
    boot();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

function boot() {
  const active = document.querySelector("nav button.on").dataset.tab;
  loadStatus().then(() => loaders[active]()).catch(() => {});
}

if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js");
document.addEventListener("visibilitychange", () => document.visibilityState === "visible" && boot());
setInterval(() => document.visibilityState === "visible" && loadStatus().catch(() => {}), 60000);
boot();
