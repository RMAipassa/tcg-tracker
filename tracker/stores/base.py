import logging
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from ..models import Snapshot

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

log = logging.getLogger("tracker.stores")


class StoreBlocked(Exception):
    """The store refused access (block page, captcha). The scanner stops asking it for this cycle."""


class Store:
    name: str = ""
    label: str = ""
    domains: tuple[str, ...] = ()
    # False: the store has no catalog scan, only watchlist items are fetched.
    catalog: bool = True
    # True only for reliable APIs whose tracked category can legitimately be empty.
    allow_empty_catalog: bool = False
    # Minimum time between two fetches of the same watchlist item (0 = every cycle).
    min_interval_minutes: int = 0
    pause_minutes_when_rate_limited: int = 60

    def __init__(self, games: list[str], delay: float):
        self.games = set(games)
        self.delay = delay
        self._last_request = 0.0
        self._catalog_cache: list[Snapshot] | None = None
        self._catalog_cached_at = 0.0
        self._paused_until = 0.0
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"},
            timeout=30,
            follow_redirects=True,
        )

    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        if time.monotonic() < self._paused_until:
            minutes = max(1, round((self._paused_until - time.monotonic()) / 60))
            raise StoreBlocked(f"rate-limit pause active for about {minutes} more minutes")
        for attempt in range(4):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.TransportError:
                if method.upper() != "GET" or attempt >= 3:
                    raise
                retry_after = min(2 ** attempt * 2, 15)
                log.info("%s request failed in transit, waiting %.0fs", self.name, retry_after)
                time.sleep(retry_after)
                continue
            # Some stores answer an exhausted rate limit with 429, WooCommerce also with 400.
            limited = response.status_code == 429 or (
                response.status_code == 400 and response.headers.get("RateLimit-Remaining") == "0"
            )
            retry_header = response.headers.get("RateLimit-Retry-After") or response.headers.get("Retry-After")
            retry_after = None
            if retry_header:
                try:
                    retry_after = float(retry_header)
                except ValueError:
                    try:
                        retry_after = max(
                            0,
                            (parsedate_to_datetime(retry_header) - datetime.now(timezone.utc)).total_seconds(),
                        )
                    except (TypeError, ValueError, OverflowError):
                        pass
            if limited and attempt == 0 and retry_after is not None and retry_after <= 120:
                log.info("%s rate limited, waiting %.0fs", self.name, retry_after)
                time.sleep(retry_after + 1)
                continue
            if limited:
                pause_seconds = max(self.pause_minutes_when_rate_limited * 60, retry_after or 0)
                self._paused_until = time.monotonic() + pause_seconds
                pause_minutes = max(1, round(pause_seconds / 60))
                raise StoreBlocked(f"rate limited; pausing for {pause_minutes} minutes")
            if response.status_code in (403, 503):
                body = response.text.lower()
                challenged = response.headers.get("server", "").lower() == "cloudflare" or any(
                    marker in body for marker in ("cf-chl", "attention required", "just a moment", "access denied")
                )
                if challenged:
                    self._paused_until = time.monotonic() + self.pause_minutes_when_rate_limited * 60
                    raise StoreBlocked(f"access challenge; pausing for {self.pause_minutes_when_rate_limited} minutes")
            response.raise_for_status()
            self._paused_until = 0.0
            return response
        raise RuntimeError("unreachable")

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)

    def handles(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def _cached_catalog(self) -> list[Snapshot] | None:
        interval = getattr(self, "catalog_interval_minutes", 0)
        if (
            self._catalog_cache is not None
            and interval
            and time.monotonic() - self._catalog_cached_at < interval * 60
        ):
            return self._catalog_cache
        return None

    def _remember_catalog(self, snapshots: list[Snapshot]) -> list[Snapshot]:
        self._catalog_cache = snapshots
        self._catalog_cached_at = time.monotonic()
        return snapshots

    def scan(self) -> list[Snapshot]:
        """All sealed products of the tracked games currently listed in the store."""
        raise NotImplementedError

    def fetch(self, url: str) -> Snapshot | None:
        """A single product by its URL (used for watchlist items)."""
        raise NotImplementedError
