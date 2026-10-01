const $ = (sel) => document.querySelector(sel);
const STORES = { bescards: "Bescards", tcgcompany: "TCG Company", intertoys: "Intertoys", bol: "bol.com" };
const GAMES = { pokemon: "Pokémon", mtg: "Magic", naruto: "Naruto" };
const KINDS = {
  new: "New arrival",
  restock: "Back in stock",
  price_drop: "Price drop",
  target: "Target reached",
};
const TAB_META = {
  alerts: ["Activity", "Collection monitor"],
  products: ["Products", "Live inventory"],
  watchlist: ["Watchlist", "Personal targets"],
  settings: ["Settings", "System control"],
};

const euroFormat = new Intl.NumberFormat("nl-NL", { style: "currency", currency: "EUR" });
const euro = (cents) => (cents == null ? "Price unknown" : euroFormat.format(cents / 100));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function ago(iso) {
  const seconds = (Date.now() - new Date(iso)) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return Math.floor(seconds / 60) + " min ago";
  if (seconds < 86400) return Math.floor(seconds / 3600) + " h ago";
  return Math.floor(seconds / 86400) + " d ago";
}

function toast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => element.classList.remove("show"), 3200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    body: options.body && typeof options.body !== "string" ? JSON.stringify(options.body) : options.body,
  });
  if (response.status === 401 && path !== "/api/login") {
    if (!$("#login").open) $("#login").showModal();
    throw new Error("Not logged in");
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || response.statusText);
  return data;
}

const image = (src) => (src
  ? `<img src="${esc(src)}" alt="" loading="lazy">`
  : `<div class="noimg" aria-hidden="true"></div>`);
const stock = (inStock) => (inStock
  ? `<span class="stock-in">In stock</span>`
  : `<span class="stock-out">Sold out</span>`);

// Activity
let alertType = "";

async function loadAlerts() {
  const events = await api("/api/events?limit=150" + (alertType ? "&type=" + alertType : ""));
  $("#alert-count").textContent = events.length ? `${events.length} events` : "";
  $("#alerts").innerHTML = events.length
    ? events.map((event) => {
        let price = euro(event.new_price_cents);
        if (event.type === "price_drop") price = `<s>${euro(event.old_price_cents)}</s> ${price}`;
        if (event.type === "target") price += ` <small>target ${euro(event.old_price_cents)}</small>`;
        return `<li class="activity-item">
          <a class="thumb" href="${esc(event.url)}" target="_blank" rel="noopener">${image(event.image)}</a>
          <div class="body">
            <div class="activity-topline"><span class="kind kind-${esc(event.type)}">${esc(KINDS[event.type] || event.type)}</span><time>${ago(event.ts)}</time></div>
            <a href="${esc(event.url)}" target="_blank" rel="noopener"><div class="title">${esc(event.title)}</div></a>
            <div class="item-footer"><span class="price">${price}</span><span class="store-tag">${esc(STORES[event.store] || event.store)}</span></div>
          </div>
        </li>`;
      }).join("")
    : `<li class="empty">No alerts yet. Your first scan establishes a baseline; changes appear here afterward.</li>`;
}

$("#alert-filter").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  alertType = button.dataset.type;
  document.querySelectorAll("#alert-filter button").forEach((item) => item.classList.toggle("on", item === button));
  loadAlerts().catch((error) => toast(error.message));
});

// Products
let game = "";
let searchTimer;
let productRequest = 0;
let pendingWatch = null;

function productParams() {
  const params = new URLSearchParams({
    q: $("#search").value.trim(),
    game,
    store: $("#filter-store").value,
    availability: $("#filter-availability").value,
    product_type: $("#filter-type").value,
    language: $("#filter-language").value,
    added: $("#filter-added").value,
    event_type: $("#filter-event").value,
    price_status: $("#filter-price-status").value,
    sort: $("#filter-sort").value,
    limit: $("#filter-limit").value,
    with_count: "true",
  });
  if ($("#filter-min-price").value) params.set("min_price", $("#filter-min-price").value);
  if ($("#filter-max-price").value) params.set("max_price", $("#filter-max-price").value);
  if ($("#filter-watched").checked) params.set("watched_only", "true");
  return params;
}

function updateActiveFilterCount() {
  const values = [
    $("#search").value.trim(), game, $("#filter-store").value, $("#filter-type").value,
    $("#filter-language").value, $("#filter-min-price").value, $("#filter-max-price").value,
    $("#filter-added").value, $("#filter-event").value, $("#filter-price-status").value,
  ];
  let count = values.filter(Boolean).length;
  if ($("#filter-availability").value !== "all") count += 1;
  if ($("#filter-sort").value !== "newest") count += 1;
  if ($("#filter-watched").checked) count += 1;
  $("#active-filter-count").textContent = count ? `${count} active` : "No active filters";
}

