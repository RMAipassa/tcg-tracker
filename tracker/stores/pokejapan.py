import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Snapshot, looks_sealed
from .base import Store


class PokeJapan(Store):
    name = "pokejapan"
    label = "TCGJapan"
    domains = ("tcgjapan.nl",)
    category_url = "https://tcgjapan.nl/nl/20-booster-boxen"
    catalog_interval_minutes = 60

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        if "pokemon" not in self.games:
            return []
        first = BeautifulSoup(self.get(self.category_url).text, "html.parser")
        pages = max(
            (
                int(match.group(1))
                for link in first.select(".pagination a[href]")
                if (match := re.search(r"[?&]page=(\d+)", link.get("href", "")))
            ),
            default=1,
        )
        for page in range(1, pages + 1):
            soup = first if page == 1 else BeautifulSoup(
                self.get(self.category_url, params={"page": page}).text,
                "html.parser",
            )
            for card in soup.select(".js-product-miniature[data-id-product]"):
                title_link = card.select_one(".product-title a[href]")
                if not title_link:
                    continue
                title = title_link.get_text(" ", strip=True)
                if not looks_sealed(title):
                    continue
                price = card.select_one(".product-price[content]")
                image = card.select_one(".product-thumbnail img[data-src], .product-thumbnail img[src]")
                snapshots[card["data-id-product"]] = Snapshot(
                    store=self.name,
                    store_product_id=card["data-id-product"],
                    url=title_link["href"],
                    title=title,
                    price_cents=round(float(price["content"]) * 100) if price else None,
                    in_stock=bool(price and not card.select_one(".product-unavailable")),
                    game="pokemon",
                    image=urljoin(self.category_url, image.get("data-src") or image.get("src")) if image else None,
                )
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        title = soup.select_one("h1")
        product_id = soup.select_one('#product_page_product_id[value]')
        price = soup.select_one('.current-price-value[content]')
        button = soup.select_one('button[data-button-action="add-to-cart"]')
        image = soup.select_one('.js-qv-product-cover[src], meta[property="og:image"][content]')
        canonical = soup.select_one('link[rel="canonical"][href]')
        if not title or not product_id:
            return None
        image_url = image.get("src") or image.get("content") if image else None
        return Snapshot(
            store=self.name,
            store_product_id=product_id["value"],
            url=canonical["href"] if canonical else url,
            title=title.get_text(" ", strip=True),
            price_cents=round(float(price["content"]) * 100) if price else None,
            in_stock=bool(button and not button.has_attr("disabled")),
            game="pokemon",
            image=urljoin(url, image_url) if image_url else None,
        )
