import logging
import time
from urllib.parse import urlparse

import httpx

from ..models import Snapshot

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

log = logging.getLogger("tracker.stores")


class Store:
    name: str = ""
    label: str = ""
    domains: tuple[str, ...] = ()

    def __init__(self, games: list[str], delay: float):
        self.games = set(games)
        self.delay = delay
        self._last_request = 0.0
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8"},
            timeout=30,
            follow_redirects=True,
        )

    def get(self, url: str, **kwargs) -> httpx.Response:
        for attempt in range(4):
            wait = self.delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            response = self.client.get(url, **kwargs)
            # Some stores answer an exhausted rate limit with 429, WooCommerce also with 400.
            limited = response.status_code == 429 or (
                response.status_code == 400 and response.headers.get("RateLimit-Remaining") == "0"
            )
            if limited and attempt < 3:
                retry_after = float(response.headers.get("RateLimit-Retry-After") or response.headers.get("Retry-After") or 30)
                log.info("%s rate limited, waiting %.0fs", self.name, retry_after)
                time.sleep(min(retry_after, 120) + 1)
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("unreachable")

    def handles(self, url: str) -> bool:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def scan(self) -> list[Snapshot]:
        """All sealed products of the tracked games currently listed in the store."""
        raise NotImplementedError

    def fetch(self, url: str) -> Snapshot | None:
        """A single product by its URL (used for watchlist items)."""
        raise NotImplementedError
