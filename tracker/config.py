import secrets
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.toml"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        example = (ROOT / "config.example.toml").read_text(encoding="utf-8")
        CONFIG_PATH.write_text(example.replace("replace-with-a-long-random-string", secrets.token_hex(32)), encoding="utf-8")
        raise SystemExit(f"Created {CONFIG_PATH}. Edit it (at least the password and base_url), then start again.")
    # utf-8-sig: tolerate the BOM that some Windows editors add.
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if config["web"].get("password") in ("", "change-me"):
        raise SystemExit(f"Set a real password under [web] in {CONFIG_PATH} before starting.")
    DATA_DIR.mkdir(exist_ok=True)
    return config
