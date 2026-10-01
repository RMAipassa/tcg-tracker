import asyncio
import hashlib
import hmac
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import ROOT, load_config
from .db import Database, now
from .notify import Notifier, load_events, vapid_public_key
from .scanner import Scanner
from .stores import build_stores

log = logging.getLogger("tracker")

config = load_config()
db = Database()
stores = build_stores(config)
scanner = Scanner(db, stores, config)
notifier = Notifier(db, config)
_scan_lock = threading.Lock()
_wake = threading.Event()
_stop = threading.Event()
state = {"next_run": None, "running": False}


def scan_and_notify() -> int:
    with _scan_lock:
        state["running"] = True
        try:
            events = scanner.run_once()
            notifier.send(events)
            return len(events)
        finally:
            state["running"] = False


def scan_loop() -> None:
    interval = config["general"].get("interval_minutes", 15) * 60
    while not _stop.is_set():
        try:
            scan_and_notify()
        except Exception:
            log.exception("Scan cycle failed")
        state["next_run"] = (datetime.now(timezone.utc) + timedelta(seconds=interval)).isoformat(timespec="seconds")
        _wake.wait(interval)
        _wake.clear()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    vapid_public_key()
    thread = threading.Thread(target=scan_loop, name="scanner", daemon=True)
    thread.start()
    yield
    _stop.set()
    _wake.set()


app = FastAPI(title="TCG Tracker", lifespan=lifespan, docs_url=None, redoc_url=None)

# --- auth ---------------------------------------------------------------

SESSION_COOKIE = "tcg_session"


def _session_token() -> str:
    secret = config["web"]["secret_key"].encode()
    return hmac.new(secret, config["web"]["password"].encode(), hashlib.sha256).hexdigest()


def require_login(request: Request) -> None:
    if not hmac.compare_digest(request.cookies.get(SESSION_COOKIE, ""), _session_token()):
        raise HTTPException(401, "Not logged in")


class Login(BaseModel):
    password: str


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    if not hmac.compare_digest(body.password.encode(), config["web"]["password"].encode()):
        raise HTTPException(401, "Wrong password")
    secure = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
    response.set_cookie(SESSION_COOKIE, _session_token(), max_age=365 * 86400, httponly=True, samesite="lax", secure=secure)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


api = Depends(require_login)

# --- data ---------------------------------------------------------------

_PRODUCT_TYPE_SQL = """CASE
    WHEN LOWER(title) LIKE '%elite trainer box%' OR LOWER(title) LIKE '% etb%' THEN 'etb'
    WHEN LOWER(title) LIKE '%booster bundle%' OR LOWER(title) LIKE '%booster bundel%' THEN 'booster_bundle'
    WHEN LOWER(title) LIKE '%booster box%' OR LOWER(title) LIKE '%boosterbox%' OR LOWER(title) LIKE '%booster display%' THEN 'booster_box'
    WHEN LOWER(title) LIKE '%collection%' OR LOWER(title) LIKE '%collectie%' THEN 'collection'
    WHEN LOWER(title) LIKE '%blister%' THEN 'blister'
    WHEN LOWER(title) LIKE '% tin%' OR LOWER(title) LIKE 'tin %' THEN 'tin'
    WHEN LOWER(title) LIKE '%deck%' THEN 'deck'
    WHEN LOWER(title) LIKE '%booster%' OR LOWER(title) LIKE '% pack%' THEN 'booster_pack'
    ELSE 'other'
END"""

_LANGUAGE_SQL = """CASE
    WHEN LOWER(title) LIKE '%japan%' OR LOWER(title) LIKE '% jpn%' THEN 'japanese'
    WHEN LOWER(title) LIKE '%korea%' OR LOWER(title) LIKE '% kor%' THEN 'korean'
    WHEN LOWER(title) LIKE '%chinees%' OR LOWER(title) LIKE '%chinese%' OR LOWER(title) LIKE '% chn%' THEN 'chinese'
    WHEN LOWER(title) LIKE '%frans%' OR LOWER(title) LIKE '%french%' THEN 'french'
    WHEN LOWER(title) LIKE '%duits%' OR LOWER(title) LIKE '%german%' THEN 'german'
    WHEN LOWER(title) LIKE '%spaans%' OR LOWER(title) LIKE '%spanish%' THEN 'spanish'
    WHEN LOWER(title) LIKE '%italiaans%' OR LOWER(title) LIKE '%italian%' THEN 'italian'
    WHEN LOWER(title) LIKE '%portugees%' OR LOWER(title) LIKE '%portuguese%' THEN 'portuguese'
    WHEN LOWER(title) LIKE '%engels%' OR LOWER(title) LIKE '%english%' THEN 'english'
    WHEN LOWER(title) LIKE '%nederlands%' OR LOWER(title) LIKE '%dutch%' THEN 'dutch'
    ELSE 'unspecified'
END"""

