import sqlite3
import threading
from datetime import datetime, timezone

from .config import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    store TEXT NOT NULL,
    store_product_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    game TEXT,
    image TEXT,
    price_cents INTEGER,
    in_stock INTEGER NOT NULL DEFAULT 0,
    in_catalog INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    UNIQUE (store, store_product_id)
);
CREATE INDEX IF NOT EXISTS idx_products_url ON products (url);

CREATE TABLE IF NOT EXISTS price_history (
    product_id INTEGER NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    price_cents INTEGER,
    in_stock INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_history_product ON price_history (product_id, ts);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    type TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products (id) ON DELETE CASCADE,
    old_price_cents INTEGER,
    new_price_cents INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events (ts);

CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    store TEXT NOT NULL,
    product_id INTEGER REFERENCES products (id) ON DELETE SET NULL,
    target_price_cents INTEGER,
    alerted_price_cents INTEGER,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    subscription TEXT NOT NULL,
    created TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS store_runs (
    store TEXT PRIMARY KEY,
    initialized INTEGER NOT NULL DEFAULT 0,
    last_run TEXT,
    last_ok TEXT,
    last_error TEXT,
    product_count INTEGER
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Thin SQLite wrapper, shared by the scanner thread and the web app."""

    def __init__(self, path=DATA_DIR / "tracker.db"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def query(self, sql: str, params=()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params=()) -> int:
        with self._lock, self._conn:
            return self._conn.execute(sql, params).lastrowid
