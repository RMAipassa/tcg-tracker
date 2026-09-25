from .base import Store
from .bescards import Bescards
from .bol import Bol
from .intertoys import Intertoys
from .tcgcompany import TcgCompany

STORE_CLASSES: dict[str, type[Store]] = {cls.name: cls for cls in (Bescards, TcgCompany, Intertoys, Bol)}
# Off unless enabled in config.toml.
DISABLED_BY_DEFAULT = {"bol"}


def build_stores(config: dict) -> dict[str, Store]:
    general = config["general"]
    stores = {}
    for name, cls in STORE_CLASSES.items():
        options = config.get("stores", {}).get(name, {})
        if options.get("enabled", name not in DISABLED_BY_DEFAULT):
            store = cls(general.get("games", ["pokemon", "mtg", "naruto"]), general.get("request_delay_seconds", 1.5))
            if hasattr(store, "configure"):
                store.configure(options)
            stores[name] = store
    return stores
