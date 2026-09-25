import logging

from .db import Database, now
from .models import Snapshot
from .stores import Store

log = logging.getLogger("tracker.scanner")


class Scanner:
    def __init__(self, db: Database, stores: dict[str, Store], config: dict):
        self.db = db
        self.stores = stores
        self.drop_percent = config["general"].get("price_drop_percent", 10)

    def run_once(self) -> list[int]:
        """Scan all stores and the watchlist; returns the ids of new events."""
        events: list[int] = []
        seen: set[int] = set()

        for store in self.stores.values():
            run = self.db.one("SELECT initialized FROM store_runs WHERE store = ?", (store.name,))
            initialized = bool(run and run["initialized"])
            started = now()
            try:
                snapshots = store.scan()
            except Exception as exc:  # one broken store must not stop the others
                log.exception("Scan of %s failed", store.name)
                self._record_run(store.name, started, error=f"{type(exc).__name__}: {exc}")
                continue
            if not snapshots:
                # Almost certainly a layout change or block, not an empty store.
                self._record_run(store.name, started, error="Scan returned 0 products")
                continue
            store_events = []
            for snapshot in snapshots:
                product_id, new_events = self.upsert(snapshot, catalog=True, announce_new=initialized)
                seen.add(product_id)
                store_events += new_events
            events += store_events
            self._record_run(store.name, started, count=len(snapshots))
            log.info("%s: %d products, %d events", store.name, len(snapshots), len(store_events))

        events += self._check_watchlist(seen)
        return events

    def upsert(self, s: Snapshot, catalog: bool, announce_new: bool) -> tuple[int, list[int]]:
        ts = now()
        row = self.db.one("SELECT * FROM products WHERE store = ? AND store_product_id = ?", (s.store, s.store_product_id))
        if row is None:
            product_id = self.db.execute(
                "INSERT INTO products (store, store_product_id, url, title, game, image, price_cents, in_stock, in_catalog, first_seen, last_seen)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (s.store, s.store_product_id, s.url, s.title, s.game, s.image, s.price_cents, int(s.in_stock), int(catalog), ts, ts),
            )
            self.db.execute("INSERT INTO price_history VALUES (?, ?, ?, ?)", (product_id, ts, s.price_cents, int(s.in_stock)))
            return product_id, [self._event(ts, "new", product_id, None, s.price_cents)] if catalog and announce_new else []

        product_id = row["id"]
        self.db.execute(
            "UPDATE products SET url = ?, title = ?, game = COALESCE(?, game), image = COALESCE(?, image), price_cents = ?,"
            " in_stock = ?, in_catalog = MAX(in_catalog, ?), last_seen = ? WHERE id = ?",
            (s.url, s.title, s.game, s.image, s.price_cents, int(s.in_stock), int(catalog), ts, product_id),
        )
        old_price, old_stock = row["price_cents"], bool(row["in_stock"])
        if old_price != s.price_cents or old_stock != s.in_stock:
            self.db.execute("INSERT INTO price_history VALUES (?, ?, ?, ?)", (product_id, ts, s.price_cents, int(s.in_stock)))

        events = []
        if s.in_stock and not old_stock:
            events.append(self._event(ts, "restock", product_id, old_price, s.price_cents))
        elif (
            (catalog or row["in_catalog"])
            and s.in_stock
            and old_price and s.price_cents
            and s.price_cents <= old_price * (1 - self.drop_percent / 100)
        ):
            events.append(self._event(ts, "price_drop", product_id, old_price, s.price_cents))
        return product_id, events

    def _check_watchlist(self, seen: set[int]) -> list[int]:
        events = []
        for watch in self.db.query("SELECT * FROM watchlist"):
            if watch["product_id"] not in seen:
                store = self.stores.get(watch["store"])
                if store is None:
                    continue
                try:
                    snapshot = store.fetch(watch["url"])
                except Exception:
                    log.exception("Fetching watchlist item %s failed", watch["url"])
                    continue
                if snapshot is None:
                    log.warning("Watchlist item %s not found", watch["url"])
                    continue
                product_id, new_events = self.upsert(snapshot, catalog=False, announce_new=False)
                events += new_events
                if product_id != watch["product_id"]:
                    self.db.execute("UPDATE watchlist SET product_id = ? WHERE id = ?", (product_id, watch["id"]))
            events += self.check_target(watch["id"])
        return events

    def check_target(self, watch_id: int) -> list[int]:
        watch = self.db.one(
            "SELECT w.*, p.price_cents, p.in_stock FROM watchlist w JOIN products p ON p.id = w.product_id WHERE w.id = ?",
            (watch_id,),
        )
        if not watch or watch["target_price_cents"] is None or watch["price_cents"] is None:
            return []
        price = watch["price_cents"]
        if price > watch["target_price_cents"]:
            if watch["alerted_price_cents"] is not None:
                self.db.execute("UPDATE watchlist SET alerted_price_cents = NULL WHERE id = ?", (watch_id,))
            return []
        # Alert once when the target is hit, and again only if it drops even further.
        if watch["in_stock"] and (watch["alerted_price_cents"] is None or price < watch["alerted_price_cents"]):
            self.db.execute("UPDATE watchlist SET alerted_price_cents = ? WHERE id = ?", (price, watch_id))
            return [self._event(now(), "target", watch["product_id"], watch["target_price_cents"], price)]
        return []

    def _event(self, ts: str, type_: str, product_id: int, old_price: int | None, new_price: int | None) -> int:
        return self.db.execute(
            "INSERT INTO events (ts, type, product_id, old_price_cents, new_price_cents) VALUES (?, ?, ?, ?, ?)",
            (ts, type_, product_id, old_price, new_price),
        )

    def _record_run(self, store: str, started: str, count: int | None = None, error: str | None = None) -> None:
        if error:
            self.db.execute(
                "INSERT INTO store_runs (store, last_run, last_error) VALUES (?, ?, ?)"
                " ON CONFLICT (store) DO UPDATE SET last_run = excluded.last_run, last_error = excluded.last_error",
                (store, started, error),
            )
        else:
            self.db.execute(
                "INSERT INTO store_runs (store, initialized, last_run, last_ok, last_error, product_count) VALUES (?, 1, ?, ?, NULL, ?)"
                " ON CONFLICT (store) DO UPDATE SET initialized = 1, last_run = excluded.last_run, last_ok = excluded.last_ok,"
                " last_error = NULL, product_count = excluded.product_count",
                (store, started, started, count),
            )
