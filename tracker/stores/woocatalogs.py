import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import Snapshot, detect_game, is_sealed_product
from .base import Store
from .generic import _OTHER_GAME, _html_price


_SPORTS_PRODUCT = re.compile(r"football|soccer|voetbal|fifa|uefa|formula ?1|basketball|baseball|nba|nfl|mlb", re.I)


class WooHtmlCatalog(Store):
    base = ""
    categories: dict[str, tuple[str, ...]] = {}
    catalog_interval_minutes = 60

    def _cards(self, soup: BeautifulSoup):
        raise NotImplementedError

    def _snapshot(self, card, game: str) -> Snapshot | None:
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
                url = self.base + path
                visited = set()
                while url and url not in visited:
                    visited.add(url)
                    soup = BeautifulSoup(self.get(url).text, "html.parser")
                    for card in self._cards(soup):
                        snapshot = self._snapshot(card, game)
                        if snapshot:
                            snapshots[snapshot.store_product_id] = snapshot
                    next_link = soup.select_one("a.next.page-numbers[href]")
                    url = urljoin(url, next_link["href"]) if next_link else ""
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        target = urlparse(url).path.rstrip("/")
        cached = next((item for item in self.scan() if urlparse(item.url).path.rstrip("/") == target), None)
        if cached:
            return cached
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        summary = soup.select_one(".summary")
        title = soup.select_one("h1.product_title")
        if not summary or not title:
            return None
        sale_price = summary.select_one(".price ins .woocommerce-Price-amount")
        price = sale_price or summary.select_one(".price .woocommerce-Price-amount")
        image = soup.select_one('meta[property="og:image"][content]')
        canonical = soup.select_one('link[rel="canonical"][href]')
        title_text = title.get_text(" ", strip=True)
        return Snapshot(
            store=self.name,
            store_product_id=target,
            url=canonical["href"] if canonical else url,
            title=title_text,
            price_cents=_html_price(price.get_text(" ", strip=True)) if price else None,
            in_stock=bool(summary.select_one(".stock.in-stock, button.single_add_to_cart_button:not([disabled])")),
            game=detect_game(title_text + " " + url),
            image=image["content"] if image else None,
        )

    def _build_snapshot(
        self,
        card,
        game: str,
        title_selector: str,
        image_selector: str,
        stock: bool,
    ) -> Snapshot | None:
        title_link = card.select_one(title_selector)
        if not title_link:
            return None
        title = title_link.get_text(" ", strip=True)
        if not is_sealed_product(title):
            return None
        detected_game = detect_game(title)
        if (detected_game and detected_game != game) or _OTHER_GAME.search(title) or _SPORTS_PRODUCT.search(title):
            return None
        sale_price = card.select_one(".price ins .woocommerce-Price-amount")
        price = sale_price or card.select_one(".price .woocommerce-Price-amount")
        image = card.select_one(image_selector)
        url = title_link["href"]
        product_id = urlparse(url).path.rstrip("/")
        image_url = None
        if image:
            image_url = image.get("data-src") or image.get("data-lazy-src") or image.get("data-wood-src") or image.get("src")
        return Snapshot(
            store=self.name,
            store_product_id=product_id,
            url=url,
            title=title,
            price_cents=_html_price(price.get_text(" ", strip=True)) if price else None,
            in_stock=stock,
            game=game,
            image=urljoin(self.base, image_url) if image_url else None,
        )


class Maximus(WooHtmlCatalog):
    name = "maximus"
    label = "Maximus"
    domains = ("maximus.be",)
    base = "https://maximus.be"
    catalog_interval_minutes = 90
    categories = {
        "pokemon": ("/product-categorie/pokemon/",),
        "mtg": ("/product-categorie/magic-the-gathering/",),
    }

    def __init__(self, games: list[str], delay: float):
        super().__init__(games, max(delay, 10))

    def _cards(self, soup: BeautifulSoup):
        return soup.select("li.product")

    def _snapshot(self, card, game: str) -> Snapshot | None:
        return self._build_snapshot(
            card,
            game,
            ".mfn-li-product-row-title a[href]",
            ".product-loop-thumb img[src]",
            "instock" in card.get("class", []),
        )


class OppaCards(WooHtmlCatalog):
    name = "oppacards"
    label = "Oppa Cards"
    domains = ("oppacards.com",)
    base = "https://oppacards.com"
    categories = {
        "pokemon": (
            "/product-category/pokemon-booster-box/",
            "/product-category/pokemon-booster-pack/",
            "/product-category/pokemon-collection-box/",
            "/product-category/pokemon-elite-trainer-boxen/",
            "/product-category/pokemon-tin/",
        ),
        "mtg": ("/product-category/magic-the-gathering/",),
    }

    def _cards(self, soup: BeautifulSoup):
        return soup.select(".products .product")

    def _snapshot(self, card, game: str) -> Snapshot | None:
        return self._build_snapshot(
            card,
            game,
            ".wd-entities-title a[href]",
            ".wd-product-img-link img[src]",
            "instock" in card.get("class", []),
        )
