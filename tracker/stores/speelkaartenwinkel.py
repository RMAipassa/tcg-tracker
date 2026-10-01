from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Snapshot, is_sealed_product
from .base import Store


class Speelkaartenwinkel(Store):
    name = "speelkaartenwinkel"
    label = "Speelkaartenwinkel"
    domains = ("speelkaartenwinkel.nl",)
    category_url = "https://www.speelkaartenwinkel.nl/pokemon.html"
    catalog_interval_minutes = 60

    def scan(self) -> list[Snapshot]:
        cached = self._cached_catalog()
        if cached is not None:
            return cached
        snapshots: dict[str, Snapshot] = {}
        if "pokemon" not in self.games:
            return []
        url = self.category_url
        visited = set()
        while url and url not in visited:
            visited.add(url)
            soup = BeautifulSoup(self.get(url).text, "html.parser")
            for card in soup.select(".item.product.product-item"):
                title_link = card.select_one("a.product-item-link[href]")
                price = card.select_one('[data-price-type="finalPrice"][data-price-amount]')
                product = card.select_one('[data-product-id]')
                if not title_link or not product:
                    continue
                title = title_link.get_text(" ", strip=True)
                if not is_sealed_product(title):
                    continue
                image = card.select_one("img.product-image-photo[src]")
                snapshots[product["data-product-id"]] = Snapshot(
                    store=self.name,
                    store_product_id=product["data-product-id"],
                    url=title_link["href"],
                    title=title,
                    price_cents=round(float(price["data-price-amount"]) * 100) if price else None,
                    in_stock=bool(card.select_one('form[data-role="tocart-form"] button')),
                    game="pokemon",
                    image=urljoin(url, image["src"]) if image else None,
                )
            next_link = soup.select_one("a.action.next[href]")
            url = urljoin(url, next_link["href"]) if next_link else ""
        return self._remember_catalog(list(snapshots.values()))

    def fetch(self, url: str) -> Snapshot | None:
        soup = BeautifulSoup(self.get(url).text, "html.parser")
        main = soup.select_one(".product-primary-column")
        if not main:
            return None
        title = main.select_one("h1")
        product_id = main.select_one('#product_addtocart_form input[name="product"][value]')
        price = main.select_one('[data-price-type="finalPrice"][data-price-amount]')
        image = soup.select_one('meta[property="og:image"][content]')
        canonical = soup.select_one('link[rel="canonical"][href]')
        if not title or not product_id:
            return None
        return Snapshot(
            store=self.name,
            store_product_id=product_id["value"],
            url=canonical["href"] if canonical else url,
            title=title.get_text(" ", strip=True),
            price_cents=round(float(price["data-price-amount"]) * 100) if price else None,
            in_stock=bool(main.select_one(".product-info-stock-sku .stock.available")),
            game="pokemon",
            image=image["content"] if image else None,
        )