async function loadProducts() {
  const request = ++productRequest;
  updateActiveFilterCount();
  $("#product-count").textContent = "Loading...";
  const result = await api("/api/products?" + productParams());
  if (request !== productRequest) return;
  const products = Array.isArray(result) ? result : result.items;
  const total = Array.isArray(result) ? products.length : result.total;
  $("#product-count").textContent = products.length === total ? `${total} products` : `${products.length} of ${total}`;
  $("#products").innerHTML = products.length
    ? products.map((product) => `<li class="product-item">
        <a class="product-media" href="${esc(product.url)}" target="_blank" rel="noopener">${image(product.image)}</a>
        <div class="body">
          <a href="${esc(product.url)}" target="_blank" rel="noopener"><div class="title">${esc(product.title)}</div></a>
          <div class="badges">${stock(product.in_stock)}<span class="store-tag">${esc(STORES[product.store] || product.store)}</span></div>
          <div class="item-footer"><span class="price">${euro(product.price_cents)}</span></div>
        </div>
        <button class="watch-add${product.watched ? " watched" : ""}" type="button" aria-label="${product.watched ? "Update" : "Add"} ${esc(product.title)} on watchlist" title="${product.watched ? "Update watch target" : "Add to watchlist"}" data-url="${esc(product.url)}" data-title="${esc(product.title)}">${product.watched ? "✓" : "+"}</button>
      </li>`).join("")
    : `<li class="empty">No products match these filters.</li>`;
}

function queueProductLoad(delay = 0) {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => loadProducts().catch((error) => toast(error.message)), delay);
}

$("#search").addEventListener("input", () => queueProductLoad(250));
document.querySelectorAll("#filter-sort, #filter-store, #filter-availability, #filter-type, #filter-language, #filter-added, #filter-event, #filter-price-status, #filter-limit, #filter-watched").forEach((control) => {
  control.addEventListener("change", () => queueProductLoad());
});
document.querySelectorAll("#filter-min-price, #filter-max-price").forEach((control) => {
  control.addEventListener("input", () => queueProductLoad(300));
});
$("#game-filter").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  game = button.dataset.game;
  document.querySelectorAll("#game-filter button").forEach((item) => item.classList.toggle("on", item === button));
  queueProductLoad();
});
$("#filter-reset").addEventListener("click", () => {
  game = "";
  $("#search").value = "";
  $("#filter-sort").value = "newest";
  $("#filter-store").value = "";
  $("#filter-availability").value = "in_stock";
  $("#filter-type").value = "";
  $("#filter-language").value = "";
  $("#filter-min-price").value = "";
  $("#filter-max-price").value = "";
  $("#filter-added").value = "";
  $("#filter-event").value = "";
  $("#filter-price-status").value = "";
  $("#filter-limit").value = "120";
  $("#filter-watched").checked = false;
  document.querySelectorAll("#game-filter button").forEach((item) => item.classList.toggle("on", item.dataset.game === ""));
  queueProductLoad();
});
$("#products").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-url]");
  if (!button) return;
  pendingWatch = { url: button.dataset.url, title: button.dataset.title };
  $("#target-product").textContent = pendingWatch.title;
  $("#target-form").reset();
  $("#target-dialog").showModal();
  $("#target-form input").focus();
});

// Watchlist
async function addWatch(url, target) {
  try {
    const result = await api("/api/watchlist", {
      method: "POST",
      body: { url, target_price: target ? parseFloat(String(target).replace(",", ".")) : null },
    });
    toast(`Watching ${result.title} at ${euro(result.price_cents)}`);
    loadWatchlist().catch(() => {});
    return true;
  } catch (error) {
    toast(error.message);
    return false;
  }
}

async function loadWatchlist() {
  const items = await api("/api/watchlist");
  $("#watch-count").textContent = `${items.length} watched`;
  $("#watchlist").innerHTML = items.length
    ? items.map((item) => {
        const hit = item.target_price_cents != null && item.price_cents != null && item.price_cents <= item.target_price_cents;
        const target = item.target_price_cents != null ? `Target ${euro(item.target_price_cents)}` : "Restock alerts";
        return `<li class="watch-item">
          <a class="thumb" href="${esc(item.url)}" target="_blank" rel="noopener">${image(item.image)}</a>
          <div class="body">
            <a href="${esc(item.url)}" target="_blank" rel="noopener"><div class="title">${esc(item.title || item.url)}</div></a>
            <div class="meta"><span class="price" ${hit ? 'style="color:var(--ok)"' : ""}>${euro(item.price_cents)}</span> · ${esc(target)} · ${stock(item.in_stock)} · ${esc(STORES[item.store] || item.store)}</div>
          </div>
          <button class="remove" type="button" data-id="${item.id}" aria-label="Remove from watchlist" title="Remove">×</button>
        </li>`;
      }).join("")
    : `<li class="empty">Your watchlist is empty. Add a product URL or use the plus button in Products.</li>`;
}

