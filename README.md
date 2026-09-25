# TCG Tracker

Personal drop tracker for sealed **Pokémon, Magic and Naruto** products at Dutch stores.
Scans every 15 minutes and alerts via **Discord**, **email** and **phone push** (installable web app).

| Store | How | Coverage |
|---|---|---|
| Bescards | Shopify `products.json` | full catalog |
| TCG Company | WooCommerce Store API | full catalog (singles excluded) |
| Intertoys | product data embedded in pages | first 36 trading-card listings + any watchlist URL |
| bol.com | – | not supported yet (bot protection) |

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

1. Install **Python 3.12+** from python.org (tick *Add python.exe to PATH*).
2. Copy this folder to the PC, e.g. `C:\tcg-tracker`.
3. Open **PowerShell as Administrator** in that folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File deploy\install.ps1 -Domain tcg.yourdomain.nl
   ```
   This creates the virtualenv, `config.toml`, two scheduled tasks that start at boot
   (the tracker and Caddy for HTTPS), and opens ports 80/443 in Windows Firewall.
4. Edit `config.toml`: set `password`, the Discord `webhook_url`
   (Discord → channel settings → Integrations → Webhooks), and optionally email SMTP.
5. **DNS**: add an A record `tcg.yourdomain.nl` → your public IP (check at whatismyip.com).
   If your home IP changes, use your DNS provider's dynamic DNS feature.
6. **Router**: forward TCP ports 80 and 443 to this PC's local IP.
7. Start both tasks (or reboot):
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
  This also works for items outside the catalog scan (e.g. singles, or older Intertoys listings).
- **Settings**: store health (last successful scan, errors), *Scan now*, push setup.

## Maintenance

- Logs: `data\tracker.log`. Database: `data\tracker.db` (SQLite; back it up if you care about history).
- If a store shows an error in Settings for a while, its site probably changed. The adapters live in
  `tracker\stores\` (one file per store).
- Run a single scan by hand: `.venv\Scripts\python.exe run.py --once`
- Adding a store: create `tracker\stores\<name>.py` with `scan()` and `fetch(url)` and register it in
  `tracker\stores\__init__.py`. Many Dutch shops run on Shopify or WooCommerce, so copying `bescards.py`
  or `tcgcompany.py` usually gets you most of the way.
