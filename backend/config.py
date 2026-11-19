"""Loads settings from .env and picks the try-on provider."""
import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

from .tryon.base import TryOnProvider

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

UPLOADS_DIR = BASE_DIR / "uploads"            # temp inputs (deleted after use)
OUTPUTS_DIR = BASE_DIR / "outputs"            # try-on results (deleted after 1 hour)
DATA_DIR = BASE_DIR / "data"                  # database file
PRODUCTS_DIR = DATA_DIR / "products"          # product (clothing) images
FRONTEND_DIR = BASE_DIR / "frontend"
DB_PATH = DATA_DIR / "store.db"

# --- Try-on provider ---
TRYON_PROVIDER = os.getenv("TRYON_PROVIDER", "huggingface").lower()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip() or None

# --- Try-on image quality ---
# Enlarge the garment mask (needs a 2nd Space call per try-on = 2x GPU quota). Set false to save quota.
EXPAND_MASK = os.getenv("TRYON_EXPAND_MASK", "true").strip().lower() not in ("0", "false", "no")
# How much to grow the mask, as % of image width (2.6% = about 20 px at 768 px wide)
MASK_EXPAND_PCT = float(os.getenv("TRYON_MASK_EXPAND_PCT", "2.6"))

# --- Admin login (store owner) ---
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip().lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# Used to sign the login cookie. If missing we make a random one (logins reset on restart).
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logging.getLogger("config").warning("SECRET_KEY not set in .env - admin sessions reset on every restart.")
SESSION_HOURS = 12

for _d in (UPLOADS_DIR, OUTPUTS_DIR, PRODUCTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def get_provider() -> TryOnProvider:
    """Factory: add new providers here (one `if` per provider)."""
    if TRYON_PROVIDER == "huggingface":
        from .tryon.huggingface import HuggingFaceTryOn
        return HuggingFaceTryOn(hf_token=HF_TOKEN)
    # elif TRYON_PROVIDER == "gemini":
    #     from .tryon.gemini import GeminiTryOn
    #     return GeminiTryOn(...)
    raise ValueError(f"Unknown TRYON_PROVIDER: {TRYON_PROVIDER!r}")
