# TCG Tracker

Personal drop tracker for sealed **Pokémon, Magic and Naruto** products at Dutch stores.
Scans every 15 minutes and alerts via **Discord**, **email** and **phone push** (installable web app).

| Store | How | Coverage |
|---|---|---|
| Bescards | Shopify `products.json` | full catalog |
| TCG Company | WooCommerce Store API | full catalog (singles excluded) |
| Intertoys | product data embedded in pages | first 36 trading-card listings + any watchlist URL |
| bol.com | headless browser (Playwright) | all Pokémon category pages + any watchlist URL |
| Top1Toys | public Magento GraphQL | Pokémon TCG categories + any watchlist URL |
| MediaMarkt NL | server-rendered catalog data | Pokémon-card category, marketplace sellers excluded |
| TCGShop | public Ecwid storefront API | Pokémon and MTG catalog |
| Peppi Collect | server-rendered JouwWeb catalog | sealed Pokémon and MTG products |
| Yellow Lightning Cards | server-rendered WooCommerce catalog | sealed Pokémon products |
| Spellenhuis | public Shopware listings | sealed Pokémon and MTG products |
| CardGameShop | server-rendered category listings | sealed Pokémon, MTG and Naruto products |
| TCGino | category listings and product pages | sealed Pokémon and MTG products; hourly full refresh |
| PKMNCards | server-rendered ePages catalog | sealed Pokémon products |
| Bazaar of Magic | server-rendered category listings | sealed Pokémon and MTG products; hourly refresh |
| CardCorner | server-rendered JTL catalog | sealed Pokémon, MTG and Naruto products; hourly refresh |
| Speelkaartenwinkel | server-rendered Magento catalog | sealed Pokémon products; hourly refresh |
| TCGJapan | server-rendered PrestaShop catalog | sealed Japanese Pokémon products; hourly refresh |
| TCG Kingdom | server-rendered MyOnlineStore catalog | sealed Pokémon, MTG and Naruto products; hourly refresh |
| PokePower | paced Shopify collection feeds | sealed Pokémon and MTG products; 90-minute refresh |
| Cards By Beard | server-rendered Shopify collections | sealed Pokémon and MTG products; 90-minute refresh |
| Outpost Brussels | paced Shopify collection feeds | sealed Pokémon and MTG products; 90-minute refresh |
| Maximus | server-rendered WooCommerce categories | sealed Pokémon and MTG products; 90-minute refresh |
| Oppa Cards | server-rendered WooCommerce categories | sealed Pokémon and MTG products; hourly refresh |
| Configured Shopify shops | public `products.json` | paginated sealed catalog |
| Configured WooCommerce shops | public Store API | paginated or category-scoped sealed catalog |
| Configured Magento shops | public GraphQL | configured TCG categories |
| Configured JouwWeb shops | embedded public product data | configured sealed-product categories |
| Configured Odoo shops | server-rendered product cards | configured TCG categories |

## Alerts

| Type | When |
|---|---|
| 🆕 `new` | a product appears that wasn't there in the previous scan |
| ✅ `restock` | a product goes from sold out to in stock |
| 📉 `price_drop` | any tracked product drops ≥ `price_drop_percent` (default 10%) since the previous scan |
| 🎯 `target` | a watchlist item is in stock at or below your target price (repeats only if it drops further) |

The first scan of a store only records a baseline, so you don't get 1,000 "new" alerts.
Per channel you choose which types it gets (`events = [...]` in `config.toml`).

## Install on Windows

1. Copy this folder to the PC, e.g. `C:\tcg-tracker`.
2. Open **PowerShell as Administrator** in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\install.ps1 -Domain tcg.yourdomain.nl
   ```
   This installs Python 3.12 through `winget` when needed, creates the virtualenv,
   installs all Python dependencies and Playwright browser support,
   creates `config.toml`, two scheduled tasks that start at boot
   (the tracker and Caddy for HTTPS), and opens ports 80/443 in Windows Firewall.
3. Edit `config.toml`: set `password`, the Discord `webhook_url`
   (Discord → channel settings → Integrations → Webhooks), and optionally email SMTP.
4. **DNS**: add an A record `tcg.yourdomain.nl` → your public IP (check at whatismyip.com).
   If your home IP changes, use your DNS provider's dynamic DNS feature.
5. **Router**: forward TCP ports 80 and 443 to this PC's local IP.
6. Start both tasks (or reboot):
   ```powershell
   Start-ScheduledTask "TCG Tracker"; Start-ScheduledTask "TCG Tracker HTTPS (Caddy)"
   ```
   Caddy gets an HTTPS certificate automatically on the first visit.

## Alternative: run it in AMP (CubeCoders) with the Python App Runner

AMP then handles start/stop, auto-restart and the console; only HTTPS (Caddy) runs outside AMP.

1. Make sure Python 3.12+ is installed **for all users** with the `py` launcher in the System PATH
   (python.org installer → *Customize installation* → *Install Python for all users* and *py launcher*).
2. In AMP create an instance from the **Python App Runner** template.
3. Instance settings:
   | Setting | Value |
   |---|---|
   | App Download Type | *None* (copy files yourself) or *Git repo* (if you push this folder to a private repo) |
   | Python Version | 3.12 or newer |
   | Python Packages Install Method | *Requirements.txt file* |
   | App Run Mode | *Python script* |
   | App Script Filename | `run.py` |
   | App Command Line Arguments | `--host 127.0.0.1 --port 8080` |
4. With *None*: copy all files of this folder into the instance's `python-app-runner\` directory.
5. Click **Update** in AMP (creates the venv and installs `requirements.txt`), then **Start**.
   The first start creates `config.toml` and stops. Edit it (password, `base_url`, Discord, email) and start again.
6. HTTPS: from a copy of this folder, in an Administrator PowerShell, run
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\install.ps1 -Domain tcg.yourdomain.nl -CaddyOnly -Port 8080
   ```
   then do the DNS and router steps (5 and 6) from above.

