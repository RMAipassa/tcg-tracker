"""Start TCG Tracker: web app + background scanner.

    python run.py                          run the server (host/port from config.toml)
    python run.py --host 0.0.0.0 --port 7777   override host/port (e.g. from AMP)
    python run.py --once                   run one scan, send notifications and exit
"""
import argparse
import logging
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _use_project_venv() -> None:
    """Make `python run.py` use the environment created by install.ps1."""
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return
    root = Path(__file__).resolve().parent
    python = root / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if python.is_file():
        raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]]))


if __name__ == "__main__":
    _use_project_venv()

from tracker.config import DATA_DIR, load_config

config = load_config()  # also creates data/
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(), RotatingFileHandler(DATA_DIR / "tracker.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")],
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy for a console

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TCG Tracker")
    parser.add_argument("--once", action="store_true", help="run one scan and exit")
    parser.add_argument("--host", help="bind address (default from config.toml)")
    parser.add_argument("--port", type=int, help="port (default from config.toml)")
    args = parser.parse_args()

    if args.once:
        from tracker.app import scan_and_notify

        print(f"{scan_and_notify()} new events")
    else:
        import uvicorn

        web = config["web"]
        uvicorn.run("tracker.app:app", host=args.host or web.get("host", "127.0.0.1"), port=args.port or web.get("port", 8080),
                    proxy_headers=True, forwarded_allow_ips="127.0.0.1")
