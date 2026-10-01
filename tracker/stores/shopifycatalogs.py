import html
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store
from .generic import _html_price


class ShopifyCollectionCatalog(Store):
    base = ""
    categories: dict[str, tuple[str, ...]] = {}
    paginated = True
    use_json_feeds = False
    json_request_delay_seconds = 65
    catalog_interval_minutes = 90

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, max(delay, self.json_request_delay_seconds) if self.use_json_feeds else delay)

    def _cards(self, soup: BeautifulSoup, game: str) -> list[Snapshot]:
        raise NotImplementedError

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        for game, paths in self.categories.items():
            if game not in self.games:
                continue
            for path in paths:
                if self.use_json_feeds:
                    page = 1
                    while True:
                        products = self.get(
                            f"{self.base}{path}/products.json",
                            params={"limit": 250, "page": page},
                        ).json()["products"]
                        for product in products:
                            snapshot = self._json_snapshot(product, game)
                            if snapshot:
                                snapshots[snapshot.store_product_id] = snapshot
                        if len(products) < 250:
                            break
                        page += 1
                    continue
                page = 1
                while True:
                    url = self.base + path
                    soup = BeautifulSoup(self.get(url, params={"page": page} if page > 1 else None).text, "html.parser")
                    cards = self._cards(soup, game)
                    for snapshot in cards:
                        snapshots[snapshot.store_product_id] = snapshot
                    if not self.paginated or not cards or not self._has_page(soup, page + 1):
                        break
                    page += 1
        return self._remember_catalog(list(snapshots.values()))

    def _json_snapshot(self, product: dict, game: str) -> Snapshot | None:
        title = html.unescape(product.get("title", "")).strip()
        if not is_sealed_product(title):
            return None
        variants = product.get("variants") or []
        available = [variant for variant in variants if variant.get("available")]
        prices = [
            round(float(variant["price"]) * 100)
            for variant in (available or variants)
            if variant.get("price") not in (None, "")
        ]
        images = product.get("images") or []
        first_image = images[0] if images else product.get("featured_image")
        image = first_image.get("src") if isinstance(first_image, dict) else first_image
        if image and image.startswith("//"):
            image = "https:" + image
        handle = product["handle"]
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]),
            url=f"{self.base}/products/{handle}",
            title=title,
            price_cents=min(prices) if prices else None,
            in_stock=bool(available),
            game=game,
            image=image,
        )

    @staticmethod
    def _has_page(soup: BeautifulSoup, page: int) -> bool:
        return any(
            str(page) in parse_qs(urlparse(link.get("href", "")).query).get("page", [])
            for link in soup.select('a[href*="page="]')
        )

    def fetch(self, url: str) -> Snapshot | None:
        target = urlparse(url).path.rstrip("/")
        cached = next((item for item in self.scan() if urlparse(item.url).path.rstrip("/") == target), None)
        if cached:
            return cached
        handle = target.rsplit("/", 1)[-1]
        if not handle:
            return None
        product = self.get(f"{self.base}/products/{handle}.js").json()
        title = product.get("title", "").strip()
        variants = product.get("variants") or []
        available = [variant for variant in variants if variant.get("available")]
        prices = [int(variant["price"]) for variant in (available or variants) if variant.get("price") is not None]
        images = product.get("images") or []
        return Snapshot(
            store=self.name,
            store_product_id=str(product["id"]) if self.use_json_feeds else f"/products/{handle}",
            url=f"{self.base}/products/{handle}",
            title=title,
            price_cents=min(prices) if prices else None,
            in_stock=bool(available),
            game=detect_game(title + " " + str(product.get("product_type") or "")),
            image=images[0] if images else None,
        )

    def _snapshot(
        self,
        card,
        game: str,
        title_selector: str,
        price_selector: str,
        stock_selector: str,
        image_selector: str,
    ) -> Snapshot | None:
        title_link = card.select_one(title_selector)
        if not title_link:
            return None
        title = title_link.get_text(" ", strip=True)
        if not is_sealed_product(title):
            return None
        path = urlparse(title_link["href"]).path
        product_path = path[path.find("/products/"):] if "/products/" in path else path
        price = card.select_one(price_selector)
        image = card.select_one(image_selector)
        image_url = image.get("src") if image else None
        if image_url and image_url.startswith("//"):
            image_url = "https:" + image_url
        return Snapshot(
            store=self.name,
            store_product_id=product_path.rstrip("/"),
            url=urljoin(self.base, product_path),
            title=title,
            price_cents=_html_price(price.get_text(" ", strip=True)) if price else None,
            in_stock=bool(card.select_one(stock_selector)),
            game=game,
            image=image_url,
        )


class PokePower(ShopifyCollectionCatalog):
    name = "pokepower"
    label = "PokePower"
    domains = ("poke-power.eu",)
    base = "https://poke-power.eu"
    use_json_feeds = True
    categories = {
        "pokemon": ("/collections/tcg-izdelki",),
        "mtg": ("/collections/magic-the-gathering-karte-in-dodatki",),
    }

    def _cards(self, soup: BeautifulSoup, game: str) -> list[Snapshot]:
        snapshots = []
        for card in soup.select("product-card"):
            snapshot = self._snapshot(
                card,
                game,
                ".card__title a[href]",
                ".price__current .js-value",
                '.product-inventory__status:not([data-inventory-level="none"])',
                ".card__main-image[src]",
            )
            if snapshot:
                snapshots.append(snapshot)
        return snapshots


class CardsByBeard(ShopifyCollectionCatalog):
    name = "cardsbybeard"
    label = "Cards By Beard"
    domains = ("cardsbybeard.eu",)
    base = "https://cardsbybeard.eu"
    paginated = False
    categories = {
        "pokemon": ("/collections/pokemon-sealed-producten",),
        "mtg": ("/collections/mtg-sealed",),
    }

    def _cards(self, soup: BeautifulSoup, game: str) -> list[Snapshot]:
        snapshots = []
        for card in soup.select(".cb-pcard"):
            snapshot = self._snapshot(
                card,
                game,
                ".cb-pcard__title[href]",
                ".cb-pcard__price--current",
                ".cb-pcard__add:not([disabled])",
                ".cb-pcard__image img[src]",
            )
            if snapshot:
                snapshots.append(snapshot)
        return snapshots


class OutpostBrussels(ShopifyCollectionCatalog):
    name = "outpostbrussels"
    label = "Outpost Brussels"
    domains = ("outpostbrussels.be",)
    base = "https://outpostbrussels.be"
    use_json_feeds = True
    categories = {
        "pokemon": ("/collections/pokemon",),
        "mtg": ("/collections/magic-the-gathering",),
    }

    def _cards(self, soup: BeautifulSoup, game: str) -> list[Snapshot]:
        snapshots = []
        for card in soup.select(".product-card-wrapper"):
            snapshot = self._snapshot(
                card,
                game,
                ".card__heading a.full-unstyled-link[href]",
                ".price-item--sale.price-item--last, .price__regular .price-item--regular",
                'button[name="add"]:not([disabled])',
                ".card__media img[src]",
            )
            if snapshot:
                snapshots.append(snapshot)
        return snapshots