_PRODUCT_SORTS = {
    "newest": "first_seen DESC, title COLLATE NOCASE",
    "oldest": "first_seen ASC, title COLLATE NOCASE",
    "updated": "last_seen DESC, title COLLATE NOCASE",
    "price_low": "price_cents IS NULL, price_cents ASC, title COLLATE NOCASE",
    "price_high": "price_cents IS NULL, price_cents DESC, title COLLATE NOCASE",
    "title_asc": "title COLLATE NOCASE ASC",
    "title_desc": "title COLLATE NOCASE DESC",
    "store": "store COLLATE NOCASE, title COLLATE NOCASE",
    "availability": "in_stock DESC, title COLLATE NOCASE",
    "type": f"{_PRODUCT_TYPE_SQL}, title COLLATE NOCASE",
}


@app.get("/api/status", dependencies=[api])
def status():
    recorded = {r["store"]: dict(r) for r in db.query("SELECT * FROM store_runs")}
    runs = []
    for name, store in stores.items():
        run = recorded.get(name, {
            "store": name,
            "initialized": 0,
            "last_run": None,
            "last_ok": None,
            "last_error": None,
            "product_count": None,
        })
        run["label"] = store.label
        runs.append(run)
    return {
        "stores": runs,
        "running": state["running"],
        "next_run": state["next_run"],
        "products": db.one("SELECT COUNT(*) AS n FROM products WHERE in_catalog = 1")["n"],
        "in_stock": db.one("SELECT COUNT(*) AS n FROM products WHERE in_catalog = 1 AND in_stock = 1")["n"],
        "push_devices": db.one("SELECT COUNT(*) AS n FROM push_subscriptions")["n"],
    }


@app.post("/api/run", dependencies=[api])
def run_now():
    _wake.set()
    return {"ok": True}


@app.get("/api/events", dependencies=[api])
def events(limit: int = 100, type: str | None = None):
    sql = (
        "SELECT e.id FROM events e JOIN products p ON p.id = e.product_id"
        " WHERE (p.in_catalog = 1 OR EXISTS (SELECT 1 FROM watchlist w WHERE w.product_id = p.id))"
        + (" AND e.type = ?" if type else "")
        + " ORDER BY e.id DESC LIMIT ?"
    )
    ids = [r["id"] for r in db.query(sql, ((type,) if type else ()) + (min(limit, 500),))]
    return load_events(db, ids)[::-1]  # newest first


@app.get("/api/products", dependencies=[api])
def products(
    q: str = "",
    game: str = "",
    store: str = "",
    in_stock: bool = False,
    availability: str = "all",
    product_type: str = "",
    language: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    added: str = "",
    event_type: str = "",
    price_status: str = "",
    watched_only: bool = False,
    sort: str = "newest",
    limit: int = 200,
    with_count: bool = False,
):
    where, params = ["in_catalog = 1"], []
    for word in q.split():
        where.append("title LIKE ?")
        params.append(f"%{word}%")
    if game:
        where.append("game = ?")
        params.append(game)
    if store:
        where.append("store = ?")
        params.append(store)
    if availability not in {"all", "in_stock", "out_of_stock"}:
        raise HTTPException(400, "Unknown availability filter")
    if in_stock or availability == "in_stock":
        where.append("in_stock = 1")
    elif availability == "out_of_stock":
        where.append("in_stock = 0")
    if product_type:
        where.append(f"({_PRODUCT_TYPE_SQL}) = ?")
        params.append(product_type)
    if language:
        where.append(f"({_LANGUAGE_SQL}) = ?")
        params.append(language)
    if min_price is not None:
        if min_price < 0:
            raise HTTPException(400, "Minimum price cannot be negative")
        where.append("price_cents >= ?")
        params.append(round(min_price * 100))
    if max_price is not None:
        if max_price < 0:
            raise HTTPException(400, "Maximum price cannot be negative")
        where.append("price_cents <= ?")
        params.append(round(max_price * 100))
    if min_price is not None and max_price is not None and min_price > max_price:
        raise HTTPException(400, "Minimum price cannot exceed maximum price")
    added_days = {"day": 1, "week": 7, "month": 30, "quarter": 90, "year": 365}
    if added:
        if added not in added_days:
            raise HTTPException(400, "Unknown date filter")
        cutoff = datetime.now(timezone.utc) - timedelta(days=added_days[added])
        where.append("first_seen >= ?")
        params.append(cutoff.isoformat(timespec="seconds"))
    if event_type:
        if event_type not in {"any", "new", "restock", "price_drop", "target"}:
            raise HTTPException(400, "Unknown activity filter")
        event_clause = "EXISTS (SELECT 1 FROM events e WHERE e.product_id = products.id"
        if event_type != "any":
            event_clause += " AND e.type = ?"
            params.append(event_type)
        where.append(event_clause + ")")
    if price_status:
        if price_status not in {"known", "unknown"}:
            raise HTTPException(400, "Unknown price filter")
        where.append("price_cents IS NOT NULL" if price_status == "known" else "price_cents IS NULL")
    if watched_only:
        where.append("EXISTS (SELECT 1 FROM watchlist w WHERE w.product_id = products.id)")
    if sort not in _PRODUCT_SORTS:
        raise HTTPException(400, "Unknown product sort")

    where_sql = " AND ".join(where)
    total = db.one(f"SELECT COUNT(*) AS n FROM products WHERE {where_sql}", params)["n"] if with_count else None
    rows = db.query(
        f"SELECT products.*, {_PRODUCT_TYPE_SQL} AS product_type, {_LANGUAGE_SQL} AS language,"
        f" EXISTS (SELECT 1 FROM watchlist w WHERE w.product_id = products.id) AS watched"
        f" FROM products WHERE {where_sql} ORDER BY {_PRODUCT_SORTS[sort]} LIMIT ?",
        (*params, max(1, min(limit, 1000))),
    )
    items = [dict(r) for r in rows]
    return {"items": items, "total": total} if with_count else items


