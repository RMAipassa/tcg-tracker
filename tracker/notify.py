import html
import json
import logging
import smtplib
import time
from email.message import EmailMessage

import httpx

from .config import DATA_DIR
from .db import Database
from .models import euro

log = logging.getLogger("tracker.notify")

STORE_LABELS = {"bescards": "Bescards", "tcgcompany": "TCG Company", "intertoys": "Intertoys"}
GAME_LABELS = {"pokemon": "Pokémon", "mtg": "Magic", "naruto": "Naruto"}
EVENT_LABELS = {"new": "🆕 New product", "restock": "✅ Back in stock", "price_drop": "📉 Price drop", "target": "🎯 Target price hit"}
EVENT_COLORS = {"new": 0x5865F2, "restock": 0x2ECC71, "price_drop": 0xE67E22, "target": 0xE91E63}
VAPID_KEY_PATH = DATA_DIR / "vapid_private.pem"


def load_events(db: Database, ids: list[int]) -> list[dict]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = db.query(
        f"SELECT e.*, p.title, p.url, p.image, p.store, p.game, p.in_stock FROM events e"
        f" JOIN products p ON p.id = e.product_id WHERE e.id IN ({marks}) ORDER BY e.id",
        ids,
    )
    return [dict(r) for r in rows]


def describe(event: dict) -> str:
    new, old = event["new_price_cents"], event["old_price_cents"]
    if event["type"] == "price_drop" and old:
        return f"{euro(old)} → {euro(new)} (-{round((1 - new / old) * 100)}%)"
    if event["type"] == "target":
        return f"{euro(new)} (target {euro(old)})"
    return euro(new)


def vapid_public_key() -> str:
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid01, b64urlencode

    if not VAPID_KEY_PATH.exists():
        vapid = Vapid01()
        vapid.generate_keys()
        vapid.save_key(str(VAPID_KEY_PATH))
    vapid = Vapid01.from_file(str(VAPID_KEY_PATH))
    raw = vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64urlencode(raw)


class Notifier:
    def __init__(self, db: Database, config: dict):
        self.db = db
        self.config = config
        self.base_url = config["general"].get("base_url", "").rstrip("/")

    def send(self, event_ids: list[int]) -> None:
        events = load_events(self.db, event_ids)
        if not events:
            return
        for channel in (self._discord, self._email, self._push):
            try:
                channel(events)
            except Exception:
                log.exception("Notification channel %s failed", channel.__name__)

    def _wanted(self, section: str, events: list[dict]) -> list[dict]:
        allowed = set(self.config.get(section, {}).get("events", EVENT_LABELS))
        return [e for e in events if e["type"] in allowed]

    def _discord(self, events: list[dict]) -> None:
        url = self.config.get("discord", {}).get("webhook_url")
        events = self._wanted("discord", events)
        if not url or not events:
            return
        embeds = []
        for e in events:
            embed = {
                "title": e["title"][:250],
                "url": e["url"],
                "color": EVENT_COLORS[e["type"]],
                "author": {"name": EVENT_LABELS[e["type"]]},
                "description": f"**{describe(e)}** · {STORE_LABELS.get(e['store'], e['store'])} · {GAME_LABELS.get(e['game'], '')}",
            }
            if e["image"]:
                embed["thumbnail"] = {"url": e["image"]}
            embeds.append(embed)
        for i in range(0, len(embeds), 10):  # Discord allows 10 embeds per message
            self._post_discord(url, {"embeds": embeds[i:i + 10]})

    def _post_discord(self, url: str, payload: dict) -> None:
        for _ in range(3):
            response = httpx.post(url, json=payload, timeout=20)
            if response.status_code == 429:
                time.sleep(float(response.json().get("retry_after", 2)))
                continue
            response.raise_for_status()
            return

    def _email(self, events: list[dict]) -> None:
        cfg = self.config.get("email", {})
        events = self._wanted("email", events)
        if not cfg.get("enabled") or not events:
            return
        message = EmailMessage()
        message["Subject"] = f"TCG Tracker: {len(events)} alert(s) – {events[0]['title'][:60]}"
        message["From"] = cfg["from"]
        message["To"] = cfg["to"]
        lines = [f"{EVENT_LABELS[e['type']]}: {e['title']} – {describe(e)} – {e['url']}" for e in events]
        message.set_content("\n".join(lines))
        rows = "".join(
            f"<tr><td>{EVENT_LABELS[e['type']]}</td><td><a href=\"{html.escape(e['url'])}\">{html.escape(e['title'])}</a></td>"
            f"<td>{html.escape(describe(e))}</td><td>{STORE_LABELS.get(e['store'], e['store'])}</td></tr>"
            for e in events
        )
        message.add_alternative(f"<table cellpadding=6>{rows}</table>", subtype="html")
        with smtplib.SMTP(cfg["smtp_host"], cfg.get("smtp_port", 587), timeout=30) as smtp:
            if cfg.get("use_starttls", True):
                smtp.starttls()
            if cfg.get("username"):
                smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(message)

    def _push(self, events: list[dict]) -> None:
        events = self._wanted("push", events)
        subscriptions = self.db.query("SELECT * FROM push_subscriptions")
        if not events or not subscriptions:
            return
        payloads = [
            {"title": EVENT_LABELS[e["type"]], "body": f"{e['title']}\n{describe(e)} · {STORE_LABELS.get(e['store'], e['store'])}",
             "url": e["url"], "icon": e["image"], "tag": f"event-{e['id']}"}
            for e in events[:4]
        ]
        if len(events) > 4:
            payloads.append({"title": f"+{len(events) - 4} more alerts", "body": "Open TCG Tracker to see them all.",
                             "url": self.base_url + "/", "tag": "summary"})
        for sub in subscriptions:
            for payload in payloads:
                if not self.push_to(sub, payload):
                    break

    def push_to(self, sub, payload: dict) -> bool:
        from pywebpush import WebPushException, webpush

        vapid_public_key()  # ensures the key file exists
        try:
            webpush(
                subscription_info=json.loads(sub["subscription"]),
                data=json.dumps(payload),
                vapid_private_key=str(VAPID_KEY_PATH),
                vapid_claims={"sub": self.config.get("push", {}).get("subject", "mailto:admin@example.com")},
                ttl=3600,
            )
            return True
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                log.info("Removing expired push subscription")
                self.db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (sub["endpoint"],))
            else:
                log.warning("Push failed: %s", exc)
            return False