$("#watch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  if (await addWatch(form.url.value, form.target.value)) form.reset();
  button.disabled = false;
});
$("#target-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!pendingWatch) return;
  const button = event.target.querySelector("button[type=submit]");
  button.disabled = true;
  if (await addWatch(pendingWatch.url, event.target.target.value)) {
    $("#target-dialog").close();
    pendingWatch = null;
  }
  button.disabled = false;
});
$("#target-cancel").addEventListener("click", () => $("#target-dialog").close());
$("#watchlist").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-id]");
  if (!button || !confirm("Remove this product from your watchlist?")) return;
  await api("/api/watchlist/" + button.dataset.id, { method: "DELETE" });
  loadWatchlist().catch(() => {});
});

// Settings and status
async function loadStatus() {
  const status = await api("/api/status");
  status.stores.forEach((store) => { STORES[store.store] = store.label; });
  const storeFilter = $("#filter-store");
  const selectedStore = storeFilter.value;
  storeFilter.innerHTML = `<option value="">All stores</option>` + status.stores
    .map((store) => `<option value="${esc(store.store)}">${esc(store.label)}</option>`).join("");
  if (status.stores.some((store) => store.store === selectedStore)) storeFilter.value = selectedStore;
  const last = status.stores.map((store) => store.last_ok).filter(Boolean).sort().pop();
  const lastText = last ? ago(last) : "not yet";
  $("#status-line").textContent = status.running ? "Scanning stores..." : `${status.in_stock} available · ${lastText}`;
  $("#status-pill").classList.toggle("scanning", status.running);
  $("#metric-in-stock").textContent = status.in_stock;
  $("#metric-products").textContent = status.products;
  $("#metric-stores").textContent = status.stores.length;
  $("#metric-updated").textContent = last ? ago(last).replace(" ago", "") : "-";

  $("#stores").innerHTML = status.stores.length
    ? status.stores.map((store) => `<div class="store-row">
        <div class="store-name">${esc(store.label)}</div>
        <div class="store-stat">${store.product_count ?? "-"} products<small>${store.last_ok ? "Updated " + ago(store.last_ok) : "Awaiting first scan"}</small></div>
        <div class="store-state ${store.last_error ? "error" : ""}">${esc(store.last_error || (store.last_ok ? "Healthy" : "Pending"))}</div>
      </div>`).join("")
    : `<div class="empty">The first scan is starting...</div>`;

  const runButton = $("#run-now");
  runButton.disabled = status.running;
  runButton.textContent = status.running ? "Scanning..." : "Scan all stores";
  clearTimeout(loadStatus.poll);
  if (status.running) loadStatus.poll = setTimeout(() => loadStatus().catch(() => {}), 2500);
}

$("#run-now").addEventListener("click", async () => {
  const button = $("#run-now");
  button.disabled = true;
  button.textContent = "Starting...";
  await api("/api/run", { method: "POST" });
  toast("Store scan queued");
  setTimeout(() => loadStatus().catch(() => {}), 700);
});
$("#logout").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

// Push notifications
function urlBase64ToUint8Array(base64) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
}

async function pushState() {
  const element = $("#push-state");
  const standalone = matchMedia("(display-mode: standalone)").matches || navigator.standalone;
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    element.textContent = /iPhone|iPad/.test(navigator.userAgent) && !standalone
      ? "On iPhone, add this site to your Home Screen and open it from there before enabling notifications."
      : "This browser does not support push notifications.";
    $("#push-enable").disabled = true;
    return;
  }
  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  element.textContent = subscription ? "Notifications are enabled on this device." : Notification.permission === "denied"
    ? "Notifications are blocked in this browser's site settings."
    : "Notifications are not enabled on this device yet.";
  $("#push-enable").textContent = subscription ? "Re-register device" : "Enable on this device";
}

$("#push-enable").addEventListener("click", async () => {
  try {
    if ((await Notification.requestPermission()) !== "granted") throw new Error("Notification permission was not granted");
    const registration = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/key");
    const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
    await api("/api/push/subscribe", { method: "POST", body: subscription.toJSON() });
    toast("Notifications enabled");
  } catch (error) {
    toast(error.message);
  }
  pushState().catch(() => {});
});
$("#push-test").addEventListener("click", async () => {
  const result = await api("/api/push/test", { method: "POST" });
  toast(`Test sent to ${result.sent}/${result.devices} devices`);
});

// Navigation and boot
const loaders = {
  alerts: loadAlerts,
  products: loadProducts,
  watchlist: loadWatchlist,
  settings: () => Promise.all([loadStatus(), pushState()]),
};

function showTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.id === "tab-" + name));
  document.querySelectorAll("nav button").forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle("on", active);
    button.setAttribute("aria-selected", String(active));
  });
  $("#page-title").textContent = TAB_META[name][0];
  $("#page-kicker").textContent = TAB_META[name][1];
  Promise.resolve(loaders[name]()).catch((error) => error.message !== "Not logged in" && toast(error.message));
}

document.querySelector("nav").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (button) showTab(button.dataset.tab);
});

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api("/api/login", { method: "POST", body: { password: event.target.password.value } });
    $("#login").close();
    event.target.reset();
    boot();
  } catch (error) {
    $("#login-error").textContent = error.message;
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
