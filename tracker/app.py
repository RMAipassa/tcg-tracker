import asyncio
import hashlib
import hmac
import json
import logging
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

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


@app.get("/api/status", dependencies=[api])
def status():
    runs = [dict(r) for r in db.query("SELECT * FROM store_runs ORDER BY store")]
    for run in runs:
        run["label"] = stores[run["store"]].label if run["store"] in stores else run["store"]
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
    sql = "SELECT id FROM events" + (" WHERE type = ?" if type else "") + " ORDER BY id DESC LIMIT ?"
    ids = [r["id"] for r in db.query(sql, ((type,) if type else ()) + (min(limit, 500),))]
    return load_events(db, ids)[::-1]  # newest first


@app.get("/api/products", dependencies=[api])
def products(q: str = "", game: str = "", store: str = "", in_stock: bool = False, limit: int = 200):
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
    if in_stock:
        where.append("in_stock = 1")
    rows = db.query(
        f"SELECT * FROM products WHERE {' AND '.join(where)} ORDER BY in_stock DESC, first_seen DESC LIMIT ?",
        (*params, min(limit, 1000)),
    )
    return [dict(r) for r in rows]


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
    try:
        snapshot = await asyncio.to_thread(store.fetch, url)
    except Exception as exc:
        raise HTTPException(502, f"Could not load product: {exc}")
    if snapshot is None:
        raise HTTPException(404, "Product not found at that URL")
    product_id, _ = scanner.upsert(snapshot, catalog=False, announce_new=False)
    target = round(body.target_price * 100) if body.target_price else None
    db.execute(
        "INSERT INTO watchlist (url, store, product_id, target_price_cents, created) VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (url) DO UPDATE SET target_price_cents = excluded.target_price_cents, alerted_price_cents = NULL",
        (snapshot.url, store.name, product_id, target, now()),
    )
    watch = db.one("SELECT id FROM watchlist WHERE url = ?", (snapshot.url,))
    notifier.send(scanner.check_target(watch["id"]))
    return {"ok": True, "title": snapshot.title, "price_cents": snapshot.price_cents, "in_stock": snapshot.in_stock}


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