@app.get("/api/products/{product_id}/history", dependencies=[api])
def history(product_id: int):
    return [dict(r) for r in db.query("SELECT ts, price_cents, in_stock FROM price_history WHERE product_id = ? ORDER BY ts", (product_id,))]


# --- watchlist ----------------------------------------------------------


class WatchIn(BaseModel):
    url: str
    target_price: float | None = None


@app.get("/api/watchlist", dependencies=[api])
def watchlist():
    rows = db.query(
        "SELECT w.id, w.url, w.store, w.target_price_cents, w.created, p.id AS product_id, p.title, p.image,"
        " p.price_cents, p.in_stock, p.last_seen FROM watchlist w LEFT JOIN products p ON p.id = w.product_id ORDER BY w.id DESC"
    )
    return [dict(r) for r in rows]


@app.post("/api/watchlist", dependencies=[api])
async def add_watch(body: WatchIn):
    url = body.url.strip().split("?")[0].split("#")[0]
    store = next((s for s in stores.values() if s.handles(url)), None)
    if store is None:
        raise HTTPException(400, "Unsupported store. Supported: " + ", ".join(s.label for s in stores.values()))
    path = urlparse(url).path.rstrip("/")
    product = next(
        (row for row in db.query("SELECT * FROM products WHERE store = ?", (store.name,))
         if urlparse(row["url"]).path.rstrip("/") == path),
        None,
    )
    if product is None:
        try:
            snapshot = await asyncio.to_thread(store.fetch, url)
        except Exception as exc:
            raise HTTPException(502, f"Could not load product: {exc}")
        if snapshot is None:
            raise HTTPException(404, "Product not found at that URL")
        product_id, _ = scanner.upsert(snapshot, catalog=False, announce_new=False)
        product_url, title = snapshot.url, snapshot.title
        price_cents, in_stock = snapshot.price_cents, snapshot.in_stock
    else:
        product_id = product["id"]
        product_url, title = product["url"], product["title"]
        price_cents, in_stock = product["price_cents"], bool(product["in_stock"])
    target = round(body.target_price * 100) if body.target_price else None
    db.execute(
        "INSERT INTO watchlist (url, store, product_id, target_price_cents, created) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (url) DO UPDATE SET target_price_cents = excluded.target_price_cents, alerted_price_cents = NULL",
        (product_url, store.name, product_id, target, now()),
    )
    watch = db.one("SELECT id FROM watchlist WHERE url = ?", (product_url,))
    notifier.send(scanner.check_target(watch["id"]))
    return {"ok": True, "title": title, "price_cents": price_cents, "in_stock": in_stock}


@app.delete("/api/watchlist/{watch_id}", dependencies=[api])
def delete_watch(watch_id: int):
    db.execute("DELETE FROM watchlist WHERE id = ?", (watch_id,))
    return {"ok": True}


# --- push ---------------------------------------------------------------


@app.get("/api/push/key")
def push_key():
    return {"key": vapid_public_key()}


@app.post("/api/push/subscribe", dependencies=[api])
async def push_subscribe(request: Request):
    subscription = await request.json()
    if not subscription.get("endpoint"):
        raise HTTPException(400, "Invalid subscription")
    db.execute(
        "INSERT INTO push_subscriptions (endpoint, subscription, created) VALUES (?, ?, ?)"
        " ON CONFLICT (endpoint) DO UPDATE SET subscription = excluded.subscription",
        (subscription["endpoint"], json.dumps(subscription), now()),
    )
    return {"ok": True}


@app.post("/api/push/test", dependencies=[api])
def push_test():
    subs = db.query("SELECT * FROM push_subscriptions")
    sent = sum(notifier.push_to(s, {"title": "TCG Tracker", "body": "Push notifications work 🎉", "url": "/", "tag": "test"}) for s in subs)
    return {"sent": sent, "devices": len(subs)}


# --- PWA ----------------------------------------------------------------

STATIC = ROOT / "static"


@app.get("/sw.js")
def service_worker():
    # Served from the root so it may control the whole app.
    return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
