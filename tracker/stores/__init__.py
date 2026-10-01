from .base import Store
from .bazaarofmagic import BazaarOfMagic
from .bescards import Bescards
from .bol import Bol
from .cardgameshop import CardGameShop
from .cardcorner import CardCorner
from .intertoys import Intertoys
from .mediamarkt import MediaMarkt
from .peppicollect import PeppiCollect
from .pkmncards import PkmnCards
from .pokejapan import PokeJapan
from .spellenhuis import Spellenhuis
from .speelkaartenwinkel import Speelkaartenwinkel
from .shopifycatalogs import CardsByBeard, OutpostBrussels, PokePower
from .tcgcompany import TcgCompany
from .tcgkingdom import TcgKingdom
from .tcgshop import TcgShop
from .tcgino import Tcgino
from .top1toys import Top1Toys
from .yellowlightning import YellowLightning
from .woocatalogs import Maximus, OppaCards
from .generic import JouwWebStore, MagentoStore, OdooStore, ShopifyStore, WooCommerceStore

STORE_CLASSES: dict[str, type[Store]] = {
    cls.name: cls
    for cls in (
        Bescards, TcgCompany, Intertoys, Bol, Top1Toys, MediaMarkt,
        TcgShop, PeppiCollect, YellowLightning, Spellenhuis, CardGameShop, Tcgino,
        PkmnCards, BazaarOfMagic, CardCorner, Speelkaartenwinkel, PokeJapan, TcgKingdom,
        PokePower, CardsByBeard, OutpostBrussels,
        Maximus, OppaCards,
    )
}
# Off unless enabled in config.toml.
DISABLED_BY_DEFAULT = {
    "bol", "top1toys", "mediamarkt", "tcgshop", "peppicollect", "yellowlightningcards", "spellenhuis",
    "cardgameshop", "tcgino",
    "pkmncards", "bazaarofmagic", "cardcorner", "speelkaartenwinkel", "pokejapan", "tcgkingdom",
    "pokepower", "cardsbybeard", "outpostbrussels",
    "maximus", "oppacards",
}
GENERIC_PLATFORMS = {
    "shopify": ShopifyStore,
    "woocommerce": WooCommerceStore,
    "magento": MagentoStore,
    "jouwweb": JouwWebStore,
    "odoo": OdooStore,
}


def build_stores(config: dict) -> dict[str, Store]:
    general = config["general"]
    configured = config.get("stores", {})
    games = general.get("games", ["pokemon", "mtg", "naruto"])
    delay = general.get("request_delay_seconds", 1.5)
    stores = {}
    for name, cls in STORE_CLASSES.items():
        options = configured.get(name, {})
        if options.get("enabled", name not in DISABLED_BY_DEFAULT):
            store = cls(games, delay)
            if hasattr(store, "configure"):
                store.configure(options)
            stores[name] = store
    for name, options in configured.items():
        platform = options.get("platform") if isinstance(options, dict) else None
        if isinstance(options, dict) and name not in stores and options.get("enabled", False) and platform in GENERIC_PLATFORMS:
            stores[name] = GENERIC_PLATFORMS[platform](name, options, games, delay)
    return stores