`config.toml` and `data\` are not overwritten by AMP updates (they're gitignored and not in the download).

**Can't forward ports?** Use a Cloudflare Tunnel instead of Caddy (domain must be on Cloudflare):
run the installer with `-SkipCaddy`, install `cloudflared` and point the tunnel to `http://localhost:8080`.

## Phone app (push notifications)

- **iPhone** (iOS 16.4+): open `https://tcg.yourdomain.nl` in Safari → Share → *Add to Home Screen*.
  Open it **from the home screen**, log in, Settings → *Enable on this device*.
- **Android**: open it in Chrome → *Install app* → Settings → *Enable on this device*.
- Tap *Send test* to check it works.

## Using it

- **Alerts** tab: everything that happened, newest first.
- **Products** tab: all tracked sealed products; tap ＋ to add one to your watchlist.
- **Watchlist** tab: paste any product URL from a supported store with an optional target price.
  This also works for items outside the catalog scan (e.g. singles or older listings).
- **Settings**: store health (last successful scan, errors), *Scan now*, push setup.

## bol.com (experimental)

bol.com only works through a real browser and **blocks automated browsers**. This adapter omits the standard
WebDriver signal, but it may still be detected. When it sees a block page or captcha it pauses for
`pause_hours_when_blocked` (default 24h) and shows the error under Settings → Stores.

- The catalog scan follows every page of bol's Pokémon cards category and reads each product card's price,
  availability and image without opening hundreds of individual product pages.
- Catalog results are refreshed every `catalog_interval_minutes` (default 60, minimum 30). Set
  `catalog_pages = 0` to follow every page, or a positive number to cap the requests per scan.
- Watchlist items found in the category results reuse that data. Other bol URLs are loaded individually at
  most once per `min_interval_minutes` (default 60, minimum 30).
- The Windows deployment installer sets up Playwright automatically and uses Chrome or Edge (installing Chrome
  when neither is present). For a local or existing installation, run:
  ```powershell
  powershell -ExecutionPolicy Bypass -File .\install.ps1
  python run.py --host 127.0.0.1 --port 8081
  ```
  `run.py` automatically uses the local `.venv` created by the installer.
  In AMP, `requirements.txt` installs Playwright; make sure Chrome or Edge is installed on the host.
  Then set `enabled = true` under `[stores.bol]` in `config.toml`.
- Check the parser against a page you saved from your own browser (Ctrl+S → "Webpagina, alleen HTML"):
  `python -m tracker.stores.bol saved-page.html`
- The catalog and product parsers are tested against the live site. Some bol search results return HTTP 403
  on their detail pages even in a regular browser; those products can still be tracked from the category page.

## Additional configuration-driven stores

Store integrations can be added without Python code when a shop exposes a supported public Shopify,
WooCommerce, Magento, JouwWeb or Odoo catalog. Each store is isolated in the scanner and appears separately in
store health and filters.

```toml
[stores.example_shop]
enabled = true
platform = "shopify" # or "woocommerce", "magento", "jouwweb", "odoo"
label = "Example Shop"
base_url = "https://example.nl"
```

For Shopify stores whose product titles and tags omit the game, set a known default and optional collection:

```toml
default_game = "pokemon"
collections = { pokemon = "pokemon" }
```

Set `include_all_products = false` to scan only those collections. A collection value may also be a list of
handles. WooCommerce stores can use `categories = { pokemon = [123, 456], mtg = 789 }` to avoid singles and
other unrelated products.

Magento stores use category ids for each tracked game:

```toml
platform = "magento"
categories = { pokemon = "123", mtg = "456", naruto = "789" }
```

Odoo stores use the same `categories` map. Values may be category ids or full `/shop/category/...` paths.

The example configuration includes 48 Shopify, WooCommerce, Magento, JouwWeb and Odoo shops verified from the
TCGSniper directory, plus 23 fixed public-catalog adapters. Four fixed integrations (Bescards, Intertoys,
TCG Company and TCGino) are not currently listed by TCGSniper, so these integrations cover 67 of its 102 stores
while supporting 71 stores in total. They are disabled by default so a new installation opts into the extra
requests deliberately. This installation has them enabled in its private `config.toml`. Stores that return an
access challenge are paused before retrying. Dead domains, duplicate storefronts,
marketplaces and shops without a usable target catalog remain excluded.

## TODO

- bol.com via a sanctioned route, if one becomes available (partner programme / Marketing Catalog API),
  or by reading bol.com "weer leverbaar" emails from a dedicated mailbox.
- More Dutch TCG shops (Shopify/WooCommerce ones are quick to add).

## Maintenance

- Logs: `data\tracker.log`. Database: `data\tracker.db` (SQLite; back it up if you care about history).
- If a store shows an error in Settings for a while, its site probably changed. The adapters live in
  `tracker\stores\` (one file per store).
- Run a single scan by hand: `.venv\Scripts\python.exe run.py --once`
- Adding a store: create `tracker\stores\<name>.py` with `scan()` and `fetch(url)` and register it in
  `tracker\stores\__init__.py`. Many Dutch shops run on Shopify or WooCommerce, so copying `bescards.py`
  or `tcgcompany.py` usually gets you most of the way.
