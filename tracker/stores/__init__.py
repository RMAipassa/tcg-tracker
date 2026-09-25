from .base import Store
from .bescards import Bescards
from .intertoys import Intertoys
from .tcgcompany import TcgCompany

STORE_CLASSES: dict[str, type[Store]] = {cls.name: cls for cls in (Bescards, TcgCompany, Intertoys)}


def build_stores(config: dict) -> dict[str, Store]:
    general = config["general"]
    stores = {}
    for name, cls in STORE_CLASSES.items():
        if config.get("stores", {}).get(name, {}).get("enabled", True):
            stores[name] = cls(general.get("games", ["pokemon", "mtg", "naruto"]), general.get("request_delay_seconds", 1.5))
    return stores
